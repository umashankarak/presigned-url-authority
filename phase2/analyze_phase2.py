#!/usr/bin/env python3
"""
Phase 2 analysis for the S3 presigned-URL over-grant study (paper 9).

Reads the two coded workbooks:
  - coding_sheet.xlsx           (the BLIND 500-file sample, minus junk -> 383 rows,
                                 all seven judgment fields coded)
  - coding_sheet_post_w40.xlsx  (the TARGETED POST-policy stratum, 238 rows,
                                 JF1 + JF4 coded only)

and produces every rate, confidence interval, and cross-tab the results
section needs.

Analysis rules (stated in the paper's methods, enforced here):
  * DENOMINATORS EXCLUDE INDETERMINATE. Every judgment-field rate is reported
    over "determinable" sites (the field is not INDETERMINATE), and the
    indeterminate rate itself is reported separately as a result.
  * JF1 / JF4 pool the POST rows from BOTH sheets (blind POST + targeted
    stratum) for maximum power on the key/size findings.
  * Everything else (mechanism prevalence, JF2 / JF3 / JF5, eligibility,
    s3_compatible) comes from the BLIND sheet ONLY -- the targeted stratum is
    deliberately enriched for POST and would bias any all-mechanism rate.
  * 95% CIs use the Wilson score interval (good for proportions near 0/1 and
    small n); for a 0/N observation this gives the standard upper bound.

No third-party stats libraries required -- pure stdlib, so it runs anywhere
and is trivially auditable for reviewers.
"""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

# ---- point these at your two files -----------------------------------------
import sys
# Usage: python3 analyze_phase2.py [blind_coded.xlsx] [targeted_coded.xlsx]
BLIND_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("coding_sheet.xlsx")
POST_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("coding_sheet_post_w40.xlsx")

JF_FIELDS = [
    "JF1_post_key_tightness",
    "JF2_key_provenance",
    "JF2_authz_gate",
    "JF3_credential_lifetime",
    "JF4_upload_size_exposure",
    "JF5_expiry_bucket",
    "JF5_expiry_appropriateness",
]


