"""
stages.py — the six Phase 1 stages.

Every stage reads/writes explicit JSON(L) artifacts under output_dir and is
resumable: re-running a stage skips work already recorded in its checkpoint.
Stages take an injected `client` (real GitHubClient or a mock) so the whole
pipeline is testable offline.

Artifacts
---------
  hits.jsonl            stage 1  one row per unique (repo, path, sha) hit
  _slices.done         stage 1  checkpoint of completed query slices
  repos.json           stage 2  {full_name -> repo metadata}
  blobs/<sha>.txt      stage 3  sha-addressed file contents
  _blobs.done          stage 3  checkpoint of fetched shas
  filtered.jsonl       stage 4  hits joined w/ repo meta, stratified, forks dropped
  deduped.jsonl        stage 5  one row per near-dup cluster representative
  sample.jsonl         stage 6  the drawn corpus sample
  sampling_frame.json  stage 6  machine-readable frame
  sampling_frame.md    stage 6  human-readable frame
"""

from __future__ import annotations

import collections
import glob
import json
import logging
import os
import random
import re
from typing import Dict, Iterable, List, Optional

from partition import BaseQuery, Slice, build_queries, partition_query

logger = logging.getLogger("stages")


# ---- small io helpers -------------------------------------------------------

def _ensure(d: str) -> str:
    os.makedirs(d, exist_ok=True)
    return d


