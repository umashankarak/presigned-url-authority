"""
dedup.py — near-duplicate detection for the code corpus.

Copied tutorials and vendored snippets inflate prevalence counts, so we collapse
near-duplicate files before sampling. Byte-identical files are already collapsed
upstream by their git blob SHA; this module catches *near* duplicates (whitespace,
comment, or identifier changes) via MinHash + LSH.

Implementation is self-contained (no external MinHash dependency) so its behaviour
is fully testable offline. Hashing uses blake2b so results are stable regardless of
PYTHONHASHSEED.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections import defaultdict
from typing import Dict, List, Set

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|\"[^\"]*\"|'[^']*'|\S")
_PRIME = (1 << 61) - 1  # Mersenne prime for universal hashing

# Language keywords + the SDK API surface we care about are kept verbatim; every
# other identifier is canonicalised to a placeholder so that variable/function
# renames don't defeat near-dup detection on short snippets. This is deliberately
# broad: the goal is to collapse copied code, and keeping the *structure* plus the
# *API calls* while erasing local names is what near-dup code studies rely on.
_KEEP = {
    # generic control-flow / syntax keywords worth preserving as structure
    "def", "class", "return", "import", "from", "for", "while", "if", "else",
    "elif", "try", "except", "with", "as", "in", "is", "not", "and", "or",
    "function", "const", "let", "var", "new", "await", "async", "public",
    "private", "static", "void", "func", "package", "type", "struct",
    "true", "false", "none", "null", "nil",
    # the presigned-URL API surface (case-insensitive match handled below)
    "generate_presigned_url", "generate_presigned_post", "createpresignedpost",
    "getsignedurl", "getsignedurlpromise", "presignputobject", "presigngetobject",
    "presignpostobject", "s3presigner", "presignedurl", "presigned_post",
    "presigned_url", "createpresignedrequest", "getpresignedurl", "expiresin",
    "conditions", "bucket", "key", "params", "contentlengthrange",
    "content_length_range", "starts-with", "acl", "expiration",
}


def normalize_tokens(text: str) -> List[str]:
    """Structure-preserving tokenizer for near-dup detection.

    - keywords and the SDK API surface are kept (lowercased) verbatim,
    - string and numeric literals are replaced by STR / NUM,
    - all other identifiers are replaced by a placeholder ID,
    - punctuation is kept (it carries call structure).

    This canonicalises identifier renames while preserving the shape of the code
    and the API calls, which is what actually distinguishes a copied snippet from
    an unrelated one on short files.
    """
    out: List[str] = []
    for m in _TOKEN.findall(text):
        low = m.lower()
        if m and (m[0] == '"' or m[0] == "'"):
            out.append("STR")
        elif m.isdigit():
            out.append("NUM")
        elif re.match(r"[A-Za-z_]", m):
            out.append(low if low in _KEEP else "ID")
        else:
            out.append(m)  # punctuation / operators
    return out


def shingles(tokens: List[str], k: int) -> Set[str]:
    if not tokens:
        return set()
    if len(tokens) < k:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def _hash64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


class MinHasher:
    def __init__(self, num_perm: int = 128, seed: int = 1):
        rng = random.Random(seed)
        self.num_perm = num_perm
        self.a = [rng.randrange(1, _PRIME) for _ in range(num_perm)]
        self.b = [rng.randrange(0, _PRIME) for _ in range(num_perm)]

    def signature(self, shing: Set[str]) -> List[int]:
        if not shing:
            return [0] * self.num_perm
        hs = [_hash64(s) % _PRIME for s in shing]
        sig = []
        for a, b in zip(self.a, self.b):
            best = _PRIME
            for h in hs:
                v = (a * h + b) % _PRIME
                if v < best:
                    best = v
            sig.append(best)
        return sig


def estimate_jaccard(sig1: List[int], sig2: List[int]) -> float:
    if not sig1:
        return 0.0
    eq = sum(1 for x, y in zip(sig1, sig2) if x == y)
    return eq / len(sig1)


class _UnionFind:
    def __init__(self, ids: List[str]):
        self.parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry


def cluster(
    docs: Dict[str, str],
    shingle_k: int = 5,
    num_perm: int = 128,
    bands: int = 32,
    threshold: float = 0.8,
    seed: int = 1,
) -> Dict[str, str]:
    """Cluster near-duplicate documents.

    Returns a mapping {doc_id -> cluster_id}, where cluster_id is a deterministic
    representative (the lexicographically smallest doc_id in the cluster). Callers
    may re-pick a representative per cluster on other criteria (e.g. repo stars).
    """
    ids = sorted(docs.keys())
    if not ids:
        return {}
    if num_perm % bands != 0:
        raise ValueError(f"num_perm ({num_perm}) must be divisible by bands ({bands})")
    rows = num_perm // bands

    mh = MinHasher(num_perm=num_perm, seed=seed)
    sigs: Dict[str, List[int]] = {}
    for did in ids:
        toks = normalize_tokens(docs[did])
        sigs[did] = mh.signature(shingles(toks, shingle_k))

    # LSH: docs sharing any band bucket are candidate pairs.
    buckets: Dict[tuple, List[str]] = defaultdict(list)
    for did in ids:
        sig = sigs[did]
        for bi in range(bands):
            band = tuple(sig[bi * rows : (bi + 1) * rows])
            buckets[(bi, band)].append(did)

    uf = _UnionFind(ids)
    for members in buckets.values():
        if len(members) < 2:
            continue
        base = members[0]
        for other in members[1:]:
            # verify to guard against LSH collisions
            if estimate_jaccard(sigs[base], sigs[other]) >= threshold:
                uf.union(base, other)

    # cluster id = smallest member id (deterministic)
    groups: Dict[str, List[str]] = defaultdict(list)
    for did in ids:
        groups[uf.find(did)].append(did)
    rep_of: Dict[str, str] = {}
    for members in groups.values():
        rep = min(members)
        for m in members:
            rep_of[m] = rep
    return rep_of
