"""Main Phase 2 extraction pipeline.

Reads the Phase 1 manifest (sample.jsonl) + sha-addressed blobs directory,
filters junk (import-only / type-def / test / abstract-def / no-sdk-call),
auto-fills mechanical columns for the rest, and writes a coding spreadsheet
(CSV, and XLSX if openpyxl is available) with the five judgment columns
(JF1-JF5) left blank, plus a context.txt-equivalent window column and a
NEEDS_REVIEW flag column, per the design doc.
"""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

from . import classify, mechanical, patterns, window

JUDGMENT_COLUMNS = [
    "JF1_post_key_tightness",
    "JF2_key_provenance",
    "JF2_authz_gate",
    "JF3_credential_lifetime",
    "JF4_upload_size_exposure",
    "JF5_expiry_bucket",
    "JF5_expiry_appropriateness",
]

# Manual row-level screen/flags from codebook v2 (Section 0 + multi-site rule).
SCREEN_COLUMNS = ["ELIGIBLE", "INELIGIBLE_REASON", "s3_compatible", "MULTI_SITE", "coder_notes"]

# Valid codes per manually-coded column -> becomes dropdown validation in XLSX.
VALID_CODES = {
    "ELIGIBLE": ["TRUE", "FALSE"],
    "INELIGIBLE_REASON": ["NON_AWS_SAMENAME", "CLOUDFRONT", "OTHER_CLOUD", "SDK_SOURCE", "FAKE_MOCK", "OTHER"],
    "s3_compatible": ["TRUE", "FALSE"],
    "MULTI_SITE": ["TRUE", "FALSE"],
    "JF1_post_key_tightness": ["EXACT", "PREFIX", "EMPTY_PREFIX", "UNSCOPED_KEY", "INDETERMINATE"],
    "JF2_key_provenance": ["SERVER", "USER_SANITIZED", "USER_RAW", "INDETERMINATE"],
    "JF2_authz_gate": ["AUTHZ_PRESENT", "AUTHN_ONLY", "NONE", "INDETERMINATE"],
    "JF3_credential_lifetime": ["LONG_LIVED_IAM", "STS_TEMPORARY", "ROLE_OR_CHAIN", "INDETERMINATE"],
    "JF4_upload_size_exposure": ["BOUNDED_POST", "UNBOUNDED_POST", "UNBOUNDED_PUT", "APP_BOUNDED_PUT", "N_A", "INDETERMINATE"],
    "JF5_expiry_bucket": ["SHORT", "MODERATE", "LONG", "VERY_LONG", "DEFAULT_UNSET", "INDETERMINATE"],
    "JF5_expiry_appropriateness": ["APPROPRIATE", "OVER_LONG", "INDETERMINATE"],
}

MECHANICAL_COLUMNS = [
    "repo", "path", "sha", "html_url", "term", "language_query", "stratum",
    "stars", "cluster_size",
    "match_type", "match_type_reason",
    "mechanism", "mechanism_needs_review",
    "match_line_no",
    "expiry_raw_value", "expiry_unit", "expiry_seconds", "expiry_source_text",
    "content_length_range_present", "conditions_visible", "content_type_condition_present", "acl_field",
    "params_locality", "referenced_var", "referenced_var_resolved",
]

ALL_COLUMNS = MECHANICAL_COLUMNS + ["needs_review", "needs_review_reasons"] + SCREEN_COLUMNS + JUDGMENT_COLUMNS + [
    "call_site_window", "referenced_snippet",
]

JUNK_COLUMNS = ["repo", "path", "sha", "term", "language_query", "match_type", "match_type_reason"]


