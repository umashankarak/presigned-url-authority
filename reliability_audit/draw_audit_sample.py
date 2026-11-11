#!/usr/bin/env python3
"""Draw the coding-reliability audit sample.

Draws 80 eligible audit sites and 10 separate practice sites with a fixed
seed, and writes:

  practice_coder2.xlsx  10 practice sites for the second coder's calibration
  practice_key.csv      final codes for the practice sites (discuss after practice)
  audit_coder2.xlsx     the 80-site blind sheet for the second coder
  audit_key.csv         final published codes for the audit sites.
                        DO NOT OPEN or share until the second coder is finished.

Practice sites never overlap the audit sites.

Strata (authorization cases oversampled):
  A  blind, authorization coded NONE                     20
  B  blind, authorization coded INDETERMINATE            20
  C  blind, authorization coded AUTHZ_PRESENT/AUTHN_ONLY 10
  D  blind, other upload sites (POST or PUT)             10
  E  targeted POST sample (key scope and size only)      20

Usage:
  python3 draw_audit_sample.py coding_sheet.xlsx coding_sheet_post_w40.xlsx [outdir]
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font

SEED = 20261107
PLAN = [("A", 20), ("B", 20), ("C", 10), ("D", 10), ("E", 20)]
PRACTICE = [("A", 2), ("B", 2), ("C", 2), ("D", 2), ("E", 2)]

JF_ALL = ["JF1_post_key_tightness", "JF2_key_provenance", "JF2_authz_gate",
          "JF3_credential_lifetime", "JF4_upload_size_exposure",
          "JF5_expiry_bucket", "JF5_expiry_appropriateness"]
JF_TARGETED = ["JF1_post_key_tightness", "JF4_upload_size_exposure"]
SHOWN = ["term", "language_query", "path", "mechanism", "match_line_no",
         "call_site_window", "referenced_snippet"]


def norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def load(path: Path) -> list[dict]:
    ws = load_workbook(path, read_only=True)["coding_sheet"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = list(rows[0])
    return [dict(zip(hdr, r)) for r in rows[1:]]


def eligible(rows):
    return [r for r in rows if norm(r.get("ELIGIBLE")) and norm(r["ELIGIBLE"]).upper() == "TRUE"]


def stratum_of(r) -> str | None:
    authz = norm(r.get("JF2_authz_gate"))
    if authz == "NONE":
        return "A"
    if authz == "INDETERMINATE":
        return "B"
    if authz in ("AUTHZ_PRESENT", "AUTHN_ONLY"):
        return "C"
    return None


def is_upload(r) -> bool:
    return norm(r.get("mechanism")) in ("POST-policy", "PUT-URL") or norm(
        r.get("JF4_upload_size_exposure")) in (
        "BOUNDED_POST", "UNBOUNDED_POST", "UNBOUNDED_PUT", "APP_BOUNDED_PUT")


def write_sheet(path: Path, picks, include_path: bool) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "audit"
    shown = [c for c in SHOWN if include_path or c != "path"]
    hdr = ["audit_id", "sample"] + shown + JF_ALL + ["notes"]
    ws.append(hdr)
    for p in picks:
        r = p["row"]
        codes = ["" if f in p["fields"] else "NOT_CODED" for f in JF_ALL]
        ws.append([p["audit_id"], p["sample"]] + [r.get(c) for c in shown] + codes + [""])
    for c in ws[1]:
        c.font = Font(bold=True)
    wcol = hdr.index("call_site_window") + 1
    ws.column_dimensions[ws.cell(1, wcol).column_letter].width = 100
    for row in ws.iter_rows(min_row=2):
        row[wcol - 1].alignment = Alignment(wrap_text=True, vertical="top")
    ref = wb.create_sheet("codes")
    ref.append(["field", "allowed codes"])
    for f, codes in [
        ("JF1_post_key_tightness", "EXACT, PREFIX, EMPTY_PREFIX, UNSCOPED_KEY, INDETERMINATE (POST only; else N_A)"),
        ("JF2_key_provenance", "SERVER, USER_SANITIZED, USER_RAW, INDETERMINATE"),
        ("JF2_authz_gate", "AUTHZ_PRESENT, AUTHN_ONLY, NONE, INDETERMINATE"),
        ("JF3_credential_lifetime", "LONG_LIVED_IAM, STS_TEMPORARY, ROLE_OR_CHAIN, INDETERMINATE"),
        ("JF4_upload_size_exposure", "BOUNDED_POST, UNBOUNDED_POST, APP_BOUNDED_PUT, UNBOUNDED_PUT, N_A, INDETERMINATE"),
        ("JF5_expiry_bucket", "SHORT, MODERATE, LONG, VERY_LONG, DEFAULT_UNSET, INDETERMINATE"),
        ("JF5_expiry_appropriateness", "APPROPRIATE, OVER_LONG, INDETERMINATE"),
    ]:
        ref.append([f, codes])
    wb.save(path)


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    blind = eligible(load(Path(sys.argv[1])))
    targ = eligible(load(Path(sys.argv[2])))
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("audit")
    out.mkdir(parents=True, exist_ok=True)
    for f in ("audit_coder2.xlsx", "audit_key.csv", "practice_coder2.xlsx", "practice_key.csv"):
        if (out / f).exists():
            sys.exit(f"{out / f} exists; the audit sample is drawn once. Remove it only if you mean to redraw.")

    rng = random.Random(SEED)
    key_sha = lambda r: norm(r.get("sha")) or norm(r.get("blob_sha"))
    pools = {s: sorted([r for r in blind if stratum_of(r) == s], key=key_sha) for s in "ABC"}
    used: set = set()

    def draw(plan):
        picks = []
        for s, n in plan:
            if s in "ABC":
                pool = [r for r in pools[s] if key_sha(r) not in used]
            elif s == "D":
                pool = sorted([r for r in blind if is_upload(r) and stratum_of(r) is not None
                               and key_sha(r) not in used], key=key_sha)
            else:
                pool = [r for r in sorted(targ, key=key_sha) if key_sha(r) not in used]
            if len(pool) < n:
                sys.exit(f"stratum {s}: pool {len(pool)} smaller than {n}")
            for r in rng.sample(pool, n):
                used.add(key_sha(r))
                picks.append({"row": r, "stratum": s,
                              "sample": "targeted" if s == "E" else "blind",
                              "fields": JF_TARGETED if s == "E" else JF_ALL})
        rng.shuffle(picks)
        return picks

    audit = draw(PLAN)          # drawn first, so the audit set matches the original design
    practice = draw(PRACTICE)   # then 10 practice sites from what remains
    for i, p in enumerate(audit, 1):
        p["audit_id"] = f"A{i:03d}"
    for i, p in enumerate(practice, 1):
        p["audit_id"] = f"P{i:02d}"

    def write_key(path, picks):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["audit_id", "sample", "audit_stratum", "sha", "stratum"] + JF_ALL)
            for p in picks:
                r = p["row"]
                w.writerow([p["audit_id"], p["sample"], p["stratum"], key_sha(r), norm(r.get("stratum"))]
                           + [(norm(r.get(f)) or "") if f in p["fields"] else "NOT_CODED" for f in JF_ALL])

    write_sheet(out / "audit_coder2.xlsx", audit, include_path=True)
    write_sheet(out / "practice_coder2.xlsx", practice, include_path=True)
    write_key(out / "audit_key.csv", audit)
    write_key(out / "practice_key.csv", practice)
    picks = audit
    manifest = {"seed": SEED, "plan": dict(PLAN), "total": len(picks),
                "practice": dict(PRACTICE), "practice_total": len(practice),
                "pool_sizes": {s: len(pools[s]) for s in "ABC"} | {"E": len(targ)},
                "blind_eligible": len(blind), "targeted_eligible": len(targ)}
    (out / "audit_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    print(f"\nwrote {out}/practice_coder2.xlsx, practice_key.csv, audit_coder2.xlsx, audit_key.csv")
    print("send the coder ONLY practice_coder2.xlsx now; audit_coder2.xlsx after the practice review;")
    print("never send either key file")


if __name__ == "__main__":
    main()
