#!/usr/bin/env python3
"""
run.py — Phase 1 corpus-mining CLI (per-query sharded).

Typical incremental workflow (Option A):

  python run.py selftest                          # offline validation, no token
  export GITHUB_TOKEN=ghp_...
  python run.py status                            # what's collected / pending
  python run.py search --languages Go,Java,CSharp,Ruby,PHP   # only these langs
  python run.py merge                             # union shards (+ legacy backup)
  python run.py subsample                         # stratified sample -> hits.jsonl
  python run.py enrich
  python run.py fetch
  python run.py filter
  python run.py dedup
  python run.py sample

Notes
-----
* Each (term,language) query is an independent shard under hits/<shard>.jsonl,
  independently checkpointed and resumable.
* --languages accepts aliases (Go, Java, CSharp/CS, Ruby, PHP, JS, TS, Python).
  Tip: quote it if you include C# literally, since the shell treats # as a
  comment: --languages "Go,Java,C#,Ruby,PHP"  (or just use CSharp).
* `merge` unions all shards plus an optional legacy hits.full.jsonl backup.
* `subsample` narrows hits.merged.jsonl to hits.jsonl using per-term caps in
  config.yaml (subsample.caps); groups smaller than their cap are kept whole.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import yaml


def load_cfg(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _print_status(res: dict) -> None:
    print(f"\nlegacy hits.full.jsonl: {res['legacy_full_manifest_hits']} hits\n")
    print(f"{'status':9} {'language':12} {'term':30} {'hits':>7} {'slices':>7}")
    print("-" * 70)
    order = {"partial": 0, "pending": 1, "complete": 2}
    for r in sorted(res["shards"], key=lambda x: (order.get(x["status"], 9), -x["hits"])):
        print(f"{r['status']:9} {r['language']:12} {r['term']:30} {r['hits']:7} {r['slices_done']:7}")


def _print_subsample(res: dict) -> None:
    print(f"\nsource={res['source']}  total={res['total']}  kept={res['kept']}  seed={res['seed']}\n")
    print(f"{'language':12} {'term':30} {'total':>7} {'kept':>6} {'cap':>6}")
    print("-" * 66)
    for b in res["breakdown"]:
        print(f"{(b['language'] or '?'):12} {b['term']:30} {b['total']:7} {b['kept']:6} {b['cap']:6}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1 presigned-URL corpus miner")
    ap.add_argument("stage", choices=[
        "selftest", "status", "search", "merge", "subsample",
        "enrich", "fetch", "filter", "dedup", "sample", "all",
    ])
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--languages", default=None,
                    help="CSV language filter for search, e.g. Go,Java,CSharp,Ruby,PHP")
    ap.add_argument("--dry-run", action="store_true",
                    help="search: process only a few slices to smoke-test the token")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("run")

    if args.stage == "selftest":
        import selftest
        return selftest.run()

    cfg = load_cfg(args.config)
    out = cfg.get("output_dir", "./phase1_out")
    import stages

    # --- stages needing no client ---
    if args.stage == "status":
        _print_status(stages.status_report(cfg, out))
        return 0
    if args.stage == "merge":
        print(json.dumps(stages.merge_hits(cfg, out), indent=2))
        return 0
    if args.stage == "subsample":
        _print_subsample(stages.subsample_hits(cfg, out))
        return 0
    if args.stage in ("filter", "dedup", "sample"):
        fn = {"filter": stages.stage_filter, "dedup": stages.stage_dedup,
              "sample": stages.stage_sample}[args.stage]
        print(json.dumps(fn(cfg, out), indent=2))
        return 0

    # --- stages needing a client ---
    from gh_client import client_from_env, AuthError
    try:
        client = client_from_env(logging.getLogger("gh"))
    except AuthError as e:
        log.error(str(e))
        return 2

    def do(stage: str):
        if stage == "search":
            return stages.stage_search(client, cfg, out, languages=args.languages,
                                       limit_slices=3 if args.dry_run else None)
        if stage == "enrich":
            return stages.stage_enrich(client, cfg, out)
        if stage == "fetch":
            return stages.stage_fetch(client, cfg, out)
        raise ValueError(stage)

    if args.stage == "all":
        for st in ("search",):
            print(json.dumps(do(st), indent=2))
        print(json.dumps(stages.merge_hits(cfg, out), indent=2))
        _print_subsample(stages.subsample_hits(cfg, out))
        for st in ("enrich", "fetch"):
            print(json.dumps(do(st), indent=2))
        for name, fn in (("filter", stages.stage_filter),
                         ("dedup", stages.stage_dedup),
                         ("sample", stages.stage_sample)):
            print(json.dumps(fn(cfg, out), indent=2))
        log.info("client stats: requests=%d sleeps=%d slept=%.0fs",
                 client.n_requests, client.n_sleeps, client.slept_seconds)
        return 0

    res = do(args.stage)
    print(json.dumps(res, indent=2))
    log.info("client stats: requests=%d sleeps=%d slept=%.0fs",
             client.n_requests, client.n_sleeps, client.slept_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
