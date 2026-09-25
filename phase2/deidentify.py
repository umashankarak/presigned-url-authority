#!/usr/bin/env python3
"""Produce the public, de-identified versions of the two coded samples.

Keeps the fields the analysis needs plus the Git blob SHA of each file, which
pins the exact file version without naming its repository. Drops everything
that names a repository or reproduces its code: repository name, file path,
URL, star count, extracted source code, referenced snippets, expiry source
text, and free-text coder notes.

Usage:
    python3 deidentify.py <blind_coded.xlsx> <targeted_coded.xlsx> <out_dir>
"""
import sys
from pathlib import Path
from openpyxl import Workbook, load_workbook

KEEP = [
    "blob_sha", "term", "language_query", "stratum", "match_type", "mechanism",
    "content_length_range_present", "conditions_visible",
    "ELIGIBLE", "INELIGIBLE_REASON", "s3_compatible", "MULTI_SITE",
    "JF1_post_key_tightness", "JF2_key_provenance", "JF2_authz_gate",
    "JF3_credential_lifetime", "JF4_upload_size_exposure",
    "JF5_expiry_bucket", "JF5_expiry_appropriateness",
]
NEVER = {"repo", "path", "html_url", "stars", "call_site_window",
         "referenced_snippet", "expiry_source_text", "coder_notes",
         "referenced_var", "referenced_var_resolved"}
assert not NEVER & set(KEEP)


def deidentify(src: Path, dst: Path, prefix: str) -> int:
    ws = load_workbook(src, read_only=True)["coding_sheet"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = list(rows[0])
    cols = [c for c in KEEP if c in hdr or c == "blob_sha"]
    out = Workbook()
    o = out.active
    o.title = "coding_sheet"
    o.append(["row_id"] + cols)
    n = 0
    for i, r in enumerate(rows[1:], 1):
        d = dict(zip(hdr, r))
        d["blob_sha"] = d.get("sha")
        if not any(d.get(c) is not None for c in cols if c != "blob_sha"):
            continue
        n += 1
        o.append([f"{prefix}{i:04d}"] + [d.get(c) for c in cols])
    out.save(dst)
    return n


if __name__ == "__main__":
    blind, targeted, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out_dir.mkdir(parents=True, exist_ok=True)
    nb = deidentify(blind, out_dir / "blind_sample_coded.xlsx", "B")
    nt = deidentify(targeted, out_dir / "targeted_post_coded.xlsx", "T")
    print(f"wrote {nb} blind rows and {nt} targeted rows to {out_dir}")
