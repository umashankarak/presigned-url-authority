"""Agreement scoring: machine-vs-human (validation set) and human-vs-human
(inter-rater kappa), with per-field Cohen's kappa.

Pure stdlib -- no scipy/sklearn needed.

Usage in the paper:
  * validation: run against the hidden validation set the human coded BLIND
    (before seeing proposals). This is the unbiased estimate of machine
    accuracy per field and belongs in the methods section.
  * kappa: run against the double-coded subsample (two humans, both blind).
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

FIELD_PAIRS = [
    ("JF1_post_key_tightness", "llm_JF1"),
    ("JF2_key_provenance", "llm_JF2_provenance"),
    ("JF2_authz_gate", "llm_JF2_authz"),
    ("JF3_credential_lifetime", "llm_JF3"),
    ("JF4_upload_size_exposure", "llm_JF4"),
    ("JF5_expiry_bucket", "llm_JF5_bucket"),
    ("JF5_expiry_appropriateness", "llm_JF5_appropriateness"),
]

HUMAN_FIELDS = [h for h, _ in FIELD_PAIRS]


def cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for two raters over categorical labels."""
    n = len(pairs)
    if n == 0:
        return None
    agree = sum(1 for a, b in pairs if a == b)
    po = agree / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    cats = set(ca) | set(cb)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def interpret(k: float | None) -> str:
    if k is None:
        return "n/a"
    if k < 0.0:
        return "worse than chance"
    if k < 0.20:
        return "slight"
    if k < 0.40:
        return "fair"
    if k < 0.60:
        return "moderate"
    if k < 0.80:
        return "substantial"
    return "almost perfect"


def _load(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def score_machine_vs_human(coded_csv: Path) -> dict:
    """Both human labels and llm_ proposals live in one file (the human coded
    their own columns; the llm_ columns came from the proposal pass)."""
    rows = _load(coded_csv)
    out = {}
    for human_col, llm_col in FIELD_PAIRS:
        pairs = [(r.get(human_col, "").strip(), r.get(llm_col, "").strip())
                 for r in rows
                 if r.get(human_col, "").strip() and r.get(llm_col, "").strip()]
        if not pairs:
            out[human_col] = {"n": 0, "note": "no rows with both labels present"}
            continue
        agree = sum(1 for a, b in pairs if a == b)
        k = cohens_kappa(pairs)
        disagreements = Counter(f"human={a} / machine={b}" for a, b in pairs if a != b)
        out[human_col] = {
            "n": len(pairs),
            "raw_agreement_pct": round(100 * agree / len(pairs), 1),
            "cohens_kappa": round(k, 3) if k is not None else None,
            "interpretation": interpret(k),
            "top_disagreements": dict(disagreements.most_common(5)),
        }
    return out


def score_human_vs_human(rater1_csv: Path, rater2_csv: Path) -> dict:
    """Join two independently-coded blind sheets on sha."""
    r1 = {r["sha"]: r for r in _load(rater1_csv)}
    r2 = {r["sha"]: r for r in _load(rater2_csv)}
    shared = set(r1) & set(r2)
    out = {"_rows_in_common": len(shared)}
    for field in HUMAN_FIELDS:
        pairs = [(r1[s].get(field, "").strip(), r2[s].get(field, "").strip())
                 for s in shared
                 if r1[s].get(field, "").strip() and r2[s].get(field, "").strip()]
        if not pairs:
            out[field] = {"n": 0, "note": "no rows with both labels present"}
            continue
        agree = sum(1 for a, b in pairs if a == b)
        k = cohens_kappa(pairs)
        out[field] = {
            "n": len(pairs),
            "raw_agreement_pct": round(100 * agree / len(pairs), 1),
            "cohens_kappa": round(k, 3) if k is not None else None,
            "interpretation": interpret(k),
            "top_disagreements": dict(
                Counter(f"r1={a} / r2={b}" for a, b in pairs if a != b).most_common(5)),
        }
    return out


def indeterminate_rates(coded_csv: Path) -> dict:
    """The per-field indeterminate rate -- a reportable result, not a failure."""
    rows = _load(coded_csv)
    out = {}
    for field in HUMAN_FIELDS:
        vals = [r.get(field, "").strip() for r in rows if r.get(field, "").strip()]
        if not vals:
            out[field] = {"n_coded": 0}
            continue
        ind = sum(1 for v in vals if v == "INDETERMINATE")
        out[field] = {"n_coded": len(vals), "indeterminate": ind,
                      "indeterminate_pct": round(100 * ind / len(vals), 1)}
    return out