def load_manifest(manifest_path: Path) -> list[dict]:
    rows = []
    with open(manifest_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_blob(blobs_dir: Path, sha: str) -> str | None:
    # Support both blob layouts: flat (blobs/<sha>.txt, as in the p2peek
    # calibration zip) and 2-hex-char sharded (blobs/<sha[:2]>/<sha>.txt,
    # the actual Phase 1 pipeline layout with 256 subdirectories).
    candidates = [blobs_dir / f"{sha}.txt", blobs_dir / sha[:2] / f"{sha}.txt"]
    for p in candidates:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return None
    return None


def process_row(manifest_row: dict, full_text: str, window_lines: int = window.WINDOW_LINES) -> dict:
    term = manifest_row["term"]
    path = manifest_row["path"]

    match_type, reason = classify.classify_match_type(term, path, full_text)

    out = {c: manifest_row.get(c, "") for c in
           ["repo", "path", "sha", "html_url", "term", "language_query", "stratum", "stars", "cluster_size"]}
    out["match_type"] = match_type
    out["match_type_reason"] = reason

    if match_type != classify.CALL:
        return out  # junk row; caller routes this to the excluded sheet

    win = window.extract_window(full_text, term, window_lines=window_lines)
    mech, mech_needs_review = patterns.disambiguate_mechanism(term, win["window_text"])

    expiry = mechanical.extract_expiry(win["window_text"])
    clr = mechanical.extract_content_length_range(win["window_text"])
    cond_vis = mechanical.conditions_visible(win["window_text"])
    ctc = mechanical.extract_content_type_condition(win["window_text"])
    acl = mechanical.extract_acl(win["window_text"])
    locality = mechanical.params_locality(win["referenced_var"], win["referenced_resolved"])

    needs_review_reasons = []
    if mech_needs_review:
        needs_review_reasons.append("mechanism_ambiguous")
    if locality == "REFERENCED_NONLOCAL":
        needs_review_reasons.append("params_referenced_nonlocal")
    if expiry["expiry_raw_value"] is None:
        needs_review_reasons.append("expiry_not_found_in_window")
    if mech == "POST-policy" and not cond_vis:
        # The policy itself is not in the window: JF1 and JF4 are both
        # unreadable here, and content_length_range_present must NOT be
        # interpreted as "no size bound".
        needs_review_reasons.append("post_conditions_not_visible")

    out.update({
        "mechanism": mech,
        "mechanism_needs_review": mech_needs_review,
        "match_line_no": win["match_line_no"],
        "expiry_raw_value": expiry["expiry_raw_value"],
        "expiry_unit": expiry["expiry_unit"],
        "expiry_seconds": expiry["expiry_seconds"],
        "expiry_source_text": expiry["expiry_source_text"],
        "content_length_range_present": clr,
        "conditions_visible": cond_vis,
        "content_type_condition_present": ctc,
        "acl_field": acl,
        "params_locality": locality,
        "referenced_var": win["referenced_var"],
        "referenced_var_resolved": win["referenced_resolved"],
        "needs_review": bool(needs_review_reasons),
        "needs_review_reasons": ";".join(needs_review_reasons),
        "call_site_window": win["window_text"],
        "referenced_snippet": win["referenced_snippet"],
    })
    for col in SCREEN_COLUMNS + JUDGMENT_COLUMNS:
        out[col] = ""
    return out


def run(manifest_path: Path, blobs_dir: Path, out_csv: Path, out_xlsx: Path | None = None,
        missing_blob_report: Path | None = None, window_lines: int = window.WINDOW_LINES):
    manifest = load_manifest(manifest_path)
    coding_rows = []
    junk_rows = []
    missing = []

    for mrow in manifest:
        text = load_blob(blobs_dir, mrow["sha"])
        if text is None:
            missing.append(mrow)
            continue
        result = process_row(mrow, text, window_lines=window_lines)
        if result["match_type"] == classify.CALL:
            coding_rows.append(result)
        else:
            junk_rows.append(result)

    _write_csv(out_csv, coding_rows, ALL_COLUMNS)
    junk_csv = out_csv.with_name(out_csv.stem + "_excluded.csv")
    _write_csv(junk_csv, junk_rows, JUNK_COLUMNS)

    if missing_blob_report and missing:
        _write_csv(missing_blob_report, missing, list(missing[0].keys()))

    if out_xlsx is not None:
        try:
            _write_xlsx(out_xlsx, coding_rows, junk_rows)
        except ImportError:
            print("openpyxl not installed; skipping XLSX output (CSV written).", file=sys.stderr)

    return {
        "total_manifest_rows": len(manifest),
        "coding_rows": len(coding_rows),
        "excluded_rows": len(junk_rows),
        "missing_blobs": len(missing),
        "needs_review_rows": sum(1 for r in coding_rows if r.get("needs_review")),
    }


def _write_csv(path: Path, rows: list[dict], columns: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_xlsx(path: Path, coding_rows: list[dict], junk_rows: list[dict]):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "coding_sheet"
    ws.append(ALL_COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    screen_fill = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
    judgment_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    for i, col in enumerate(ALL_COLUMNS, start=1):
        if col in SCREEN_COLUMNS:
            ws.cell(row=1, column=i).fill = screen_fill
        elif col in JUDGMENT_COLUMNS:
            ws.cell(row=1, column=i).fill = judgment_fill

    for r in coding_rows:
        ws.append([r.get(c, "") for c in ALL_COLUMNS])

    n_rows = len(coding_rows) + 1
    # dropdown validation on every manually-coded column, so a typo can never
    # produce an invalid code (invalid codes silently wreck kappa computation)
    for col_name, codes in VALID_CODES.items():
        if col_name not in ALL_COLUMNS:
            continue
        col_letter = get_column_letter(ALL_COLUMNS.index(col_name) + 1)
        dv = DataValidation(type="list", formula1='"' + ",".join(codes) + '"',
                            allow_blank=True, showErrorMessage=True,
                            errorTitle="Invalid code",
                            error=f"Valid codes for {col_name}: " + ", ".join(codes))
        ws.add_data_validation(dv)
        dv.add(f"{col_letter}2:{col_letter}{max(n_rows, 2)}")

    # usability: freeze header + identity columns; readable widths; wrap the window
    ws.freeze_panes = "D2"
    widths = {"repo": 28, "path": 36, "call_site_window": 60, "referenced_snippet": 40,
              "needs_review_reasons": 26, "coder_notes": 30, "html_url": 18}
    for i, col in enumerate(ALL_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(col, max(12, min(len(col) + 2, 24)))
    win_idx = ALL_COLUMNS.index("call_site_window") + 1
    for row in ws.iter_rows(min_row=2, min_col=win_idx, max_col=win_idx, max_row=n_rows):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    # crib sheet: valid codes per field, so the coder never leaves the workbook
    ws_codes = wb.create_sheet("codes_reference")
    ws_codes.append(["column", "valid codes"])
    for cell in ws_codes[1]:
        cell.font = Font(bold=True)
    for col_name, codes in VALID_CODES.items():
        ws_codes.append([col_name, " / ".join(codes)])
    ws_codes.column_dimensions["A"].width = 30
    ws_codes.column_dimensions["B"].width = 90

    ws2 = wb.create_sheet("excluded")
    ws2.append(JUNK_COLUMNS)
    for cell in ws2[1]:
        cell.font = Font(bold=True)
    for r in junk_rows:
        ws2.append([r.get(c, "") for c in JUNK_COLUMNS])

    wb.save(path)