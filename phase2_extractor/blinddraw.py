"""Blind draws for the two validation protocols in the codebook:

1. The hidden human-coded validation set (~80-100 files) that measures
   machine/LLM-vs-human agreement per field for the paper.
2. The inter-rater double-coding subsample (~15-20% of the coded set) for
   Cohen's kappa.

Both need the same artifact: a BLINDED coding sheet — call-site windows and
identity columns only, with every machine label (mechanism, expiry,
content-length-range, ACL, needs_review...) stripped, and all screen/judgment
columns blank. Per the codebook: "no machine labels, no first-rater labels
visible."

The draw is seeded and stratified by the machine's mechanism column (so
POST-policy files — the JF1 carriers — are represented), but the mechanism
itself is NOT written to the blinded sheet; it's only used for stratification.
A separate key file records which rows were drawn (sha + stratification
info) so agreement can be computed by joining on sha afterwards.
"""
from __future__ import annotations
import csv
import random
from pathlib import Path

from .pipeline import SCREEN_COLUMNS, JUDGMENT_COLUMNS, VALID_CODES

BLIND_IDENTITY_COLUMNS = ["repo", "path", "sha", "html_url", "term", "language_query"]
BLIND_COLUMNS = BLIND_IDENTITY_COLUMNS + SCREEN_COLUMNS + JUDGMENT_COLUMNS + [
    "call_site_window", "referenced_snippet",
]


def draw_blind(coding_sheet_csv: Path, n: int, seed: int, out_csv: Path,
               out_xlsx: Path | None = None, key_out: Path | None = None) -> dict:
    with open(coding_sheet_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    rng = random.Random(seed)
    by_mech: dict[str, list[dict]] = {}
    for r in rows:
        by_mech.setdefault(r.get("mechanism", "UNKNOWN"), []).append(r)
    for bucket in by_mech.values():
        rng.shuffle(bucket)

    # proportional allocation by mechanism, with every non-empty stratum
    # getting at least one row so no mechanism is invisible in validation
    total = len(rows)
    n = min(n, total)
    alloc = {}
    for mech, bucket in sorted(by_mech.items()):
        alloc[mech] = max(1, round(n * len(bucket) / total)) if bucket else 0
    # trim/pad to hit n exactly, trimming from the largest strata first
    while sum(alloc.values()) > n:
        biggest = max(alloc, key=lambda m: alloc[m])
        alloc[biggest] -= 1
    while sum(alloc.values()) < n:
        for mech in sorted(by_mech, key=lambda m: -len(by_mech[m])):
            if alloc[mech] < len(by_mech[mech]):
                alloc[mech] += 1
                break
        else:
            break

    drawn = []
    for mech, k in alloc.items():
        drawn.extend(by_mech[mech][:k])
    rng.shuffle(drawn)  # don't present grouped by mechanism — that leaks the label

    # blinded sheet: identity + windows only, judgment/screen blank
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=BLIND_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in drawn:
            blank = {c: r.get(c, "") for c in BLIND_IDENTITY_COLUMNS + ["call_site_window", "referenced_snippet"]}
            for c in SCREEN_COLUMNS + JUDGMENT_COLUMNS:
                blank[c] = ""
            w.writerow(blank)

    if out_xlsx is not None:
        try:
            _write_blind_xlsx(out_xlsx, drawn)
        except ImportError:
            pass

    if key_out is not None:
        with open(key_out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["sha", "repo", "path", "mechanism_stratum"])
            w.writeheader()
            for r in drawn:
                w.writerow({"sha": r["sha"], "repo": r["repo"], "path": r["path"],
                            "mechanism_stratum": r.get("mechanism", "")})

    return {
        "coding_sheet_rows": total,
        "drawn": len(drawn),
        "seed": seed,
        "allocation_by_mechanism_stratum": alloc,
        "note": "mechanism used for stratification only; NOT present in the blinded sheet",
    }


def _write_blind_xlsx(path: Path, drawn: list[dict]):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "blind_coding"
    ws.append(BLIND_COLUMNS)
    fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    for i, col in enumerate(BLIND_COLUMNS, start=1):
        ws.cell(row=1, column=i).font = Font(bold=True)
        if col in SCREEN_COLUMNS or col in JUDGMENT_COLUMNS:
            ws.cell(row=1, column=i).fill = fill

    for r in drawn:
        row = {c: r.get(c, "") for c in BLIND_IDENTITY_COLUMNS + ["call_site_window", "referenced_snippet"]}
        for c in SCREEN_COLUMNS + JUDGMENT_COLUMNS:
            row[c] = ""
        ws.append([row.get(c, "") for c in BLIND_COLUMNS])

    n_rows = len(drawn) + 1
    for col_name, codes in VALID_CODES.items():
        if col_name not in BLIND_COLUMNS:
            continue
        col_letter = get_column_letter(BLIND_COLUMNS.index(col_name) + 1)
        dv = DataValidation(type="list", formula1='"' + ",".join(codes) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col_letter}2:{col_letter}{max(n_rows, 2)}")

    ws.freeze_panes = "D2"
    widths = {"repo": 28, "path": 36, "call_site_window": 60, "referenced_snippet": 40, "coder_notes": 30}
    for i, col in enumerate(BLIND_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(col, max(12, min(len(col) + 2, 24)))
    win_idx = BLIND_COLUMNS.index("call_site_window") + 1
    for row in ws.iter_rows(min_row=2, min_col=win_idx, max_col=win_idx, max_row=n_rows):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(path)
