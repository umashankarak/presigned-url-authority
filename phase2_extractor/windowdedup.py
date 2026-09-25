"""Call-site window near-duplicate detection.

Phase 1 dedup is file-level and weak on small snippets (per the handoff doc:
"file-level dedup is weak on tiny snippets; Phase 2 should re-dedup on the
extracted call-site window"). This clusters rows whose NORMALIZED call-site
windows are near-identical, so the same tutorial snippet copied across repos
doesn't inflate a prevalence rate.

Normalization strips the things that vary between copies without changing the
scoping decision: whitespace, string/number literals, comments, and common
variable-name noise. Then near-duplicates are found by exact match on a
normalized hash (fast, conservative) plus optional token-Jaccard for fuzzy
matches.

Output adds two columns:
  window_cluster_id : integer; rows sharing an id are near-duplicates
  window_is_cluster_rep : True for one representative per cluster

This does NOT delete rows -- you still code them all -- but analysis can then
report both the raw rate and the dedup-weighted rate (one vote per cluster),
which is the honest pair of numbers for a copy-paste-heavy corpus.
"""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

_COMMENT_RE = re.compile(r"//.*?$|#.*?$|/\*.*?\*/", re.MULTILINE | re.DOTALL)
_STRING_RE = re.compile(r"""(['"]).*?\1""", re.DOTALL)
_NUMBER_RE = re.compile(r"\b\d[\d_]*\b")
_WS_RE = re.compile(r"\s+")


def normalize_window(text: str) -> str:
    t = _COMMENT_RE.sub(" ", text)
    t = _STRING_RE.sub("STR", t)
    t = _NUMBER_RE.sub("N", t)
    t = _WS_RE.sub(" ", t)
    return t.strip().lower()


def _hash(norm: str) -> str:
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _tokens(norm: str) -> set[str]:
    return set(re.findall(r"[a-z_]+|STR|N", norm))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def dedup(in_csv: Path, out_csv: Path, jaccard_threshold: float = 0.92) -> dict:
    rows = list(csv.DictReader(open(in_csv, encoding="utf-8")))
    cols = list(rows[0].keys()) if rows else []
    for c in ("window_cluster_id", "window_is_cluster_rep"):
        if c not in cols:
            cols.append(c)

    norms = [normalize_window(r.get("call_site_window", "")) for r in rows]
    toks = [_tokens(n) for n in norms]

    # exact-normalized clustering first
    cluster_of = [-1] * len(rows)
    by_hash: dict[str, int] = {}
    next_id = 0
    for i, n in enumerate(norms):
        h = _hash(n)
        if h in by_hash:
            cluster_of[i] = by_hash[h]
        else:
            by_hash[h] = next_id
            cluster_of[i] = next_id
            next_id += 1

    # fuzzy merge: link exact-clusters whose reps are near-identical
    reps = {}
    for i, cid in enumerate(cluster_of):
        reps.setdefault(cid, i)
    rep_ids = sorted(reps)
    parent = {c: c for c in rep_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a_idx in range(len(rep_ids)):
        for b_idx in range(a_idx + 1, len(rep_ids)):
            ca, cb = rep_ids[a_idx], rep_ids[b_idx]
            if _jaccard(toks[reps[ca]], toks[reps[cb]]) >= jaccard_threshold:
                parent[find(ca)] = find(cb)

    final = {}
    remap = {}
    nid = 0
    for i in range(len(rows)):
        root = find(cluster_of[i])
        if root not in remap:
            remap[root] = nid
            nid += 1
        final[i] = remap[root]

    seen_rep = set()
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(rows):
            cid = final[i]
            r["window_cluster_id"] = cid
            r["window_is_cluster_rep"] = cid not in seen_rep
            seen_rep.add(cid)
            w.writerow(r)

    n_clusters = len(set(final.values()))
    sizes: dict[int, int] = {}
    for c in final.values():
        sizes[c] = sizes.get(c, 0) + 1
    dups = sum(1 for c in sizes.values() if c > 1)
    return {
        "rows": len(rows),
        "clusters": n_clusters,
        "multi_row_clusters": dups,
        "largest_cluster": max(sizes.values()) if sizes else 0,
        "rows_that_are_duplicates": len(rows) - n_clusters,
        "dedup_weighted_n": n_clusters,
    }
