"""Targeted POST-policy re-sample.

The blind 500-file draw only contains ~60-90 POST-policy files, not enough
to estimate JF1 (empty-prefix rate) precisely. This draws an additional
seeded sample from the full corpus manifest (the ~23,986-file quality-
filtered set, or any broader manifest you point it at) restricted to
POST-policy terms, so JF1 has enough statistical power.

This does NOT re-fetch anything — it re-draws from a manifest you already
have (point --manifest at your full corpus manifest, not the 500-file
sample.jsonl).
"""
from __future__ import annotations
import json
import random
from pathlib import Path

POST_TERMS = {"createPresignedPost", "generate_presigned_post", "PostObjectV4", "presigned_post"}


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def draw_post_sample(full_corpus_manifest: Path, n: int, seed: int,
                      existing_sample_manifest: Path | None = None,
                      allocation: str = "proportional") -> tuple[list[dict], dict]:
    """Returns (sampled_rows, stats). Excludes shas already present in
    existing_sample_manifest (the primary 500-file blind draw) so the
    targeted draw adds new coverage rather than re-picking the same files."""
    corpus = load_jsonl(full_corpus_manifest)
    post_pool = [r for r in corpus if r.get("term") in POST_TERMS]

    excluded_shas = set()
    if existing_sample_manifest and Path(existing_sample_manifest).exists():
        existing = load_jsonl(existing_sample_manifest)
        excluded_shas = {r["sha"] for r in existing}

    eligible = [r for r in post_pool if r["sha"] not in excluded_shas]

    stats = {
        "corpus_size": len(corpus),
        "post_policy_pool_size": len(post_pool),
        "already_in_primary_sample": len(post_pool) - len(eligible),
        "eligible_for_draw": len(eligible),
    }

    if n >= len(eligible):
        stats["note"] = "requested n >= eligible pool; returning full eligible pool"
        return eligible, stats

    rng = random.Random(seed)
    by_lang: dict[str, list[dict]] = {}
    for r in eligible:
        by_lang.setdefault(r.get("language_query", "unknown"), []).append(r)
    for bucket in by_lang.values():
        rng.shuffle(bucket)

    langs = sorted(by_lang.keys())
    stats["eligible_pool_by_language"] = {l: len(by_lang[l]) for l in langs}

    if allocation == "proportional":
        # Mirror the corpus composition so the pooled JF1 rate is directly
        # interpretable as a corpus-level estimate. Largest-remainder method.
        total = len(eligible)
        exact = {l: n * len(by_lang[l]) / total for l in langs}
        alloc = {l: int(exact[l]) for l in langs}
        remainder = n - sum(alloc.values())
        for l in sorted(langs, key=lambda x: exact[x] - int(exact[x]), reverse=True):
            if remainder <= 0:
                break
            if alloc[l] < len(by_lang[l]):
                alloc[l] += 1
                remainder -= 1
        sampled = []
        for l in langs:
            sampled.extend(by_lang[l][:min(alloc[l], len(by_lang[l]))])
    elif allocation == "equal":
        # Equal-n per language. Only defensible if you report per-language
        # rates and weight before pooling -- an unweighted pooled rate from
        # this design over-represents small-population languages.
        sampled = []
        idx = {l: 0 for l in langs}
        while len(sampled) < n:
            progressed = False
            for l in langs:
                if len(sampled) >= n:
                    break
                if idx[l] < len(by_lang[l]):
                    sampled.append(by_lang[l][idx[l]])
                    idx[l] += 1
                    progressed = True
            if not progressed:
                break
    else:
        raise ValueError("allocation must be 'proportional' or 'equal'")

    stats["allocation"] = allocation
    stats["drawn"] = len(sampled)
    stats["by_language"] = {l: sum(1 for r in sampled if r.get("language_query") == l) for l in langs}
    tot_pool = len(eligible) or 1
    tot_draw = len(sampled) or 1
    stats["share_check_pool_vs_draw_pct"] = {
        l: [round(100 * len(by_lang[l]) / tot_pool, 1),
            round(100 * stats["by_language"].get(l, 0) / tot_draw, 1)]
        for l in langs
    }
    return sampled, stats


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
