"""
gh_client.py — a rate-limit-aware GitHub REST client for code-corpus mining.

Only three endpoints are used by Phase 1:
  - GET /search/code   (the "search" rate bucket: ~10 req/min authenticated)
  - GET /repos/{full}  (the "core" rate bucket: 5000 req/hr authenticated)
  - GET {git_url}      (blob fetch; also "core" bucket)

Design notes
------------
* Code search REST API REQUIRES authentication. Without a token it returns 401.
* The search endpoint caps results at 1000 per query (100/page x 10 pages).
  Requesting page > 10 returns 422. Callers must respect this; partition.py
  slices queries so each slice stays under 1000.
* We react to rate limits from response headers rather than guessing:
    - 403 + Retry-After                -> secondary (abuse) limit; sleep then retry
    - 403 + X-RateLimit-Remaining: 0   -> primary limit; sleep to reset then retry
    - 429                              -> sleep Retry-After then retry
    - 5xx / connection error           -> exponential backoff, capped retries
    - 422                              -> ValidationError (never retried)
    - 401                              -> AuthError (never retried)
"""

from __future__ import annotations

import base64
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

import requests

API = "https://api.github.com"
UA = "presigned-url-corpus-study/phase1 (research; contact via repo)"


class GitHubError(Exception):
    pass


class AuthError(GitHubError):
    pass


class ValidationError(GitHubError):
    pass


@dataclass
class RateInfo:
    remaining: Optional[int] = None
    limit: Optional[int] = None
    reset: Optional[int] = None


@dataclass
class GitHubClient:
    token: str
    session: requests.Session = field(default_factory=requests.Session)
    sleep: Callable[[float], None] = time.sleep
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("gh"))
    max_retries: int = 6
    # counters for the run report / debugging
    n_requests: int = 0
    n_sleeps: int = 0
    slept_seconds: float = 0.0
    last_rate: Dict[str, RateInfo] = field(default_factory=dict)

    def _headers(self, text_match: bool = False) -> Dict[str, str]:
        accept = (
            "application/vnd.github.text-match+json"
            if text_match
            else "application/vnd.github+json"
        )
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": UA,
        }

    def _record_rate(self, bucket: str, resp: requests.Response) -> None:
        try:
            self.last_rate[bucket] = RateInfo(
                remaining=int(resp.headers.get("X-RateLimit-Remaining", "-1")),
                limit=int(resp.headers.get("X-RateLimit-Limit", "-1")),
                reset=int(resp.headers.get("X-RateLimit-Reset", "0")),
            )
        except (TypeError, ValueError):
            pass

    def _sleep_for(self, seconds: float, why: str) -> None:
        seconds = max(0.0, seconds)
        self.n_sleeps += 1
        self.slept_seconds += seconds
        self.logger.info("sleeping %.1fs (%s)", seconds, why)
        self.sleep(seconds)

    def _request(self, url: str, params=None, bucket: str = "core", text_match=False) -> requests.Response:
        attempt = 0
        while True:
            attempt += 1
            self.n_requests += 1
            try:
                resp = self.session.get(
                    url, params=params, headers=self._headers(text_match), timeout=30
                )
            except requests.RequestException as e:
                if attempt > self.max_retries:
                    raise GitHubError(f"network error after {attempt} attempts: {e}")
                backoff = min(60.0, (2 ** attempt)) + random.uniform(0, 1.0)
                self._sleep_for(backoff, f"network error: {e}")
                continue

            self._record_rate(bucket, resp)
            code = resp.status_code

            if code == 200:
                return resp

            if code == 401:
                raise AuthError(
                    "401 Unauthorized. Code search requires a valid token. "
                    "Set GITHUB_TOKEN (classic PAT, no scopes needed for public "
                    "code search, or a fine-grained token with public-repo read)."
                )

            if code == 422:
                # e.g. page>10, or a malformed query. Not retryable.
                raise ValidationError(f"422 for {resp.url}: {resp.text[:300]}")

            if code in (403, 429):
                retry_after = resp.headers.get("Retry-After")
                remaining = resp.headers.get("X-RateLimit-Remaining")
                if retry_after is not None:
                    self._sleep_for(float(retry_after) + 1.0, f"{code} Retry-After")
                elif remaining is not None and remaining == "0":
                    reset = int(resp.headers.get("X-RateLimit-Reset", "0"))
                    wait = reset - time.time()
                    self._sleep_for(wait + 1.0, f"{code} primary limit reset")
                else:
                    # Unclear 403 (could be secondary limit without header). Back off.
                    if attempt > self.max_retries:
                        raise GitHubError(f"403 after {attempt} attempts: {resp.text[:200]}")
                    self._sleep_for(min(90.0, 2 ** attempt) + random.uniform(0, 2), "403 (no header)")
                continue

            if 500 <= code < 600:
                if attempt > self.max_retries:
                    raise GitHubError(f"{code} after {attempt} attempts")
                self._sleep_for(min(60.0, 2 ** attempt) + random.uniform(0, 1), f"{code} server error")
                continue

            raise GitHubError(f"unexpected {code} for {resp.url}: {resp.text[:200]}")

    # ---- public API ---------------------------------------------------------

    def search_code(self, q: str, page: int = 1, per_page: int = 100, text_match: bool = False) -> dict:
        if page > 10:
            raise ValidationError("search_code page must be <= 10 (1000-result cap)")
        resp = self._request(
            f"{API}/search/code",
            params={"q": q, "per_page": per_page, "page": page},
            bucket="search",
            text_match=text_match,
        )
        return resp.json()

    def get_repo(self, full_name: str) -> dict:
        resp = self._request(f"{API}/repos/{full_name}", bucket="core")
        return resp.json()

    def get_blob_text(self, git_url: str, max_bytes: int = 400_000) -> Optional[str]:
        """Fetch a git blob (base64) and decode to text. Returns None if too large
        or undecodable as UTF-8 (binary)."""
        resp = self._request(git_url, bucket="core")
        data = resp.json()
        if data.get("encoding") != "base64":
            return None
        raw = base64.b64decode(data.get("content", ""))
        if len(raw) > max_bytes:
            return None
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None


def client_from_env(logger: Optional[logging.Logger] = None) -> GitHubClient:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise AuthError("GITHUB_TOKEN is not set in the environment.")
    return GitHubClient(token=token, logger=logger or logging.getLogger("gh"))
