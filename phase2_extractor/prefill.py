"""Deterministic pre-fill: the subset of judgment-field decisions that are
genuinely mechanical, i.e. where the codebook's decision procedure reduces to
"read a literal that is visibly present in the window."

This is NOT an LLM. Every value here is produced by an explicit rule, and
every rule is auditable and reportable in the paper's methods section. The
point of separating this from the LLM proposals is that rule-derived labels
need only spot-checking, whereas LLM proposals need row-by-row verification.

Deliberately conservative: a rule fires only when the evidence is a literal
in the window. Anything requiring provenance tracing, intent judgment, or
cross-file resolution returns None and is left to the human (optionally with
an LLM proposal to check against).

What is NOT rule-decidable, and why:
  JF1 EXACT-via-fixed-Key : needs provenance tracing of the Key expression
  JF1 UNSCOPED_KEY        : needs "is this raw user input?" judgment
  JF2 (both parts)        : provenance + authz reasoning, wholly judgment
  JF3                     : requires locating the client construction, often
                            out of window; ROLE_OR_CHAIN vs INDETERMINATE is
                            a judgment about what "no credentials arg" means
  JF4 PUT side            : "is size enforced elsewhere" is judgment
  JF5 Part B              : appropriateness is explicitly subjective
"""
from __future__ import annotations

import re

# --- JF1: explicit $key condition with a literal operator+value ---
# Matches ['starts-with', '$key', 'literal'] / ["eq", "$key", "literal"] and
# the Python tuple/list equivalents, across quoting styles.
_KEY_COND_RE = re.compile(
    r"""[\[\(]\s*['"](eq|starts-with)['"]\s*,\s*['"]\$key['"]\s*,\s*(['"])(.*?)\2\s*[\]\)]""",
    re.IGNORECASE | re.DOTALL,
)

# A $key condition whose third element is NOT a literal (a variable, f-string,
# template literal, concatenation) -- detectable, but not resolvable here.
_KEY_COND_NONLITERAL_RE = re.compile(
    r"""[\[\(]\s*['"](eq|starts-with)['"]\s*,\s*['"]\$key['"]\s*,\s*(?!['"])([^\]\)]+)[\]\)]""",
    re.IGNORECASE,
)


def prefill_jf1(mechanism: str, window: str, referenced_snippet: str = "") -> tuple[str | None, str]:
    """Returns (code_or_None, rationale).

    Fires only for an explicit, literal $key condition -- the one JF1 branch
    that is a pure literal read. Absence of a $key condition does NOT fire a
    rule (that is the codebook's #1 trap: it could be EXACT via a fixed Key,
    or UNSCOPED_KEY via a raw user key, and only provenance tracing tells
    them apart).
    """
    if mechanism != "POST-policy":
        return None, ""

    text = (window or "") + "\n" + (referenced_snippet or "")

    m = _KEY_COND_RE.search(text)
    if m:
        op, _, value = m.group(1).lower(), m.group(2), m.group(3)
        if op == "eq":
            return "EXACT", f"explicit ['eq','$key','{value}'] condition (literal)"
        if value == "":
            return "EMPTY_PREFIX", "explicit ['starts-with','$key',''] with empty literal prefix"
        return "PREFIX", f"explicit ['starts-with','$key','{value}'] with non-empty literal prefix"

    if _KEY_COND_NONLITERAL_RE.search(text):
        # A $key condition exists but its value is dynamic -- the codebook's
        # "dynamic prefix" trap. Explicitly hand this to the human.
        return None, "NEEDS_HUMAN: $key condition present but value is non-literal (dynamic prefix trap)"

    return None, "no explicit $key condition; EXACT-vs-UNSCOPED requires Key provenance tracing"


def prefill_jf4(mechanism: str, content_length_range_present: str | bool,
                conditions_visible: str | bool = "True") -> tuple[str | None, str]:
    """POST size exposure is a literal presence check; GET is N_A by
    definition. PUT is left to the human (app-level enforcement is judgment)."""
    if mechanism == "GET-URL":
        return "N_A", "GET/download flow, no upload"
    if mechanism == "POST-policy":
        present = str(content_length_range_present).strip().upper() in ("TRUE", "1", "YES")
        if present:
            return "BOUNDED_POST", "content-length-range condition present in policy"
        vis = str(conditions_visible).strip().upper() in ("TRUE", "1", "YES")
        if not vis:
            # CRITICAL: no Conditions structure in the window means the policy
            # is unreadable, NOT that it lacks a size bound. Asserting
            # UNBOUNDED_POST here would inflate the headline finding.
            return None, ("NEEDS_HUMAN: no Conditions visible in window -- absence of "
                          "content-length-range is NOT evidence of no size bound")
        return "UNBOUNDED_POST", "Conditions visible in window, no content-length-range among them"
    return None, "PUT flow: requires judgment about app-level size enforcement"


# --- JF5 Part A: bucket the machine-extracted expiry seconds ---
def prefill_jf5_bucket(expiry_seconds) -> tuple[str | None, str]:
    """Pure arithmetic on a number the extractor already resolved. The human
    still verifies the UNIT (the codebook's units traps) -- this rule only
    saves the bucketing arithmetic, and fires only when a value exists."""
    if expiry_seconds in (None, "", "None"):
        return None, "no expiry resolved from window"
    try:
        s = int(float(expiry_seconds))
    except (TypeError, ValueError):
        return None, "expiry value not numeric"
    if s <= 900:
        return "SHORT", f"{s}s <= 15 min"
    if s <= 3600:
        return "MODERATE", f"{s}s in (15 min, 1 hr]"
    if s <= 86400:
        return "LONG", f"{s}s in (1 hr, 24 hr]"
    if s <= 604800:
        return "VERY_LONG", f"{s}s in (24 hr, 7 d]"
    return "INDETERMINATE", f"{s}s exceeds the 7-day SigV4 maximum; re-read units"


RULE_COLUMNS = {
    "JF1_post_key_tightness": "rule_JF1",
    "JF4_upload_size_exposure": "rule_JF4",
    "JF5_expiry_bucket": "rule_JF5A",
}


def prefill_row(row: dict) -> dict:
    """Returns {rule_col: code, rule_col + '_why': rationale} for whatever fires."""
    out = {}
    jf1, why1 = prefill_jf1(row.get("mechanism", ""), row.get("call_site_window", ""),
                            row.get("referenced_snippet", ""))
    jf4, why4 = prefill_jf4(row.get("mechanism", ""), row.get("content_length_range_present", ""),
                            row.get("conditions_visible", "True"))
    jf5, why5 = prefill_jf5_bucket(row.get("expiry_seconds"))
    out["rule_JF1"] = jf1 or ""
    out["rule_JF1_why"] = why1
    out["rule_JF4"] = jf4 or ""
    out["rule_JF4_why"] = why4
    out["rule_JF5A"] = jf5 or ""
    out["rule_JF5A_why"] = why5
    return out
