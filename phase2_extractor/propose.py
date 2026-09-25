"""LLM-assisted proposal pass.

Proposes JF1-JF5 codes with a rationale and a confidence flag per field, so
the human's job becomes verification rather than derivation.

RESEARCH-INTEGRITY DESIGN (this is the part that makes it defensible):

  1. Proposals are written to SEPARATE columns (llm_JF*), never into the
     human JF columns. The human types their own label. This preserves an
     independent human label per row, which is what makes machine-vs-human
     agreement measurable at all -- if the machine pre-fills the human's
     cell, agreement is 100% by construction and means nothing.

  2. The hidden validation set MUST be human-coded BEFORE proposals are
     generated or seen (`blinddraw` produces it). That set is the unbiased
     estimate of machine accuracy. Proposals seen first contaminate it.

  3. Every proposal carries a rationale and a LOW/MEDIUM/HIGH confidence.
     LOW-confidence rows get read carefully; the confidence flag is itself
     reportable ("machine self-flagged N% of sites as uncertain").

  4. The prompt instructs the model to prefer INDETERMINATE over guessing,
     mirroring the codebook's coding discipline. An over-confident labeler
     is worse than no labeler.

Requires ANTHROPIC_API_KEY in the environment. Use --dry-run to preview
prompts and estimate cost without making any API calls.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are assisting a peer-reviewed empirical security study that measures authority over-grant in Amazon S3 presigned-URL generation code. You propose codes for five judgment fields; a human researcher verifies every one of your proposals.

CRITICAL DISCIPLINE: Code ONLY from what the provided code window shows. If a value's origin is not visible, the correct answer is INDETERMINATE. A flagged indeterminate is a legitimate research finding; a guess is fabricated data that corrupts the study. Prefer INDETERMINATE whenever you are reasoning from plausibility rather than from visible evidence.

TECHNICAL GUARDRAIL: A presigned URL for GET/PUT cannot be repointed to another key by editing the URL -- the key is part of the SigV4 signature. Never reason as if GET key-swapping were possible.

JF1 -- POST $key tightness (POST-policy generators ONLY; leave blank otherwise)
  EXACT: an ['eq','$key',...] condition, OR a fixed/server-generated Key field with no user-controlled component (the SDK binds whatever string was computed at signing time).
  PREFIX: ['starts-with','$key','some/nonempty/prefix/'].
  EMPTY_PREFIX: ['starts-with','$key',''] -- empty string, holder may write any key in the bucket.
  UNSCOPED_KEY: no $key condition AND Key is derived from unvalidated raw user input.
  INDETERMINATE: conditions or Key come from outside the file, or are built dynamically.
  #1 TRAP: absence of a $key condition does NOT mean unscoped. If Key is fixed or server-generated, code EXACT.
  NOTE: a key like `${userId}/${id}.txt` is still EXACT for JF1 -- it is fixed at signing time and the URL holder cannot change it. User-controlled components matter for JF2, not JF1.

JF2 Part A -- key provenance: SERVER / USER_SANITIZED / USER_RAW / INDETERMINATE.
  Sanitization counts only if applied to the key or filename. A contentType check does not validate the key.
JF2 Part B -- authorization gate (code INDEPENDENTLY of Part A):
  AUTHZ_PRESENT: a check ties the request to an authenticated principal AND to the resource (ownership check on the key, or a server-derived prefix that structurally confines writes to the requester's own namespace).
  AUTHN_ONLY: is-logged-in only, no resource-ownership check.
  NONE: no auth machinery visible anywhere in the file.
  INDETERMINATE: a guard/decorator/middleware is referenced but its logic is not shown.
  TRAP: framework auth (NestJS guards, Rails before_action, Django decorators, Spring @PreAuthorize, Express middleware) gates outside the window. If referenced but not shown, code INDETERMINATE, never NONE.

JF3 -- signing credential lifetime:
  LONG_LIVED_IAM: explicit access key + secret pair (even from env vars -- what matters is that an access-key/secret pair is a static credential).
  STS_TEMPORARY: assumed-role / session credentials.
  ROLE_OR_CHAIN: client constructed with NO credentials argument (SDK default provider chain).
  INDETERMINATE: client constructed outside the file.
  TRAP: "no visible credentials" is ROLE_OR_CHAIN, not LONG_LIVED_IAM.

JF4 -- upload size exposure:
  BOUNDED_POST (POST with content-length-range) / UNBOUNDED_POST (POST without) /
  UNBOUNDED_PUT (PUT upload, no visible server-side size control) /
  APP_BOUNDED_PUT (PUT with enforced server-side size control) /
  N_A (GET/download) / INDETERMINATE.
  TRAPS: content-length-range is POST-only. A comment documenting a limit is not enforcement. Client-side file.size checks do not count.

JF5 Part A -- expiry bucket: SHORT (<=15min) / MODERATE (>15min-1hr) / LONG (>1hr-24hr) / VERY_LONG (>24hr-7d) / DEFAULT_UNSET (no expiry passed, SDK default applies) / INDETERMINATE (expiry from unresolvable variable).
  TRAP: units differ by SDK, and duration arithmetic must be evaluated (Ruby `1.minute.to_i` is 60 seconds, not 1).
JF5 Part B -- appropriateness: APPROPRIATE / OVER_LONG / INDETERMINATE.
  Reserve OVER_LONG for clear mismatches. For generic utility wrappers with no visible use case, code INDETERMINATE.

ELIGIBILITY: if the code is not a real AWS-or-S3-compatible presign generation site (e.g. a same-named non-AWS function, a CloudFront signer, another cloud's signer, SDK source code implementing the API, or a fake/mock), set eligible=false and give the reason; leave all JF codes null.

Respond with ONLY a JSON object, no preamble and no markdown fences:
{"eligible": true/false, "ineligible_reason": null or string,
 "JF1": null or code, "JF1_why": string, "JF1_confidence": "LOW"/"MEDIUM"/"HIGH",
 "JF2_provenance": code, "JF2_provenance_why": string, "JF2_provenance_confidence": "...",
 "JF2_authz": code, "JF2_authz_why": string, "JF2_authz_confidence": "...",
 "JF3": code, "JF3_why": string, "JF3_confidence": "...",
 "JF4": code, "JF4_why": string, "JF4_confidence": "...",
 "JF5_bucket": code, "JF5_bucket_why": string, "JF5_bucket_confidence": "...",
 "JF5_appropriateness": code, "JF5_appropriateness_why": string, "JF5_appropriateness_confidence": "..."}
Keep each _why under 25 words and cite the specific visible evidence."""

