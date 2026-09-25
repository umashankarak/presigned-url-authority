"""
partition.py — build search queries and adaptively partition them by file size
so every slice returns <= 1000 results (the GitHub search cap).

The GitHub code-search API caps any single query at 1000 results. For a common
term this means a naive query silently drops most matches. The standard fix is
to slice the query space until each slice is under the cap and union the slices.

We slice on the `size:` qualifier (file size in bytes). For each base query we
probe total_count with a cheap per_page=1 request; if a size range exceeds the
cap we bisect it and recurse. A single-byte range that still exceeds the cap is
irreducible and reported as truncated (logged for the sampling-frame honesty).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterator, List, Tuple

logger = logging.getLogger("partition")


@dataclass(frozen=True)
class BaseQuery:
    term: str
    language: str

    def q(self, lo: int, hi: int) -> str:
        # Quote the term so multi-token / underscore terms are matched literally.
        return f'"{self.term}" language:{self.language} size:{lo}..{hi}'

    @property
    def label(self) -> str:
        return f"{self.term}|{self.language}"


def build_queries(cfg: dict) -> List[BaseQuery]:
    out: List[BaseQuery] = []
    for item in cfg["queries"]:
        out.append(BaseQuery(term=item["term"], language=item["language"]))
    return out


@dataclass
class Slice:
    query: str
    lo: int
    hi: int
    total_count: int
    truncated: bool  # True if total_count > cap even at min granularity


def _total_count(search_code, q: str, probe_cache: Dict[str, int]) -> int:
    if q in probe_cache:
        return probe_cache[q]
    resp = search_code(q=q, page=1, per_page=1)
    tc = int(resp.get("total_count", 0))
    if resp.get("incomplete_results"):
        logger.warning("incomplete_results while probing: %s (count=%d)", q, tc)
    probe_cache[q] = tc
    return tc


def partition_query(
    search_code,
    base: BaseQuery,
    size_min: int,
    size_max: int,
    cap: int,
    probe_cache: Dict[str, int],
) -> Iterator[Slice]:
    """Yield size-range slices for one base query, each <= cap where possible."""
    stack: List[Tuple[int, int]] = [(size_min, size_max)]
    while stack:
        lo, hi = stack.pop()
        q = base.q(lo, hi)
        tc = _total_count(search_code, q, probe_cache)
        if tc == 0:
            continue
        if tc <= cap or lo >= hi:
            yield Slice(query=q, lo=lo, hi=hi, total_count=tc, truncated=(tc > cap))
        else:
            mid = (lo + hi) // 2
            # push high half first so we process low half first (stable-ish order)
            stack.append((mid + 1, hi))
            stack.append((lo, mid))
