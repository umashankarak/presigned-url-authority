"""Correction 2: apply the resolved disagreements from the reliability audit.

The second coder and the final codes disagreed on 14 fields at 10 sites
(reliability_audit/audit_resolutions.csv). Seven changes follow from the
resolutions: six codes changed and one site found to be library source and
made ineligible. The other seven disagreements kept the final code.

Each change is matched by file SHA (identified sheets: `sha`; public sheets:
`blob_sha`) and refuses to apply unless the cell still holds the expected old
value. Already applied to the data files in phase2/data/; kept as a record of
the change. A .bak copy is written before saving.

Usage:
    python3 apply_audit_resolutions.py blind    <blind sheet.xlsx>
    python3 apply_audit_resolutions.py targeted <targeted sheet.xlsx>
"""
import shutil
import sys
import time

from openpyxl import load_workbook

# (sample, sha, field, old, new, reason)
CHANGES = [
    ("blind", "47320b0bf6291fbe330c7662c6552d7be61951c9", "JF2_authz_gate", "INDETERMINATE", "NONE",
     "A016: FastAPI handler fully visible, no auth dependency or check (codebook: NONE)"),
    ("blind", "f5c687ef741e4326854d4626ba460811ebe6dc63", "JF5_expiry_bucket", "SHORT", "MODERATE",
     "A022: 30 TimeUnit.MINUTES is over 15 min, up to 1 h"),
    ("blind", "b07163b0b84cda91ce46d5b94a6647e3fae32aa0", "JF2_authz_gate", "AUTHZ_PRESENT", "INDETERMINATE",
     "A059: Rails before_action; prefix is the challenge id, not the caller's identity; controller filters outside window"),
    ("blind", "b07163b0b84cda91ce46d5b94a6647e3fae32aa0", "JF4_upload_size_exposure", "INDETERMINATE", "UNBOUNDED_POST",
     "A059: presigned_post options all inline; no content_length_range"),
    ("blind", "588a73b9a5957cae60685da79bf7fc31452cd6e7", "JF1_post_key_tightness", "INDETERMINATE", "N_A",
     "A069: PUT URL, not a POST policy"),
    ("blind", "588a73b9a5957cae60685da79bf7fc31452cd6e7", "JF4_upload_size_exposure", "UNBOUNDED_PUT", "INDETERMINATE",
     "A069: window ends at 'new PutObjectCommand({'; signing parameters not visible"),
    ("targeted", "41d165680d0264fb5327111f43171d26903e2cce", "ELIGIBLE", True, False,
     "A074: Shrine::Storage::S3 is library source that defines presigning (codebook: SDK_SOURCE)"),
    ("targeted", "41d165680d0264fb5327111f43171d26903e2cce", "INELIGIBLE_REASON", None, "SDK_SOURCE", "A074"),
    ("targeted", "41d165680d0264fb5327111f43171d26903e2cce", "JF1_post_key_tightness", "INDETERMINATE", None, "A074"),
    ("targeted", "41d165680d0264fb5327111f43171d26903e2cce", "JF4_upload_size_exposure", "INDETERMINATE", None, "A074"),
]


def same(a, b):
    def n(v):
        if v is None or str(v).strip() == "":
            return None
        s = str(v).strip().upper()
        return {"TRUE": True, "FALSE": False}.get(s, s)
    return n(a) == n(b)


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("blind", "targeted"):
        sys.exit(__doc__)
    sample, path = sys.argv[1], sys.argv[2]
    todo = [c for c in CHANGES if c[0] == sample]
    wb = load_workbook(path)
    ws = wb.worksheets[0]
    hdr = [c.value for c in ws[1]]
    sha_col = "sha" if "sha" in hdr else "blob_sha"
    done = 0
    for row in ws.iter_rows(min_row=2):
        sha = row[hdr.index(sha_col)].value
        for _, s, field, old, new, why in todo:
            if s != sha:
                continue
            cell = row[hdr.index(field)]
            if not same(cell.value, old):
                sys.exit(f"{path}: {s[:10]} {field} is {cell.value!r}, expected {old!r}; nothing saved")
            if field == "ELIGIBLE" and isinstance(cell.value, str):
                new = "FALSE"
            cell.value = new
            done += 1
            print(f"  {why.split(':')[0]} {field}: {old} -> {new}")
    if done != len(todo):
        sys.exit(f"{path}: applied {done} of {len(todo)} changes; nothing saved")
    bak = f"{path}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(path, bak)
    wb.save(path)
    print(f"{path}: {done} changes saved (backup at {bak})")


if __name__ == "__main__":
    main()