LLM_COLUMNS = [
    "llm_eligible", "llm_ineligible_reason",
    "llm_JF1", "llm_JF1_why", "llm_JF1_conf",
    "llm_JF2_provenance", "llm_JF2_provenance_why", "llm_JF2_provenance_conf",
    "llm_JF2_authz", "llm_JF2_authz_why", "llm_JF2_authz_conf",
    "llm_JF3", "llm_JF3_why", "llm_JF3_conf",
    "llm_JF4", "llm_JF4_why", "llm_JF4_conf",
    "llm_JF5_bucket", "llm_JF5_bucket_why", "llm_JF5_bucket_conf",
    "llm_JF5_appropriateness", "llm_JF5_appropriateness_why", "llm_JF5_appropriateness_conf",
    "llm_error",
]


def build_user_prompt(row: dict) -> str:
    parts = [
        f"Language: {row.get('language_query','')}   SDK term: {row.get('term','')}",
        f"Machine-detected mechanism: {row.get('mechanism','')}",
        f"File path: {row.get('path','')}",
        "",
        "--- CALL-SITE WINDOW ---",
        row.get("call_site_window", ""),
    ]
    ref = (row.get("referenced_snippet") or "").strip()
    if ref and ref != "(defined inline within window)":
        parts += ["", "--- REFERENCED PARAMS (resolved elsewhere in the same file) ---", ref]
    return "\n".join(parts)