def _read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _append_jsonl(path: str, row: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_jsonl(path: str, rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _load_set(path: str) -> set:
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        return {ln.strip() for ln in f if ln.strip()}


def _append_line(path: str, val: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(val + "\n")


def _blob_path(out: str, sha: str) -> str:
    d = _ensure(os.path.join(out, "blobs", sha[:2]))
    return os.path.join(d, f"{sha}.txt")


# ---- stage 1: search (per-query shards) -------------------------------------
#
# Each (term, language) query writes its own shard under hits/<shard>.jsonl with
# its own <shard>.done checkpoint. A shard is COMPLETE when its .done file ends
# with the __COMPLETE__ sentinel. This makes the corpus self-documenting (you can
# see which queries finished), lets any single query be re-run in isolation, and
# lets --languages fetch only a subset. The flat hits.jsonl is produced later by
# `merge_hits` (union of shards + any legacy hits.full.jsonl) and then narrowed by
# `subsample_hits`.

_SAFE = re.compile(r"[^A-Za-z0-9]+")
_COMPLETE = "__COMPLETE__"

_LANG_ALIASES = {
    "c#": "c#", "csharp": "c#", "cs": "c#",
    "go": "go", "golang": "go",
    "java": "java", "ruby": "ruby", "php": "php",
    "python": "python", "py": "python",
    "javascript": "javascript", "js": "javascript",
    "typescript": "typescript", "ts": "typescript",
}


def _norm_lang(l: str) -> str:
    return _LANG_ALIASES.get(l.strip().lower(), l.strip().lower())


def _shard_name(term: str, lang: str) -> str:
    return f"{_SAFE.sub('_', term)}__{_SAFE.sub('_', lang)}"


def _filter_by_language(queries: List[BaseQuery], languages) -> List[BaseQuery]:
    if not languages:
        return queries
    req = {_norm_lang(x) for x in languages}
    return [q for q in queries if _norm_lang(q.language) in req]


def stage_search(client, cfg: dict, out: str, languages=None,
                 limit_slices: Optional[int] = None) -> dict:
    """Partitioned code search into per-query shards.

    languages: optional list/CSV of language names (aliases ok: Go, Java, CSharp,
               Ruby, PHP, JS, TS, Python). Only matching queries are searched.
    limit_slices: cap slices processed across this call (used by --dry-run).
    """
    hits_dir = _ensure(os.path.join(out, "hits"))
    if isinstance(languages, str):
        languages = [x for x in languages.split(",") if x.strip()]
    queries = _filter_by_language(build_queries(cfg), languages)
    if not queries:
        return {"stage": "search", "error": "no queries match --languages",
                "languages": languages}

    cap = int(cfg.get("cap", 1000))
    per_page = int(cfg.get("per_page", 100))
    size_min = int(cfg.get("size_min", 0))
    size_max = int(cfg.get("size_max", 384_000))
    probe_cache: Dict[str, int] = {}

    processed = 0
    truncated: List[dict] = []
    shard_summary: Dict[str, dict] = {}

    for base in queries:
        shard = _shard_name(base.term, base.language)
        shard_path = os.path.join(hits_dir, shard + ".jsonl")
        done_path = os.path.join(hits_dir, shard + ".done")
        done = _load_set(done_path)

        if _COMPLETE in done:
            shard_summary[shard] = {"status": "complete", "hits": len(_read_jsonl(shard_path))}
            continue

        seen = {(h["repo"], h["path"], h["sha"]) for h in _read_jsonl(shard_path)}
        shard_complete = True

        for sl in partition_query(client.search_code, base, size_min, size_max, cap, probe_cache):
            if limit_slices is not None and processed >= limit_slices:
                logger.info("slice limit reached (%d); stopping early", limit_slices)
                shard_complete = False
                break
            if sl.query in done:
                continue
            if sl.truncated:
                truncated.append({"query": sl.query, "total_count": sl.total_count})
                logger.warning("irreducible truncated slice (%d>%d): %s",
                               sl.total_count, cap, sl.query)
            n_pages = min(10, (sl.total_count + per_page - 1) // per_page)
            for page in range(1, n_pages + 1):
                resp = client.search_code(q=sl.query, page=page, per_page=per_page)
                if resp.get("incomplete_results"):
                    logger.warning("incomplete_results: %s p%d", sl.query, page)
                for it in resp.get("items", []):
                    repo = it["repository"]["full_name"]
                    key = (repo, it["path"], it["sha"])
                    if key in seen:
                        continue
                    seen.add(key)
                    _append_jsonl(shard_path, {
                        "repo": repo,
                        "path": it["path"],
                        "sha": it["sha"],
                        "git_url": it.get("git_url"),
                        "html_url": it.get("html_url"),
                        "term": base.term,
                        "language_query": base.language,
                    })
            _append_line(done_path, sl.query)
            done.add(sl.query)
            processed += 1

        if shard_complete:
            _append_line(done_path, _COMPLETE)
            shard_summary[shard] = {"status": "complete", "hits": len(_read_jsonl(shard_path))}
        else:
            shard_summary[shard] = {"status": "partial", "hits": len(_read_jsonl(shard_path))}
            _save_truncated(out, truncated)
            return {"stage": "search", "partial": True, "shards": shard_summary,
                    "processed_slices": processed}

    _save_truncated(out, truncated)
    return {"stage": "search", "partial": False, "shards": shard_summary,
            "processed_slices": processed}


def _save_truncated(out: str, truncated: List[dict]) -> None:
    """Maintain a cumulative, deduped truncated-slice log across search calls."""
    p = os.path.join(out, "truncated_slices.json")
    existing = json.load(open(p)) if os.path.exists(p) else []
    seen = {t["query"] for t in existing}
    for t in truncated:
        if t["query"] not in seen:
            existing.append(t)
            seen.add(t["query"])
    with open(p, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)


def merge_hits(cfg: dict, out: str) -> dict:
    """Union all per-query shards (+ legacy hits.full.jsonl if present) into
    hits.merged.jsonl, deduping by (repo, path, sha)."""
    hits_dir = os.path.join(out, "hits")
    sources: List[str] = []
    legacy = os.path.join(out, "hits.full.jsonl")
    if os.path.exists(legacy):
        sources.append(legacy)
    if os.path.isdir(hits_dir):
        sources += sorted(glob.glob(os.path.join(hits_dir, "*.jsonl")))

    seen = set()
    rows: List[dict] = []
    per_source: Dict[str, int] = {}
    for src in sources:
        added = 0
        for row in _read_jsonl(src):
            key = (row["repo"], row["path"], row["sha"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            added += 1
        per_source[os.path.basename(src)] = added

    _write_jsonl(os.path.join(out, "hits.merged.jsonl"), rows)
    return {"stage": "merge", "sources": per_source, "unique_hits": len(rows)}


def subsample_hits(cfg: dict, out: str) -> dict:
    """Stratified, seeded subsample of the merged manifest into hits.jsonl.

    Per-term caps come from cfg['subsample']; groups smaller than their cap are
    kept whole. Reads hits.merged.jsonl (preferred), else hits.full.jsonl."""
    src = os.path.join(out, "hits.merged.jsonl")
    if not os.path.exists(src):
        alt = os.path.join(out, "hits.full.jsonl")
        src = alt if os.path.exists(alt) else os.path.join(out, "hits.jsonl")

    rows = _read_jsonl(src)
    sub = cfg.get("subsample", {}) or {}
    default_cap = int(sub.get("default_cap", 500))
    caps = sub.get("caps", {}) or {}
    seed = int(cfg.get("seed", 42))
    rng = random.Random(seed)

    by = collections.defaultdict(list)
    for r in rows:
        by[(r.get("term"), r.get("language_query"))].append(r)

    keep: List[dict] = []
    breakdown: List[dict] = []
    for (term, lang), v in by.items():
        vv = list(v)
        rng.shuffle(vv)
        cap = int(caps.get(term, default_cap))
        kept = vv[:cap]
        keep.extend(kept)
        breakdown.append({"term": term, "language": lang,
                          "total": len(v), "kept": len(kept), "cap": cap})
    rng.shuffle(keep)

    _write_jsonl(os.path.join(out, "hits.jsonl"), keep)
    breakdown.sort(key=lambda b: -b["total"])
    report = {"source": os.path.basename(src), "seed": seed,
              "total": len(rows), "kept": len(keep), "breakdown": breakdown}
    with open(os.path.join(out, "subsample_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return {"stage": "subsample", **report}


def status_report(cfg: dict, out: str) -> dict:
    """Per-query shard status: hits collected + complete/partial/pending."""
    hits_dir = os.path.join(out, "hits")
    rows: List[dict] = []
    for base in build_queries(cfg):
        shard = _shard_name(base.term, base.language)
        sp = os.path.join(hits_dir, shard + ".jsonl")
        dp = os.path.join(hits_dir, shard + ".done")
        n = len(_read_jsonl(sp)) if os.path.exists(sp) else 0
        done = _load_set(dp) if os.path.exists(dp) else set()
        status = "complete" if _COMPLETE in done else ("partial" if n > 0 else "pending")
        rows.append({"term": base.term, "language": base.language, "hits": n,
                     "slices_done": len([d for d in done if d != _COMPLETE]),
                     "status": status})
    legacy = os.path.join(out, "hits.full.jsonl")
    legacy_n = len(_read_jsonl(legacy)) if os.path.exists(legacy) else 0
    return {"stage": "status", "legacy_full_manifest_hits": legacy_n, "shards": rows}


# ---- stage 2: enrich --------------------------------------------------------

def stage_enrich(client, cfg: dict, out: str) -> dict:
    hits = _read_jsonl(os.path.join(out, "hits.jsonl"))
    repos_path = os.path.join(out, "repos.json")
    cache: Dict[str, dict] = {}
    if os.path.exists(repos_path):
        with open(repos_path, "r", encoding="utf-8") as f:
            cache = json.load(f)

    todo = sorted({h["repo"] for h in hits} - set(cache.keys()))
    for i, full in enumerate(todo, 1):
        try:
            r = client.get_repo(full)
        except Exception as e:  # keep going; record the failure
            logger.warning("repo fetch failed for %s: %s", full, e)
            cache[full] = {"full_name": full, "error": str(e)}
            continue
        cache[full] = {
            "full_name": full,
            "stars": r.get("stargazers_count", 0),
            "fork": bool(r.get("fork", False)),
            "archived": bool(r.get("archived", False)),
            "pushed_at": r.get("pushed_at"),
            "size_kb": r.get("size", 0),
            "license": (r.get("license") or {}).get("spdx_id"),
            "owner_type": (r.get("owner") or {}).get("type"),
            "language": r.get("language"),
        }
        if i % 25 == 0:
            with open(repos_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)

    with open(repos_path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    return {"stage": "enrich", "repos_cached": len(cache), "newly_fetched": len(todo)}


# ---- stage 3: fetch ---------------------------------------------------------

def stage_fetch(client, cfg: dict, out: str) -> dict:
    hits = _read_jsonl(os.path.join(out, "hits.jsonl"))
    done_path = os.path.join(out, "_blobs.done")
    done = _load_set(done_path)
    max_bytes = int(cfg.get("max_file_bytes", 400_000))

    # unique shas (sha-addressed store => fetch each blob once)
    by_sha: Dict[str, dict] = {}
    for h in hits:
        by_sha.setdefault(h["sha"], h)

    fetched = 0
    skipped_large = 0
    skipped_missing = 0
    for sha, h in by_sha.items():
        if sha in done:
            continue
        p = _blob_path(out, sha)
        if os.path.exists(p):
            done.add(sha)
            continue
        if not h.get("git_url"):
            continue
        try:
            text = client.get_blob_text(h["git_url"], max_bytes=max_bytes)
        except Exception as e:
            # The blob's repo/commit was deleted since the search snapshot, or a
            # transient error survived retries. Skip it (mirrors enrich's 404
            # handling) instead of aborting the whole fetch. The sha is marked
            # done so a resume won't retry it.
            logger.warning("blob fetch failed for %s (%s): %s", h["repo"], sha, e)
            skipped_missing += 1
            _append_line(done_path, sha)
            done.add(sha)
            continue
        if text is None:
            skipped_large += 1
            _append_line(done_path, sha)  # mark handled so we don't retry
            done.add(sha)
            continue
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        _append_line(done_path, sha)
        done.add(sha)
        fetched += 1

    return {
        "stage": "fetch",
        "unique_blobs": len(by_sha),
        "newly_fetched": fetched,
        "skipped_binary_or_large": skipped_large,
        "skipped_missing": skipped_missing,
    }


# ---- stage 4: filter + stratify --------------------------------------------

def _inactive_days(pushed_at: Optional[str]) -> Optional[int]:
    if not pushed_at:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.strptime(pushed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).days


def stage_filter(cfg: dict, out: str) -> dict:
    hits = _read_jsonl(os.path.join(out, "hits.jsonl"))
    with open(os.path.join(out, "repos.json"), "r", encoding="utf-8") as f:
        repos = json.load(f)

    q = cfg["quality"]
    min_stars = int(q.get("min_stars", 5))
    max_inactive = int(q.get("max_inactive_days", 1825))
    excl_forks = bool(q.get("exclude_forks", True))
    excl_archived = bool(q.get("exclude_archived", True))

    kept: List[dict] = []
    dropped = {"fork": 0, "archived": 0, "repo_error": 0, "no_blob": 0}
    for h in hits:
        meta = repos.get(h["repo"], {})
        if meta.get("error"):
            dropped["repo_error"] += 1
            continue
        if excl_forks and meta.get("fork"):
            dropped["fork"] += 1
            continue
        if excl_archived and meta.get("archived"):
            dropped["archived"] += 1
            continue
        blob = _blob_path(out, h["sha"])
        if not os.path.exists(blob):
            dropped["no_blob"] += 1
            continue

        inactive = _inactive_days(meta.get("pushed_at"))
        stars = int(meta.get("stars", 0))
        is_primary = (stars >= min_stars) and (inactive is None or inactive <= max_inactive)
        row = dict(h)
        row["stars"] = stars
        row["inactive_days"] = inactive
        row["stratum"] = "primary" if is_primary else "sample"
        kept.append(row)

    _write_jsonl(os.path.join(out, "filtered.jsonl"), kept)
    strata = {"primary": 0, "sample": 0}
    for r in kept:
        strata[r["stratum"]] += 1
    return {"stage": "filter", "kept": len(kept), "dropped": dropped, "strata": strata}


# ---- stage 5: dedup ---------------------------------------------------------

def stage_dedup(cfg: dict, out: str) -> dict:
    from dedup import cluster

    rows = _read_jsonl(os.path.join(out, "filtered.jsonl"))
    if not rows:
        _write_jsonl(os.path.join(out, "deduped.jsonl"), [])
        return {"stage": "dedup", "input": 0, "clusters": 0, "collapsed": 0}

    # load contents keyed by a stable doc id (repo::path::sha)
    def did(r):
        return f'{r["repo"]}::{r["path"]}::{r["sha"]}'

    docs: Dict[str, str] = {}
    for r in rows:
        p = _blob_path(out, r["sha"])
        with open(p, "r", encoding="utf-8") as f:
            docs[did(r)] = f.read()

    d = cfg.get("dedup", {})
    rep_of = cluster(
        docs,
        shingle_k=int(d.get("shingle_k", 5)),
        num_perm=int(d.get("num_perm", 128)),
        bands=int(d.get("bands", 32)),
        threshold=float(d.get("jaccard_threshold", 0.8)),
        seed=int(cfg.get("seed", 42)),
    )

    # group rows by cluster; pick representative = highest stars, then smallest id
    by_cluster: Dict[str, List[dict]] = {}
    for r in rows:
        by_cluster.setdefault(rep_of[did(r)], []).append(r)

    reps: List[dict] = []
    for cid, members in by_cluster.items():
        members_sorted = sorted(members, key=lambda r: (-int(r.get("stars", 0)), did(r)))
        rep = dict(members_sorted[0])
        rep["cluster_size"] = len(members)
        rep["cluster_members"] = [did(m) for m in members_sorted]
        reps.append(rep)

    _write_jsonl(os.path.join(out, "deduped.jsonl"), reps)
    return {
        "stage": "dedup",
        "input": len(rows),
        "clusters": len(reps),
        "collapsed": len(rows) - len(reps),
    }


# ---- stage 6: sample + sampling frame --------------------------------------

def stage_sample(cfg: dict, out: str) -> dict:
    rows = _read_jsonl(os.path.join(out, "deduped.jsonl"))
    seed = int(cfg.get("seed", 42))
    target = int(cfg.get("target_sample_size", 400))

    primary = [r for r in rows if r["stratum"] == "primary"]
    sample_stratum = [r for r in rows if r["stratum"] == "sample"]

    rng = random.Random(seed)

    def draw(pool: List[dict], n: int) -> List[dict]:
        pool_sorted = sorted(pool, key=lambda r: f'{r["repo"]}::{r["path"]}::{r["sha"]}')
        if len(pool_sorted) <= n:
            return pool_sorted
        return rng.sample(pool_sorted, n)

    drawn_primary = draw(primary, target)
    # a fixed, smaller comparison slice of the tutorial/sample stratum
    sample_target = int(cfg.get("sample_stratum_size", max(1, target // 4)))
    drawn_sample = draw(sample_stratum, sample_target)

    drawn = drawn_primary + drawn_sample
    _write_jsonl(os.path.join(out, "sample.jsonl"), drawn)

    # ---- build the sampling frame ----
    hits = _read_jsonl(os.path.join(out, "hits.jsonl"))
    filtered = _read_jsonl(os.path.join(out, "filtered.jsonl"))
    deduped = rows

    def lang_dist(rs):
        d: Dict[str, int] = {}
        for r in rs:
            d[r.get("language_query", "?")] = d.get(r.get("language_query", "?"), 0) + 1
        return dict(sorted(d.items(), key=lambda kv: -kv[1]))

    def term_dist(rs):
        d: Dict[str, int] = {}
        for r in rs:
            d[r.get("term", "?")] = d.get(r.get("term", "?"), 0) + 1
        return dict(sorted(d.items(), key=lambda kv: -kv[1]))

    truncated = []
    tp = os.path.join(out, "truncated_slices.json")
    if os.path.exists(tp):
        with open(tp, "r", encoding="utf-8") as f:
            truncated = json.load(f)

    frame = {
        "snapshot_label": cfg.get("snapshot_label"),
        "seed": seed,
        "counts": {
            "raw_unique_hits": len(hits),
            "unique_repos": len({h["repo"] for h in hits}),
            "after_filter": len(filtered),
            "after_dedup_clusters": len(deduped),
            "near_dup_collapsed": len(filtered) - len(deduped),
            "sampled_total": len(drawn),
        },
        "strata": {
            "primary_available": len(primary),
            "primary_sampled": len(drawn_primary),
            "sample_available": len(sample_stratum),
            "sample_sampled": len(drawn_sample),
        },
        "language_distribution_deduped": lang_dist(deduped),
        "term_distribution_deduped": term_dist(deduped),
        "truncated_slices": truncated,
        "config_quality": cfg.get("quality"),
        "config_dedup": cfg.get("dedup"),
    }
    with open(os.path.join(out, "sampling_frame.json"), "w", encoding="utf-8") as f:
        json.dump(frame, f, indent=2)

    _write_frame_md(os.path.join(out, "sampling_frame.md"), frame)
    return {"stage": "sample", **frame["counts"], "strata": frame["strata"]}


def _write_frame_md(path: str, frame: dict) -> None:
    c = frame["counts"]
    s = frame["strata"]
    lines = []
    lines.append("# Phase 1 Sampling Frame\n")
    lines.append(f"- Snapshot label: `{frame.get('snapshot_label')}`")
    lines.append(f"- RNG seed: `{frame.get('seed')}`\n")
    lines.append("## Corpus funnel\n")
    lines.append("| Stage | Count |")
    lines.append("|---|---|")
    lines.append(f"| Raw unique hits (repo,path,sha) | {c['raw_unique_hits']} |")
    lines.append(f"| Unique repositories | {c['unique_repos']} |")
    lines.append(f"| After quality filter | {c['after_filter']} |")
    lines.append(f"| After near-dup dedup (clusters) | {c['after_dedup_clusters']} |")
    lines.append(f"| Near-duplicates collapsed | {c['near_dup_collapsed']} |")
    lines.append(f"| **Sampled total** | **{c['sampled_total']}** |\n")
    lines.append("## Strata\n")
    lines.append("| Stratum | Available | Sampled |")
    lines.append("|---|---|---|")
    lines.append(f"| primary | {s['primary_available']} | {s['primary_sampled']} |")
    lines.append(f"| sample (tutorial/toy) | {s['sample_available']} | {s['sample_sampled']} |\n")
    lines.append("## Language distribution (deduped)\n")
    lines.append("| Language query | Files |")
    lines.append("|---|---|")
    for k, v in frame["language_distribution_deduped"].items():
        lines.append(f"| {k} | {v} |")
    lines.append("\n## Term distribution (deduped)\n")
    lines.append("| Term | Files |")
    lines.append("|---|---|")
    for k, v in frame["term_distribution_deduped"].items():
        lines.append(f"| {k} | {v} |")
    if frame["truncated_slices"]:
        lines.append("\n## Truncated slices (hit the 1000 cap irreducibly)\n")
        lines.append("These size-1 slices still exceeded the cap; a small tail of matches is unreachable via the API and is documented here for honesty.\n")
        lines.append("| Query | total_count |")
        lines.append("|---|---|")
        for t in frame["truncated_slices"]:
            lines.append(f"| `{t['query']}` | {t['total_count']} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
