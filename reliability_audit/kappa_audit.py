#!/usr/bin/env python3
"""Agreement statistics for the coding-reliability audit.

Compares, per judgment field:
  second coder  vs  final published codes (the author's)   inter-rater
  optional third sheet (for example an author re-code) vs both

Every code, including INDETERMINATE and N_A, counts as a category, so
agreement on "cannot be decided" is measured too. Fields marked NOT_CODED,
or left blank by either rater, are skipped for that pair.

Usage:
  python3 kappa_audit.py audit/audit_key.csv audit/audit_coder2.xlsx [third_sheet.xlsx|.csv]

Writes audit_agreement.txt and audit_disagreements.csv next to the key file.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

JF_ALL = ["JF1_post_key_tightness", "JF2_key_provenance", "JF2_authz_gate",
          "JF3_credential_lifetime", "JF4_upload_size_exposure",
          "JF5_expiry_bucket", "JF5_expiry_appropriateness"]


def norm(v):
    if v is None:
        return None
    s = str(v).strip().upper()
    return s or None


def read_any(path: Path) -> dict[str, dict]:
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    else:
        ws = load_workbook(path, read_only=True).worksheets[0]
        it = list(ws.iter_rows(values_only=True))
        hdr = [str(h).strip() if h else "" for h in it[0]]
        rows = [dict(zip(hdr, r)) for r in it[1:]]
    return {str(r["audit_id"]).strip(): r for r in rows if r.get("audit_id")}


def kappa(pairs: list[tuple[str, str]]) -> tuple[int, float, float]:
    n = len(pairs)
    if n == 0:
        return 0, float("nan"), float("nan")
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / (n * n)
    k = float("nan") if pe == 1 else (po - pe) / (1 - pe)
    return n, po, k


def compare(a: dict, b: dict, field: str):
    pairs, diffs = [], []
    for aid in sorted(set(a) & set(b)):
        x, y = norm(a[aid].get(field)), norm(b[aid].get(field))
        if not x or not y or "NOT_CODED" in (x, y):
            continue
        pairs.append((x, y))
        if x != y:
            diffs.append((aid, x, y))
    return pairs, diffs


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    key_path = Path(sys.argv[1])
    final = read_any(key_path)
    coder2 = read_any(Path(sys.argv[2]))
    third = read_any(Path(sys.argv[3])) if len(sys.argv) > 3 else None

    missing = [aid for aid in final if aid not in coder2]
    if missing:
        print(f"warning: {len(missing)} audit sites missing from the coder sheet: {missing[:5]}...")

    comparisons = [("second coder vs final (inter-rater)", coder2, final)]
    if third:
        comparisons += [("third sheet vs final", third, final), ("second coder vs third sheet", coder2, third)]

    lines, disagreements = [], []
    for title, a, b in comparisons:
        lines.append(f"\n### {title}")
        lines.append(f"  {'field':30s} {'n':>4s} {'agree':>7s} {'kappa':>7s}")
        for f in JF_ALL:
            pairs, diffs = compare(a, b, f)
            n, po, k = kappa(pairs)
            if n == 0:
                continue
            ks = "  n/a" if k != k else f"{k:7.2f}"
            lines.append(f"  {f:30s} {n:4d} {100 * po:6.1f}% {ks}")
            disagreements += [(title, f, aid, x, y) for aid, x, y in diffs]

    report = "\n".join(lines)
    print(report)
    out_dir = key_path.parent
    (out_dir / "audit_agreement.txt").write_text(report.lstrip() + "\n", encoding="utf-8")
    with open(out_dir / "audit_disagreements.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["comparison", "field", "audit_id", "first_rater_code", "second_rater_code", "resolution"])
        w.writerows(list(d) + [""] for d in disagreements)
    print(f"\nwrote {out_dir}/audit_agreement.txt and audit_disagreements.csv "
          f"({len(disagreements)} disagreements to resolve)")


if __name__ == "__main__":
    main()