def _flatten(obj: dict) -> dict:
    g = obj.get
    return {
        "llm_eligible": g("eligible", ""),
        "llm_ineligible_reason": g("ineligible_reason") or "",
        "llm_JF1": g("JF1") or "", "llm_JF1_why": g("JF1_why", ""), "llm_JF1_conf": g("JF1_confidence", ""),
        "llm_JF2_provenance": g("JF2_provenance") or "", "llm_JF2_provenance_why": g("JF2_provenance_why", ""),
        "llm_JF2_provenance_conf": g("JF2_provenance_confidence", ""),
        "llm_JF2_authz": g("JF2_authz") or "", "llm_JF2_authz_why": g("JF2_authz_why", ""),
        "llm_JF2_authz_conf": g("JF2_authz_confidence", ""),
        "llm_JF3": g("JF3") or "", "llm_JF3_why": g("JF3_why", ""), "llm_JF3_conf": g("JF3_confidence", ""),
        "llm_JF4": g("JF4") or "", "llm_JF4_why": g("JF4_why", ""), "llm_JF4_conf": g("JF4_confidence", ""),
        "llm_JF5_bucket": g("JF5_bucket") or "", "llm_JF5_bucket_why": g("JF5_bucket_why", ""),
        "llm_JF5_bucket_conf": g("JF5_bucket_confidence", ""),
        "llm_JF5_appropriateness": g("JF5_appropriateness") or "",
        "llm_JF5_appropriateness_why": g("JF5_appropriateness_why", ""),
        "llm_JF5_appropriateness_conf": g("JF5_appropriateness_confidence", ""),
        "llm_error": "",
    }


def propose_one(client, row: dict, max_retries: int = 3) -> dict:
    prompt = build_user_prompt(row)
    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=1200, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            text = text.replace("```json", "").replace("```", "").strip()
            return _flatten(json.loads(text))
        except json.JSONDecodeError as e:
            if attempt == max_retries - 1:
                return {**{c: "" for c in LLM_COLUMNS}, "llm_error": f"JSON parse failed: {e}"}
            time.sleep(1)
        except Exception as e:
            if attempt == max_retries - 1:
                return {**{c: "" for c in LLM_COLUMNS}, "llm_error": f"{type(e).__name__}: {e}"}
            time.sleep(2 ** attempt)
    return {**{c: "" for c in LLM_COLUMNS}, "llm_error": "exhausted retries"}


def run(coding_sheet_csv: Path, out_csv: Path, limit: int | None = None,
        dry_run: bool = False, resume: bool = True) -> dict:
    with open(coding_sheet_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        in_cols = list(rows[0].keys()) if rows else []
    if limit:
        rows = rows[:limit]

    done: dict[str, dict] = {}
    if resume and out_csv.exists():
        with open(out_csv, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("llm_error", "") == "":
                    done[r["sha"]] = r
        print(f"resuming: {len(done)} rows already proposed", file=sys.stderr)

    if dry_run:
        sample = build_user_prompt(rows[0]) if rows else ""
        est_in = sum(len(build_user_prompt(r)) for r in rows) / 3.7 + len(SYSTEM_PROMPT) / 3.7 * len(rows)
        est_out = 350 * len(rows)
        print("--- EXAMPLE PROMPT (first row) ---")
        print(sample[:2000])
        return {"rows": len(rows), "dry_run": True,
                "est_input_tokens": int(est_in), "est_output_tokens": int(est_out),
                "note": "no API calls made; run without --dry-run to execute"}

    try:
        from anthropic import Anthropic
    except ImportError:
        raise SystemExit("pip3 install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("set ANTHROPIC_API_KEY in your environment")
    client = Anthropic()

    out_cols = in_cols + [c for c in LLM_COLUMNS if c not in in_cols]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    n_new = n_err = 0
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_cols, extrasaction="ignore")
        w.writeheader()
        for i, row in enumerate(rows, 1):
            if row["sha"] in done:
                w.writerow(done[row["sha"]])
                continue
            result = propose_one(client, row)
            if result.get("llm_error"):
                n_err += 1
            n_new += 1
            w.writerow({**row, **result})
            f.flush()
            if i % 25 == 0:
                print(f"  {i}/{len(rows)}", file=sys.stderr)
    return {"rows": len(rows), "newly_proposed": n_new, "errors": n_err, "out": str(out_csv)}
