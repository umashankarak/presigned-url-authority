from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from . import agreement, blinddraw, pipeline, postsample, prefill, propose, windowdedup


def cmd_extract(args):
    stats = pipeline.run(
        manifest_path=Path(args.manifest),
        blobs_dir=Path(args.blobs),
        out_csv=Path(args.out),
        out_xlsx=Path(args.out).with_suffix(".xlsx") if args.xlsx else None,
        missing_blob_report=Path(args.out).with_name(Path(args.out).stem + "_missing_blobs.csv"),
        window_lines=args.window_lines,
    )
    print(json.dumps(stats, indent=2))


def cmd_postsample(args):
    sampled, stats = postsample.draw_post_sample(
        full_corpus_manifest=Path(args.corpus_manifest),
        n=args.n,
        seed=args.seed,
        existing_sample_manifest=Path(args.existing_sample) if args.existing_sample else None,
        allocation=args.allocation,
    )
    postsample.write_jsonl(Path(args.out), sampled)
    print(json.dumps(stats, indent=2))


def cmd_blinddraw(args):
    out = Path(args.out)
    stats = blinddraw.draw_blind(
        coding_sheet_csv=Path(args.coding_sheet),
        n=args.n, seed=args.seed,
        out_csv=out,
        out_xlsx=out.with_suffix(".xlsx"),
        key_out=out.with_name(out.stem + "_draw_key.csv"),
    )
    print(json.dumps(stats, indent=2))


def cmd_prefill(args):
    import csv as _csv
    rows = list(_csv.DictReader(open(args.coding_sheet, encoding="utf-8")))
    cols = list(rows[0].keys()) if rows else []
    extra = ["rule_JF1", "rule_JF1_why", "rule_JF4", "rule_JF4_why", "rule_JF5A", "rule_JF5A_why"]
    out_cols = cols + [c for c in extra if c not in cols]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fired = {"rule_JF1": 0, "rule_JF4": 0, "rule_JF5A": 0}
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=out_cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            pf = prefill.prefill_row(r)
            for k in fired:
                if pf.get(k):
                    fired[k] += 1
            w.writerow({**r, **pf})
    print(json.dumps({"rows": len(rows), "rules_fired": fired, "out": str(out)}, indent=2))


def cmd_propose(args):
    stats = propose.run(Path(args.coding_sheet), Path(args.out),
                        limit=args.limit, dry_run=args.dry_run, resume=not args.no_resume)
    print(json.dumps(stats, indent=2))


def cmd_agreement(args):
    if args.rater2:
        res = agreement.score_human_vs_human(Path(args.coded), Path(args.rater2))
        label = "human_vs_human_kappa"
    else:
        res = agreement.score_machine_vs_human(Path(args.coded))
        label = "machine_vs_human"
    print(json.dumps({label: res,
                      "indeterminate_rates": agreement.indeterminate_rates(Path(args.coded))}, indent=2))


def cmd_windowdedup(args):
    stats = windowdedup.dedup(Path(args.coding_sheet), Path(args.out), jaccard_threshold=args.threshold)
    print(json.dumps(stats, indent=2))


def cmd_selftest(args):
    from . import selftest
    ok = selftest.run(verbose=True)
    sys.exit(0 if ok else 1)


def main():
    p = argparse.ArgumentParser(prog="phase2_extractor", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    pe = sub.add_parser("extract", help="Build the Phase 2 coding spreadsheet from manifest + blobs")
    pe.add_argument("--manifest", required=True, help="Path to sample.jsonl (the 500-file manifest)")
    pe.add_argument("--blobs", required=True, help="Path to the blobs/ directory (sha-addressed .txt files)")
    pe.add_argument("--out", required=True, help="Output CSV path (XLSX written alongside if --xlsx)")
    pe.add_argument("--window-lines", type=int, default=15,
                    help="Lines of context each side of the match (default 15). Widen if policy Conditions fall outside the window.")
    pe.add_argument("--xlsx", action="store_true", help="Also write an XLSX workbook (requires openpyxl)")
    pe.set_defaults(func=cmd_extract)

    pp = sub.add_parser("postsample", help="Draw the targeted POST-policy re-sample from the full corpus")
    pp.add_argument("--corpus-manifest", required=True, help="Full corpus manifest jsonl (not the 500-file sample)")
    pp.add_argument("--existing-sample", default=None, help="The primary 500-file sample.jsonl, to avoid re-drawing the same files")
    pp.add_argument("--n", type=int, default=250, help="Target sample size (default 250, per the 200-300 target)")
    pp.add_argument("--seed", type=int, default=43, help="Random seed (default 43, distinct from the primary seed 42)")
    pp.add_argument("--allocation", choices=["proportional", "equal"], default="proportional",
                    help="Language allocation. 'proportional' (default) mirrors corpus composition so pooled rates are interpretable; 'equal' draws equal n per language (report per-language and weight before pooling)")
    pp.add_argument("--out", required=True, help="Output jsonl path for the targeted sample manifest")
    pp.set_defaults(func=cmd_postsample)

    pb = sub.add_parser("blinddraw", help="Seeded blind draw for the validation set / double-coding kappa subsample")
    pb.add_argument("--coding-sheet", required=True, help="The coding_sheet.csv produced by extract")
    pb.add_argument("--n", type=int, default=90, help="Rows to draw (default 90; use ~15-20%% of coded set for the kappa subsample)")
    pb.add_argument("--seed", type=int, default=44, help="Random seed (default 44; use a different seed per draw)")
    pb.add_argument("--out", required=True, help="Output blinded CSV path (XLSX written alongside)")
    pb.set_defaults(func=cmd_blinddraw)

    pf = sub.add_parser("prefill", help="Deterministic rule-based pre-fill (no LLM) for mechanically-decidable JF cells")
    pf.add_argument("--coding-sheet", required=True)
    pf.add_argument("--out", required=True)
    pf.set_defaults(func=cmd_prefill)

    pr = sub.add_parser("propose", help="LLM proposal pass: JF codes + rationale + confidence in SEPARATE columns")
    pr.add_argument("--coding-sheet", required=True)
    pr.add_argument("--out", required=True)
    pr.add_argument("--limit", type=int, default=None, help="Only process the first N rows (use for a cheap trial)")
    pr.add_argument("--dry-run", action="store_true", help="Preview prompt + token estimate, make no API calls")
    pr.add_argument("--no-resume", action="store_true", help="Ignore existing output and re-propose everything")
    pr.set_defaults(func=cmd_propose)

    pa = sub.add_parser("agreement", help="Score machine-vs-human, or human-vs-human kappa with --rater2")
    pa.add_argument("--coded", required=True, help="Coded CSV with human JF columns filled")
    pa.add_argument("--rater2", default=None, help="Second rater's coded CSV (switches to inter-rater kappa)")
    pa.set_defaults(func=cmd_agreement)

    pw = sub.add_parser("windowdedup", help="Cluster near-duplicate call-site windows (copy-paste tutorial detection)")
    pw.add_argument("--coding-sheet", required=True)
    pw.add_argument("--out", required=True)
    pw.add_argument("--threshold", type=float, default=0.92, help="Token-Jaccard threshold for fuzzy merge (default 0.92)")
    pw.set_defaults(func=cmd_windowdedup)

    ps = sub.add_parser("selftest", help="Run the self-test against the bundled calibration fixtures")
    ps.set_defaults(func=cmd_selftest)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