# ---- helpers ---------------------------------------------------------------
def load(path: Path) -> list[dict]:
    ws = load_workbook(path, read_only=True)["coding_sheet"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = list(rows[0])
    return [dict(zip(hdr, r)) for r in rows[1:]]


def norm(v):
    """Normalize a cell to a clean string or None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def is_true(v) -> bool:
    return norm(v) is not None and norm(v).upper() == "TRUE"


def is_false(v) -> bool:
    return norm(v) is not None and norm(v).upper() == "FALSE"


def coded_rows(data: list[dict]) -> list[dict]:
    """Rows the human actually touched (ELIGIBLE is TRUE or FALSE)."""
    return [r for r in data if is_true(r.get("ELIGIBLE")) or is_false(r.get("ELIGIBLE"))]


def eligible_rows(data: list[dict]) -> list[dict]:
    return [r for r in coded_rows(data) if is_true(r.get("ELIGIBLE"))]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval. Returns (point, lo, hi) as proportions."""
    if n == 0:
        return (float("nan"), float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def pct(x: float) -> str:
    return "n/a" if x != x else f"{100 * x:.1f}%"


def field_distribution(rows: list[dict], field: str) -> Counter:
    return Counter(norm(r.get(field)) or "(blank)" for r in rows)


def determinable(rows: list[dict], field: str) -> list[str]:
    """Values of `field` that are present, not INDETERMINATE, and not N_A.
    N_A marks a site the dimension does not apply to (e.g. a download site
    under size bound), so it belongs in no denominator."""
    out = []
    for r in rows:
        v = norm(r.get(field))
        if v and v not in ("INDETERMINATE", "N_A"):
            out.append(v)
    return out


def rate_block(rows: list[dict], field: str, title: str,
               overgrant_codes: set[str] | None = None) -> None:
    dist = field_distribution(rows, field)
    coded = [r for r in rows if norm(r.get(field)) and norm(r.get(field)) != "N_A"]
    n_coded = len(coded)
    n_indet = dist.get("INDETERMINATE", 0)
    det = determinable(rows, field)
    n_det = len(det)
    print(f"\n### {title}")
    print(f"    coded (non-blank): {n_coded}")
    if n_coded:
        print(f"    INDETERMINATE:     {n_indet}  ({pct(n_indet / n_coded)} of coded)")
    print(f"    determinable:      {n_det}")
    if n_det:
        dd = Counter(det)
        for code, c in dd.most_common():
            p, lo, hi = wilson(c, n_det)
            print(f"      {code:16s} {c:4d}  {pct(p)}   [95% CI {pct(lo)}-{pct(hi)}]")
    if overgrant_codes and n_det:
        k = sum(1 for v in det if v in overgrant_codes)
        p, lo, hi = wilson(k, n_det)
        label = "+".join(sorted(overgrant_codes))
        print(f"    >>> OVER-GRANT ({label}): {k}/{n_det} = {pct(p)}  [95% CI {pct(lo)}-{pct(hi)}]")


# ---- load ------------------------------------------------------------------
blind = load(BLIND_PATH)
post = load(POST_PATH)

blind_coded = coded_rows(blind)
blind_elig = eligible_rows(blind)
post_coded = coded_rows(post)
post_elig = eligible_rows(post)

print("=" * 78)
print("PHASE 2 ANALYSIS  —  S3 presigned-URL over-grant study")
print("=" * 78)

# ---- 1. Corpus / eligibility ----------------------------------------------
print("\n" + "-" * 78)
print("1. SAMPLE & ELIGIBILITY")
print("-" * 78)
print(f"\nBLIND sample: {len(blind_coded)} coded  |  eligible {len(blind_elig)}  "
      f"|  ineligible {len(blind_coded) - len(blind_elig)} "
      f"({pct((len(blind_coded)-len(blind_elig))/len(blind_coded))})")
inelig = Counter(norm(r.get("INELIGIBLE_REASON")) for r in blind_coded if is_false(r.get("ELIGIBLE")))
print("  ineligible reasons:", dict(inelig))
print(f"\nTARGETED POST stratum: {len(post_coded)} coded  |  eligible {len(post_elig)}  "
      f"|  ineligible {len(post_coded)-len(post_elig)} "
      f"({pct((len(post_coded)-len(post_elig))/len(post_coded))})")

print("\nTerm-search precision by mechanism (BLIND sample):")
for mech in ["POST-policy", "GET-URL", "PUT-URL", "INDETERMINATE"]:
    rows_m = [r for r in blind_coded if norm(r.get("mechanism")) == mech]
    if not rows_m:
        continue
    elig_m = sum(1 for r in rows_m if is_true(r.get("ELIGIBLE")))
    p, lo, hi = wilson(elig_m, len(rows_m))
    print(f"    {mech:16s} {elig_m:3d}/{len(rows_m):3d} eligible = {pct(p)}  [95% CI {pct(lo)}-{pct(hi)}]")

# s3-compatible
s3c = sum(1 for r in blind_elig if is_true(r.get("s3_compatible")))
p, lo, hi = wilson(s3c, len(blind_elig))
print(f"\nS3-compatible (non-AWS S3 API) among eligible blind: {s3c}/{len(blind_elig)} = "
      f"{pct(p)}  [95% CI {pct(lo)}-{pct(hi)}]")

# ---- 2. Mechanism prevalence (blind only — the RQ2 denominator) -----------
print("\n" + "-" * 78)
print("2. MECHANISM PREVALENCE  (BLIND sample only — unbiased)")
print("-" * 78)
mech_dist = Counter(norm(r.get("mechanism")) for r in blind_elig)
n = len(blind_elig)
for mech, c in mech_dist.most_common():
    p, lo, hi = wilson(c, n)
    print(f"    {str(mech):16s} {c:4d}  {pct(p)}  [95% CI {pct(lo)}-{pct(hi)}]")

# ---- 3. JF1 — key tightness (POOLED across both sheets) -------------------
print("\n" + "-" * 78)
print("3. JF1 — POST $key TIGHTNESS  (POOLED: blind POST rows + targeted stratum)")
print("-" * 78)
blind_post = [r for r in blind_elig if norm(r.get("mechanism")) == "POST-policy"]
pooled_jf1 = blind_post + post_elig  # targeted stratum is all POST
rate_block(pooled_jf1, "JF1_post_key_tightness",
           "JF1 pooled (key tightness)",
           overgrant_codes={"EMPTY_PREFIX", "UNSCOPED_KEY"})
print("\n  (For contrast, blind-only and targeted-only JF1:)")
rate_block(blind_post, "JF1_post_key_tightness", "JF1 — blind POST rows only")
rate_block(post_elig, "JF1_post_key_tightness", "JF1 — targeted stratum only")

# ---- 4. JF4 — upload size exposure (pooled uploads) ----------------------
print("\n" + "-" * 78)
print("4. JF4 — UPLOAD SIZE EXPOSURE")
print("-" * 78)
# pooled uploads: all POST (both sheets) + PUT (blind only). N_A (GET) excluded
# from the 'upload' denominator by construction (N_A is not over-grant).
blind_uploads = [r for r in blind_elig
                 if norm(r.get("mechanism")) in ("POST-policy", "PUT-URL")]
pooled_jf4 = blind_uploads + post_elig
rate_block(pooled_jf4, "JF4_upload_size_exposure",
           "JF4 pooled (upload size)",
           overgrant_codes={"UNBOUNDED_POST", "UNBOUNDED_PUT"})

print("\n  JF4 by mechanism (this is the key split for the paper):")
for mech, src in [("POST-policy (pooled)", pooled_jf4 if False else None)]:
    pass
# POST size-omission (pooled POST)
post_all = blind_post + post_elig
det_post = determinable(post_all, "JF4_upload_size_exposure")
unb_post = sum(1 for v in det_post if v == "UNBOUNDED_POST")
if det_post:
    p, lo, hi = wilson(unb_post, len(det_post))
    print(f"    POST unbounded:  {unb_post}/{len(det_post)} = {pct(p)}  [95% CI {pct(lo)}-{pct(hi)}]")
# PUT size-omission (blind only)
blind_put = [r for r in blind_elig if norm(r.get("mechanism")) == "PUT-URL"]
det_put = determinable(blind_put, "JF4_upload_size_exposure")
unb_put = sum(1 for v in det_put if v == "UNBOUNDED_PUT")
if det_put:
    p, lo, hi = wilson(unb_put, len(det_put))
    print(f"    PUT unbounded:   {unb_put}/{len(det_put)} = {pct(p)}  [95% CI {pct(lo)}-{pct(hi)}]")

# ---- 5. JF2 — provenance + authz (blind only) ----------------------------
print("\n" + "-" * 78)
print("5. JF2 — KEY PROVENANCE & AUTHORIZATION  (BLIND sample only)")
print("-" * 78)
rate_block(blind_elig, "JF2_key_provenance", "JF2 Part A — provenance",
           overgrant_codes={"USER_RAW"})
rate_block(blind_elig, "JF2_authz_gate", "JF2 Part B — authz gate",
           overgrant_codes={"NONE", "AUTHN_ONLY"})
# IDOR red flag = USER_RAW + (NONE or AUTHN_ONLY), among rows determinable on BOTH parts
idor_den = [r for r in blind_elig
            if norm(r.get("JF2_key_provenance")) in ("SERVER", "USER_SANITIZED", "USER_RAW")
            and norm(r.get("JF2_authz_gate")) in ("AUTHZ_PRESENT", "AUTHN_ONLY", "NONE")]
idor_k = sum(1 for r in idor_den
             if norm(r.get("JF2_key_provenance")) == "USER_RAW"
             and norm(r.get("JF2_authz_gate")) in ("NONE", "AUTHN_ONLY"))
if idor_den:
    p, lo, hi = wilson(idor_k, len(idor_den))
    print(f"\n  >>> IDOR red flag (USER_RAW + NONE/AUTHN_ONLY): "
          f"{idor_k}/{len(idor_den)} = {pct(p)}  [95% CI {pct(lo)}-{pct(hi)}]  "
          f"(rows determinable on both JF2 parts)")

# ---- 6. JF3 — credential lifetime (blind only) ---------------------------
print("\n" + "-" * 78)
print("6. JF3 — SIGNING CREDENTIAL LIFETIME  (BLIND sample only)")
print("-" * 78)
rate_block(blind_elig, "JF3_credential_lifetime", "JF3 — credential lifetime",
           overgrant_codes={"LONG_LIVED_IAM"})

# ---- 7. JF5 — expiry (blind only) ----------------------------------------
print("\n" + "-" * 78)
print("7. JF5 — EXPIRATION  (BLIND sample only)")
print("-" * 78)
rate_block(blind_elig, "JF5_expiry_bucket", "JF5 Part A — expiry bucket")
rate_block(blind_elig, "JF5_expiry_appropriateness", "JF5 Part B — appropriateness",
           overgrant_codes={"OVER_LONG"})

# ---- 8. Indeterminate-rate summary (a reported result) -------------------
print("\n" + "-" * 78)
print("8. INDETERMINATE RATES PER FIELD  (a reported result: static undecidability)")
print("-" * 78)
print(f"  {'field':30s} {'coded':>6s} {'indet':>6s} {'rate':>7s}")
for fld, rows_src in [
    ("JF1 (pooled POST)", pooled_jf1),
    ("JF2_provenance (blind)", blind_elig),
    ("JF2_authz (blind)", blind_elig),
    ("JF3 (blind)", blind_elig),
    ("JF4 (pooled uploads)", pooled_jf4),
    ("JF5_bucket (blind)", blind_elig),
    ("JF5_approp (blind)", blind_elig),
]:
    fieldname = {
        "JF1 (pooled POST)": "JF1_post_key_tightness",
        "JF2_provenance (blind)": "JF2_key_provenance",
        "JF2_authz (blind)": "JF2_authz_gate",
        "JF3 (blind)": "JF3_credential_lifetime",
        "JF4 (pooled uploads)": "JF4_upload_size_exposure",
        "JF5_bucket (blind)": "JF5_expiry_bucket",
        "JF5_approp (blind)": "JF5_expiry_appropriateness",
    }[fld]
    coded = [r for r in rows_src if norm(r.get(fieldname)) and norm(r.get(fieldname)) != "N_A"]
    indet = sum(1 for r in coded if norm(r.get(fieldname)) == "INDETERMINATE")
    rate = indet / len(coded) if coded else float("nan")
    print(f"  {fld:30s} {len(coded):6d} {indet:6d} {pct(rate):>7s}")


# ---- 9. Supplementary measures reported in the paper ----------------------
print("\n" + "-" * 78)
print("9. SUPPLEMENTARY MEASURES  (stratum check, PUT sensitivity, short expiries)")
print("-" * 78)

def frac(k, n_):
    p, lo, hi = wilson(k, n_)
    return f"{k}/{n_} = {pct(p)}  [95% CI {pct(lo)}-{pct(hi)}]"

# 9a. headline measures by stratum (primary vs low-signal; pipeline label 'sample')
print("\n### Headline measures by stratum")
for stratum, label in [("primary", "primary"), ("sample", "low-signal")]:
    ks = determinable([r for r in pooled_jf1 if norm(r.get("stratum")) == stratum],
                      "JF1_post_key_tightness")
    wa = sum(1 for v in ks if v in ("EMPTY_PREFIX", "UNSCOPED_KEY"))
    ps = determinable([r for r in post_all if norm(r.get("stratum")) == stratum],
                      "JF4_upload_size_exposure")
    pu = determinable([r for r in blind_put if norm(r.get("stratum")) == stratum],
                      "JF4_upload_size_exposure")
    az = determinable([r for r in blind_elig if norm(r.get("stratum")) == stratum],
                      "JF2_authz_gate")
    print(f"  [{label}]")
    print(f"    write-anywhere POST key scope:   {frac(wa, len(ks))}")
    print(f"    POST without size range:         {frac(sum(1 for v in ps if v == 'UNBOUNDED_POST'), len(ps))}")
    print(f"    PUT without size bound:          {frac(sum(1 for v in pu if v == 'UNBOUNDED_PUT'), len(pu))}")
    print(f"    no resource-level authorization: {frac(sum(1 for v in az if v in ('NONE', 'AUTHN_ONLY')), len(az))}")

# 9b. PUT sensitivity: include coder-identified PUT uploads whose mechanism the
# extractor could not assign
jf4_blind = [norm(r.get("JF4_upload_size_exposure")) for r in blind_elig]
unb_put_all = sum(1 for v in jf4_blind if v == "UNBOUNDED_PUT")
put_all = sum(1 for v in jf4_blind if v in ("UNBOUNDED_PUT", "APP_BOUNDED_PUT"))
print("\n### PUT sensitivity (all coder-identified PUT uploads, blind)")
print(f"    PUT without size bound:          {frac(unb_put_all, put_all)}")

# 9c. expiries of one hour or less
exp = determinable(blind_elig, "JF5_expiry_bucket")
short = sum(1 for v in exp if v in ("SHORT", "MODERATE"))
print("\n### Expiry of one hour or less (blind)")
print(f"    expiry <= 1 hour:                {frac(short, len(exp))}")

print("\n" + "=" * 78)
print("done. Denominators exclude INDETERMINATE; JF1/JF4 pool both sheets;")
print("all other fields are BLIND-sample only. CIs are Wilson score, 95%.")
print("=" * 78)
