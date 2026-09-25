"""Self-test: runs the pipeline against the bundled 24-file calibration
sample (fixtures/) and asserts a set of known-correct outcomes, several of
them taken directly from the codebook's worked examples plus a few real
traps found in this specific sample (a Ruby fake/mock implementation, a
.d.ts type stub, a case-mismatched C# identifier). This is not a substitute
for validating against your full corpus — it's a regression check so future
edits to the regex/heuristics don't silently break the cases already known
to matter.
"""
from __future__ import annotations
import csv
import sys
import tempfile
from pathlib import Path

from . import pipeline

FIXTURES = Path(__file__).parent / "fixtures"


def _index_by_repo(rows):
    return {r["repo"]: r for r in rows}


def run(verbose: bool = False) -> bool:
    if verbose:
        from . import __version__
        print(f"phase2_extractor v{__version__}")
    with tempfile.TemporaryDirectory() as tmp:
        out_csv = Path(tmp) / "coding_sheet.csv"
        stats = pipeline.run(
            manifest_path=FIXTURES / "peek_sample.jsonl",
            blobs_dir=FIXTURES / "blobs",
            out_csv=out_csv,
        )

        with open(out_csv, encoding="utf-8") as f:
            coding = list(csv.DictReader(f))
        with open(out_csv.with_name(out_csv.stem + "_excluded.csv"), encoding="utf-8") as f:
            excluded = list(csv.DictReader(f))

    coding_by_repo = _index_by_repo(coding)
    excluded_by_repo = _index_by_repo(excluded)

    checks = []

    def check(name, cond):
        checks.append((name, cond))
        if verbose:
            print(("PASS" if cond else "FAIL") + " - " + name)

    # --- manifest bookkeeping ---
    check("all 24 fixture rows accounted for", stats["total_manifest_rows"] == 24)
    check("no missing blobs", stats["missing_blobs"] == 0)

    # --- exclusions: junk correctly filtered ---
    check("Java test file excluded as TEST",
          excluded_by_repo.get("Team-Kiero/Kiero-Server", {}).get("match_type") == "TEST")
    check(".d.ts type stub excluded as TYPE_DEF",
          excluded_by_repo.get("DefinitelyTyped/DefinitelyTyped", {}).get("match_type") == "TYPE_DEF")
    check("PHP import-only usage excluded as IMPORT_ONLY",
          excluded_by_repo.get("Interfacelab/ilab-media-tools", {}).get("match_type") == "IMPORT_ONLY")
    # A Ruby fake/mock implementation (`presigned_url_for`, no real AWS call)
    # has call syntax, so it isn't auto-excluded -- but it must never be
    # confidently coded as a real mechanism. Flagging NEEDS_REVIEW here is the
    # correct, honest outcome (a human dismisses this in seconds; silently
    # auto-dropping it risks a false negative on a file that could be real).
    fake_ruby = coding_by_repo.get("alphagov/asset-manager", {})
    check("Ruby fake/mock implementation: not confidently coded as any real mechanism",
          fake_ruby.get("mechanism") == "INDETERMINATE")
    check("Ruby fake/mock implementation: flagged needs_review",
          fake_ruby.get("needs_review") == "True")

    # --- worked examples from the codebook (PG-genie) ---
    pg = coding_by_repo.get("coderashhar/PG-genie", {})
    check("PG-genie: classified as CALL", "coderashhar/PG-genie" in coding_by_repo)
    check("PG-genie: mechanism POST-policy", pg.get("mechanism") == "POST-policy")
    check("PG-genie: expiry 300 seconds", pg.get("expiry_raw_value") == "300" and pg.get("expiry_unit") == "seconds")
    check("PG-genie: content-length-range present", pg.get("content_length_range_present") == "True")
    check("PG-genie: content-type condition present", pg.get("content_type_condition_present") == "True")
    check("PG-genie: params inline (Key/Conditions built at call site)", pg.get("params_locality") == "INLINE")

    # --- chainjet (codebook's INDETERMINATE worked example for JF1;
    #     the extractor's job is just to flag non-local params, not judge JF1) ---
    cj = coding_by_repo.get("chainjet/platform", {})
    check("chainjet: mechanism POST-policy", cj.get("mechanism") == "POST-policy")
    # NOTE: in this actual sample, params IS resolvable in-file (built ~9 lines
    # above the call) -- update if the codebook's characterization refers to a
    # different/broader window than the 15-line default.

    # --- case-mismatch trap: manifest term casing differs from source ---
    carbon = coding_by_repo.get("carbon/Amazon", {})
    check("carbon/Amazon: case-insensitive fallback still finds the call",
          carbon.get("mechanism") == "GET-URL")
    check("carbon/Amazon: flagged needs_review (case-insensitive match)",
          carbon.get("needs_review") == "True")

    # --- ambiguous-mechanism terms correctly flagged, not guessed ---
    newpresign = [r for r in coding if r["term"] == "NewPresignClient"]
    check("NewPresignClient (client constructor, not a method call): all instances INDETERMINATE, not guessed",
          all(r["mechanism"] == "INDETERMINATE" for r in newpresign) and len(newpresign) >= 1)

    all_pass = all(c for _, c in checks)
    if verbose:
        n_pass = sum(1 for _, c in checks if c)
        print(f"\n{n_pass}/{len(checks)} checks passed")
    return all_pass


if __name__ == "__main__":
    ok = run(verbose=True)
    sys.exit(0 if ok else 1)
