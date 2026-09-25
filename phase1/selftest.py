"""
selftest.py — offline validation of the Phase 1 pipeline.

Runs the entire pipeline against a MockGitHubClient backed by synthetic fixtures,
with no network or token. Verifies:

  1. Adaptive size partitioning splits a >cap term into <=cap slices, terminates,
     and covers the whole size range (no lost matches, no double counting).
  2. Stage 1 dedups hits by (repo, path, sha).
  3. MinHash/LSH clusters near-duplicate files and separates distinct ones.
  4. Stage 4 drops forks/archived and stratifies by stars.
  5. Blob fetch is sha-addressed (identical content stored once).
  6. Sampling is deterministic under a fixed seed and the sampling frame counts
     reconcile through the funnel.

Exit code 0 = all pass, 1 = a failure.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from typing import Dict, List

# ---------------------------------------------------------------------------
# Fixtures: a tiny synthetic "GitHub" world.
# ---------------------------------------------------------------------------

# Two blobs are byte-identical (same sha) across two repos -> should collapse by sha.
# Two more are near-duplicates (identifier/whitespace changes) -> collapse by MinHash.
# One is distinct -> survives.

_BLOB_A = '''
import boto3
s3 = boto3.client("s3")
def upload(key):
    return s3.generate_presigned_post(Bucket="b", Key=key, ExpiresIn=3600)
'''

# near-dup of A: renamed function + var, reflowed, comment added
_BLOB_A_NEAR = '''
import boto3
client = boto3.client("s3")
def make_upload(k):  # near duplicate of the canonical tutorial
    return client.generate_presigned_post(Bucket="b", Key=k, ExpiresIn=3600)
'''

# Genuinely unrelated file (different language/framework, no boto3 boilerplate).
# Kept distinct so the dedup test validates the mechanism rather than a
# near-worst-case where two files merely share import boilerplate. (The thin-
# separation behaviour on tiny snippets that DO share boilerplate is documented
# in the README as the reason Phase 2 dedups on the call-site window.)
_BLOB_DISTINCT = '''
package main
import "fmt"
func handler(w http.ResponseWriter, r *http.Request) {
    total := 0
    for i := 0; i < len(r.Header); i++ {
        total += i * 2
    }
    fmt.Fprintf(w, "processed %d headers", total)
}
'''


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


SHA_A = _sha(_BLOB_A)
SHA_ANEAR = _sha(_BLOB_A_NEAR)
SHA_DIST = _sha(_BLOB_DISTINCT)

# git blob store keyed by sha
_BLOBS: Dict[str, str] = {
    SHA_A: _BLOB_A,
    SHA_ANEAR: _BLOB_A_NEAR,
    SHA_DIST: _BLOB_DISTINCT,
}

# repo metadata
_REPOS = {
    "good/primary": {"stargazers_count": 120, "fork": False, "archived": False,
                     "pushed_at": "2026-06-01T00:00:00Z", "size": 10,
                     "license": {"spdx_id": "MIT"}, "owner": {"type": "User"},
                     "language": "Python"},
    "copy/fork": {"stargazers_count": 3, "fork": True, "archived": False,
                  "pushed_at": "2026-06-01T00:00:00Z", "size": 10,
                  "license": None, "owner": {"type": "User"}, "language": "Python"},
    "old/archived": {"stargazers_count": 50, "fork": False, "archived": True,
                     "pushed_at": "2019-01-01T00:00:00Z", "size": 10,
                     "license": None, "owner": {"type": "Org"}, "language": "Python"},
    "toy/lowstars": {"stargazers_count": 1, "fork": False, "archived": False,
                     "pushed_at": "2026-06-01T00:00:00Z", "size": 10,
                     "license": None, "owner": {"type": "User"}, "language": "Python"},
}

# search hits the mock will return for the one Python POST query.
# Note: SHA_A appears in BOTH good/primary and copy/fork (byte-identical copy).
_HITS = [
    {"repo": "good/primary",  "path": "app/upload.py",  "sha": SHA_A},
    {"repo": "copy/fork",     "path": "vendor/upload.py","sha": SHA_A},      # fork -> dropped in filter
    {"repo": "good/primary",  "path": "app/near.py",    "sha": SHA_ANEAR},  # near-dup of SHA_A
    {"repo": "good/primary",  "path": "app/download.py","sha": SHA_DIST},   # distinct
    {"repo": "old/archived",  "path": "x.py",           "sha": SHA_DIST},   # archived -> dropped
    {"repo": "toy/lowstars",  "path": "demo.py",        "sha": SHA_DIST},   # sample stratum
]


class MockGitHubClient:
    """Implements the three methods stages.py needs, plus adaptive-partition probing.

    For partitioning we model a *single* term whose matches are spread over the
    size range so the partitioner must bisect. total_count for a size window is
    the number of synthetic matches whose size falls in [lo,hi]. We place many
    synthetic files to force the >cap bisection path, but only the 6 real _HITS
    carry blob content / repo metadata (the rest are size-probe fodder for a
    DIFFERENT sentinel query used only in the partition unit test).
    """

    def __init__(self):
        self.search_calls = 0

    # ---- partition test uses this sentinel term with a known distribution ----
    def search_code(self, q: str, page: int = 1, per_page: int = 100, text_match=False):
        self.search_calls += 1

        if q.startswith('"__SENTINEL__"'):
            lo, hi = _parse_size(q)
            # 2500 matches spread uniformly over sizes 0..384000
            total = _count_uniform(lo, hi, n=2500, smin=0, smax=384000)
            if page == 1 and per_page == 1:
                return {"total_count": total, "incomplete_results": False, "items": []}
            # page of item stubs (content irrelevant for the partition test)
            items = _uniform_items(lo, hi, total, page, per_page)
            return {"total_count": total, "incomplete_results": False, "items": items}

        # the real pipeline query: return the 6 hits regardless of size window on
        # first probe, and page them out. Keep it simple: all 6 in size band.
        lo, hi = _parse_size(q)
        matches = _HITS  # pretend all fall in-band
        if page == 1 and per_page == 1:
            return {"total_count": len(matches), "incomplete_results": False, "items": []}
        start = (page - 1) * per_page
        chunk = matches[start:start + per_page]
        items = [{
            "repository": {"full_name": h["repo"]},
            "path": h["path"],
            "sha": h["sha"],
            "git_url": f'mock://blob/{h["sha"]}',
            "html_url": f'https://example/{h["repo"]}/{h["path"]}',
        } for h in chunk]
        return {"total_count": len(matches), "incomplete_results": False, "items": items}

    def get_repo(self, full_name: str):
        return dict(_REPOS[full_name], full_name=full_name)

    def get_blob_text(self, git_url: str, max_bytes: int = 400_000):
        sha = git_url.split("/")[-1]
        return _BLOBS.get(sha)


# ---- helpers for the synthetic uniform distribution (partition test) --------

def _parse_size(q: str):
    # q contains 'size:LO..HI'
    frag = [t for t in q.split() if t.startswith("size:")][0]
    lo, hi = frag[len("size:"):].split("..")
    return int(lo), int(hi)


def _count_uniform(lo, hi, n, smin, smax):
    span = smax - smin + 1
    # positions evenly spaced; count how many land in [lo,hi]
    # position of match i: smin + round(i*span/n)
    lo = max(lo, smin); hi = min(hi, smax)
    if hi < lo:
        return 0
    # inclusive count
    import math
    # match i in [0,n) has pos p_i = smin + (i*span)//n
    # count i with lo <= p_i <= hi
    def i_at(pos):
        # smallest i with p_i >= pos  => i >= (pos-smin)*n/span
        return math.ceil((pos - smin) * n / span)
    i_lo = max(0, i_at(lo))
    i_hi = min(n, i_at(hi + 1))
    return max(0, i_hi - i_lo)


def _uniform_items(lo, hi, total, page, per_page):
    start = (page - 1) * per_page
    k = max(0, min(per_page, total - start))
    items = []
    for j in range(k):
        idx = start + j
        items.append({
            "repository": {"full_name": f"u/repo{idx % 7}"},
            "path": f"f{idx}.py",
            "sha": f"sent{idx:06d}",
            "git_url": f"mock://blob/sent{idx:06d}",
            "html_url": "https://example/x",
        })
    return items


# ---------------------------------------------------------------------------
# The tests.
# ---------------------------------------------------------------------------

def _cfg(tmp: str) -> dict:
    return {
        "snapshot_label": "selftest",
        "output_dir": tmp,
        "seed": 42,
        "per_page": 100,
        "size_min": 0,
        "size_max": 384000,
        "cap": 1000,
        "max_file_bytes": 400000,
        "quality": {"min_stars": 5, "max_inactive_days": 1825,
                    "exclude_forks": True, "exclude_archived": True},
        "dedup": {"shingle_k": 3, "num_perm": 128, "bands": 32, "jaccard_threshold": 0.5},
        "target_sample_size": 400,
        "sample_stratum_size": 100,
        "queries": [{"term": "generate_presigned_post", "language": "Python"}],
    }


def test_partition(client) -> None:
    from partition import BaseQuery, partition_query
    base = BaseQuery(term="__SENTINEL__", language="Python")
    cache: Dict[str, int] = {}
    slices = list(partition_query(client.search_code, base, 0, 384000, cap=1000, probe_cache=cache))
    # every non-truncated slice must be <= cap
    for s in slices:
        assert s.total_count <= 1000 or s.truncated, f"slice over cap: {s}"
    # ranges cover [0,384000] with no gaps and no overlaps
    ranges = sorted((s.lo, s.hi) for s in slices)
    assert ranges[0][0] == 0, ranges[0]
    assert ranges[-1][1] == 384000, ranges[-1]
    for (l1, h1), (l2, h2) in zip(ranges, ranges[1:]):
        assert l2 == h1 + 1, f"gap/overlap between {(l1,h1)} and {(l2,h2)}"
    # union of counts should equal the true total (2500), proving no double count
    total = sum(s.total_count for s in slices)
    assert total == 2500, f"union total {total} != 2500"
    print(f"  [ok] partition: {len(slices)} slices, union total={total}, all <= cap")


def test_dedup_unit() -> None:
    from dedup import cluster
    docs = {
        "d_a": _BLOB_A,
        "d_a_near": _BLOB_A_NEAR,
        "d_dist": _BLOB_DISTINCT,
    }
    rep = cluster(docs, shingle_k=3, num_perm=128, bands=32, threshold=0.5, seed=42)
    assert rep["d_a"] == rep["d_a_near"], "near-duplicates were not clustered together"
    assert rep["d_dist"] != rep["d_a"], "distinct file was wrongly merged"
    n_clusters = len(set(rep.values()))
    assert n_clusters == 2, f"expected 2 clusters, got {n_clusters}"
    print("  [ok] dedup unit: near-dups merged, distinct separated (2 clusters)")


def test_pipeline(client, tmp: str) -> None:
    import stages
    cfg = _cfg(tmp)

    s1 = stages.stage_search(client, cfg, tmp)
    # sharded search writes hits/<shard>.jsonl; the single Python query shard holds
    # the 6 fixture hits. merge+subsample then build hits.jsonl for downstream stages.
    only_shard = list(s1["shards"])[0]
    assert s1["shards"][only_shard]["hits"] == 6, s1
    m = stages.merge_hits(cfg, tmp)
    assert m["unique_hits"] == 6, m
    # generous caps so subsample keeps all 6
    cfg["subsample"] = {"default_cap": 100, "caps": {}}
    sub = stages.subsample_hits(cfg, tmp)
    assert sub["kept"] == 6, sub
    print(f"  [ok] stage1 search+merge+subsample: {m['unique_hits']} unique hits -> hits.jsonl")

    s2 = stages.stage_enrich(client, cfg, tmp)
    assert s2["repos_cached"] == 4, s2
    print(f"  [ok] stage2 enrich: {s2['repos_cached']} repos cached")

    s3 = stages.stage_fetch(client, cfg, tmp)
    # 3 unique shas -> 3 blobs stored (sha-addressed, so SHA_A stored once)
    assert s3["unique_blobs"] == 3, s3
    assert s3["newly_fetched"] == 3, s3
    # verify sha-addressed store really has 3 files
    nfiles = sum(len(fs) for _, _, fs in os.walk(os.path.join(tmp, "blobs")))
    assert nfiles == 3, f"expected 3 stored blobs, found {nfiles}"
    print(f"  [ok] stage3 fetch: {s3['unique_blobs']} unique blobs (sha-addressed)")

    s4 = stages.stage_filter(cfg, tmp)
    # drops: copy/fork (fork), old/archived (archived) => 4 kept of 6
    assert s4["dropped"]["fork"] == 1, s4
    assert s4["dropped"]["archived"] == 1, s4
    assert s4["kept"] == 4, s4
    # strata: primary = good/primary rows (3), sample = toy/lowstars (1)
    assert s4["strata"]["primary"] == 3, s4
    assert s4["strata"]["sample"] == 1, s4
    print(f"  [ok] stage4 filter: kept={s4['kept']} dropped={s4['dropped']} strata={s4['strata']}")

    s5 = stages.stage_dedup(cfg, tmp)
    # kept rows: good/primary {SHA_A, SHA_ANEAR, SHA_DIST}, toy {SHA_DIST}
    # SHA_A and SHA_ANEAR are near-dups -> merge. The two SHA_DIST files are
    # byte-identical content -> Jaccard 1.0 -> merge. So 4 rows -> 2 clusters.
    assert s5["input"] == 4, s5
    assert s5["clusters"] == 2, s5
    assert s5["collapsed"] == 2, s5
    print(f"  [ok] stage5 dedup: {s5['input']} -> {s5['clusters']} clusters ({s5['collapsed']} collapsed)")

    s6 = stages.stage_sample(cfg, tmp)
    # everything fits under target, so sample == deduped rows
    assert s6["sampled_total"] == 2, s6
    # frame funnel reconciles
    frame = json.load(open(os.path.join(tmp, "sampling_frame.json")))
    c = frame["counts"]
    assert c["raw_unique_hits"] == 6
    assert c["after_filter"] == 4
    assert c["after_dedup_clusters"] == 2
    assert c["near_dup_collapsed"] == 2
    assert os.path.exists(os.path.join(tmp, "sampling_frame.md"))
    print(f"  [ok] stage6 sample+frame: sampled={s6['sampled_total']}, funnel reconciles")

    # determinism: re-run sample, identical output
    out1 = open(os.path.join(tmp, "sample.jsonl")).read()
    stages.stage_sample(cfg, tmp)
    out2 = open(os.path.join(tmp, "sample.jsonl")).read()
    assert out1 == out2, "sampling is not deterministic under fixed seed"
    print("  [ok] sampling determinism under fixed seed")


def test_resume(client, tmp: str) -> None:
    """Re-running search must not duplicate hits in the shard."""
    import stages
    cfg = _cfg(tmp)
    shard_dir = os.path.join(tmp, "hits")
    shard = [s for s in os.listdir(shard_dir) if s.endswith(".jsonl")][0]
    before = _count(os.path.join(shard_dir, shard))
    stages.stage_search(client, cfg, tmp)  # resume, should add nothing
    after = _count(os.path.join(shard_dir, shard))
    assert before == after, f"resume duplicated hits: {before} -> {after}"
    print(f"  [ok] resume: hits stable at {after} (no duplication)")


def test_sharding_language_merge_subsample(client) -> None:
    """Sharded search: --languages filter, per-shard files + resume, merge dedup,
    and subsample caps."""
    import stages
    tmp = tempfile.mkdtemp(prefix="phase1_shard_")
    try:
        cfg = _cfg(tmp)
        # two queries in two different languages
        cfg["queries"] = [
            {"term": "generate_presigned_post", "language": "Python"},
            {"term": "createPresignedPost", "language": "Go"},
        ]

        # (a) language filter: only Go -> only the Go shard is created
        r1 = stages.stage_search(client, cfg, tmp, languages=["Go"])
        shard_files = os.listdir(os.path.join(tmp, "hits"))
        assert any(s.startswith("createPresignedPost__Go") for s in shard_files), shard_files
        assert not any("Python" in s for s in shard_files), shard_files
        assert not any("__COMPLETE__" == k for k in [])  # noop guard
        go_shard = [s for s in shard_files if s.endswith(".jsonl")][0]
        go_hits = _count(os.path.join(tmp, "hits", go_shard))
        assert go_hits == 6, go_hits  # mock returns the 6 fixture hits
        assert r1["shards"][list(r1["shards"])[0]]["status"] == "complete", r1
        print(f"  [ok] language filter: only Go shard built ({go_hits} hits, complete)")

        # (b) alias filter: 'py' selects the Python query
        stages.stage_search(client, cfg, tmp, languages=["py"])
        shard_files = os.listdir(os.path.join(tmp, "hits"))
        assert any(s.startswith("generate_presigned_post__Python") for s in shard_files), shard_files
        print("  [ok] language alias: 'py' resolved to Python shard")

        # (c) resume: re-running search adds nothing (shards already COMPLETE)
        py_shard = [s for s in shard_files if s.startswith("generate_presigned_post") and s.endswith(".jsonl")][0]
        before = _count(os.path.join(tmp, "hits", py_shard))
        stages.stage_search(client, cfg, tmp)  # all languages, but both complete
        after = _count(os.path.join(tmp, "hits", py_shard))
        assert before == after, f"resume duplicated hits: {before} -> {after}"
        print(f"  [ok] per-shard resume: stable at {after} (COMPLETE shards skipped)")

        # (d) merge: both shards hold the SAME 6 (repo,path,sha) fixtures, so the
        # union dedups to 6 total.
        m = stages.merge_hits(cfg, tmp)
        assert m["unique_hits"] == 6, m
        assert os.path.exists(os.path.join(tmp, "hits.merged.jsonl"))
        print(f"  [ok] merge: 2 shards -> {m['unique_hits']} unique hits (deduped)")

        # (e) subsample caps: cap the term at 2, keep whole otherwise
        cfg["subsample"] = {"default_cap": 100, "caps": {"createPresignedPost": 2}}
        s = stages.subsample_hits(cfg, tmp)
        cp = [b for b in s["breakdown"] if b["term"] == "createPresignedPost"]
        # merged has only unique (repo,path,sha); createPresignedPost rows among them
        assert cp and cp[0]["kept"] <= 2, s["breakdown"]
        # determinism under fixed seed
        out1 = open(os.path.join(tmp, "hits.jsonl")).read()
        stages.subsample_hits(cfg, tmp)
        out2 = open(os.path.join(tmp, "hits.jsonl")).read()
        assert out1 == out2, "subsample not deterministic under fixed seed"
        print(f"  [ok] subsample caps + determinism (createPresignedPost kept {cp[0]['kept']})")

        # (f) status reflects completion
        st = stages.status_report(cfg, tmp)
        statuses = {r["status"] for r in st["shards"]}
        assert "complete" in statuses, st
        print("  [ok] status: shards reported complete")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _count(path: str) -> int:
    with open(path) as f:
        return sum(1 for ln in f if ln.strip())


def run() -> int:
    print("Phase 1 self-test (offline, mock GitHub)\n")
    client = MockGitHubClient()
    try:
        print("[partition]")
        test_partition(client)
        print("[dedup]")
        test_dedup_unit()
        tmp = tempfile.mkdtemp(prefix="phase1_selftest_")
        try:
            print("[pipeline]")
            test_pipeline(client, tmp)
            test_resume(client, tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        print("[sharding/merge/subsample]")
        test_sharding_language_merge_subsample(client)
    except AssertionError as e:
        print(f"\nFAIL: {e}")
        return 1
    except Exception as e:  # unexpected
        import traceback
        traceback.print_exc()
        print(f"\nERROR: {e}")
        return 1
    print("\nAll self-tests passed.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
