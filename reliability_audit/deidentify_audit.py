#!/usr/bin/env python3
"""Write the public, de-identified codes for the coding-reliability audit.

Reads the identified audit files (kept private because they hold repository
paths and code excerpts) and writes two CSV files that hold only audit ids,
public row ids, and codes:

  audit_final_codes.csv          the final codes at the time of the audit
  audit_second_coder_codes.csv   the second coder's independent codes

Usage:
  python3 deidentify_audit.py audit/audit_key.csv audit/audit_coder2_completed.xlsx \
      ../phase2/data/blind_sample_coded.xlsx ../phase2/data/targeted_post_coded.xlsx

Run kappa_audit.py on the two outputs to reproduce the agreement table.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from openpyxl import load_workbook

JF_ALL = ["JF1_post_key_tightness", "JF2_key_provenance", "JF2_authz_gate",
          "JF3_credential_lifetime", "JF4_upload_size_exposure",
          "JF5_expiry_bucket", "JF5_expiry_appropriateness"]


def norm(v):
    if v is None:
        return ""
    return str(v).strip()


def sheet_rows(path: Path) -> list[dict]:
    ws = load_workbook(path, read_only=True).worksheets[0]
    it = list(ws.iter_rows(values_only=True))
    hdr = [norm(h) for h in it[0]]
    return [dict(zip(hdr, r)) for r in it[1:]]


def main() -> None:
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    key_path, coder_path, blind_path, targ_path = map(Path, sys.argv[1:])
    row_id = {}
    for p in (blind_path, targ_path):
        for r in sheet_rows(p):
            row_id[norm(r["blob_sha"])] = norm(r["row_id"])

    with open(key_path, newline="", encoding="utf-8-sig") as fh:
        key = list(csv.DictReader(fh))
    coder = {norm(r.get("audit_id")): r for r in sheet_rows(coder_path) if norm(r.get("audit_id"))}

    missing = [k["audit_id"] for k in key if norm(k["sha"]) not in row_id]
    if missing:
        sys.exit(f"no public row for audit sites {missing}; nothing written")
    if set(coder) != {k["audit_id"] for k in key}:
        sys.exit("the coder sheet and the key list different audit ids; nothing written")

    out = Path(".")
    with open(out / "audit_final_codes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["audit_id", "sample", "audit_stratum", "row_id"] + JF_ALL)
        for k in sorted(key, key=lambda k: k["audit_id"]):
            w.writerow([k["audit_id"], k["sample"], k["audit_stratum"], row_id[norm(k["sha"])]]
                       + [norm(k[f]) for f in JF_ALL])
    with open(out / "audit_second_coder_codes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["audit_id"] + JF_ALL)
        for aid in sorted(coder):
            w.writerow([aid] + [norm(coder[aid].get(f)).upper() for f in JF_ALL])
    print(f"wrote audit_final_codes.csv and audit_second_coder_codes.csv ({len(key)} sites)")


if __name__ == "__main__":
    main()
