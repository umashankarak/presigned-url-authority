"""Correction 1: recode the size bound of site B0006 under the PUT size rule.

A PUT URL counts as size-bounded only when the expected content length is
signed into it (CODEBOOK.md, JF4). B0006 was first coded APP_BOUNDED_PUT
because the server checks a file size; on recheck the server uploads the file
itself and then issues a URL for the stored object through a helper whose
method is not visible. Size bound becomes INDETERMINATE.

Already applied to the data files in phase2/data/; kept as a record of the
change. Rerunning it on the published files stops with "expected
APP_BOUNDED_PUT", because the value has already changed.

Usage (edits the workbook in place; a .bak copy is written first):
    python3 reclassify_put_size.py <coded_sheet.xlsx> [<more.xlsx> ...]

Works on both the identified sheet (matched by `sha`) and the de-identified
GitHub sheet (matched by `row_id` or `blob_sha`).
"""
import shutil
import sys
import time

from openpyxl import load_workbook

SHA = "f34df19ae6b7ee7b3f69d7a664179cc137102b56"
ROW_ID = "B0006"
FIELD = "JF4_upload_size_exposure"
OLD, NEW = "APP_BOUNDED_PUT", "INDETERMINATE"
NOTE = ("PUT size rule: server uploads the file itself, then issues a URL for "
        "the stored object; not a presigned upload grant. "
        "JF4 APP_BOUNDED_PUT -> INDETERMINATE.")


def patch(path: str) -> None:
    shutil.copy2(path, path + ".bak")
    wb = load_workbook(path)
    ws = wb.worksheets[0]
    header = [c.value for c in ws[1]]
    col = {name: i + 1 for i, name in enumerate(header) if name}
    if FIELD not in col:
        sys.exit(f"{path}: column {FIELD} not found")
    hits = 0
    for r in range(2, ws.max_row + 1):
        ident = {ws.cell(r, col[k]).value for k in ("sha", "blob_sha", "row_id") if k in col}
        if SHA in ident or ROW_ID in ident:
            cur = ws.cell(r, col[FIELD]).value
            if cur != OLD:
                sys.exit(f"{path}: row {r} has {FIELD}={cur!r}, expected {OLD!r}; nothing changed")
            ws.cell(r, col[FIELD]).value = NEW
            if "coder_notes" in col:
                prev = ws.cell(r, col["coder_notes"]).value
                ws.cell(r, col["coder_notes"]).value = f"{prev} | {NOTE}" if prev else NOTE
            hits += 1
    if hits != 1:
        sys.exit(f"{path}: expected exactly 1 matching row, found {hits}; nothing saved")
    wb.save(path)
    print(f"{path}: {FIELD} {OLD} -> {NEW} (backup at {path}.bak)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        patch(p)
