"""Auto-fills the mechanical columns listed in the codebook's quick-reference
table: raw expiry value + SDK, content-length-range present?, content-type
condition present?, ACL field + value, params inline-vs-referenced.

These are meant to be spot-checked by a human, not trusted blindly (per the
codebook: "Auto-filled (verify)"). Anything ambiguous is left blank/None with
a NEEDS_REVIEW-style flag rather than a guessed value.
"""
from __future__ import annotations
import re

_CLR_RE = re.compile(r"content-length-range", re.IGNORECASE)
_CONTENT_TYPE_COND_RE = re.compile(
    r"\$Content-Type|['\"]Content-Type['\"]|\bcontentType\b.*Conditions|Conditions.*\bcontentType\b",
    re.IGNORECASE,
)
_ACL_RE = re.compile(r"\bACL\b\s*[:=]\s*['\"]?([\w-]+)", re.IGNORECASE)

# Expiry patterns: (regex, unit-per-match) — unit None means "read from context, don't guess"
_EXPIRY_PATTERNS = [
    (re.compile(r"ExpiresIn\s*[:=]\s*(\d+)"), "seconds"),                      # boto3 / JS v3
    (re.compile(r"\bExpires\s*[:=]\s*(\d+)\b"), "seconds"),                    # JS v2 getSignedUrl/createPresignedPost, some Go
    (re.compile(r"expires_in\s*[:=]\s*(\d+)"), "seconds"),                     # Ruby
    (re.compile(r"Duration\.ofSeconds\((\d+)\)"), "seconds"),                  # Java v2
    (re.compile(r"Duration\.ofMinutes\((\d+)\)"), "minutes"),                  # Java v2
    (re.compile(r"Duration\.ofHours\((\d+)\)"), "hours"),                      # Java v2
    (re.compile(r"AddSeconds\((\d+)\)"), "seconds"),                           # C#
    (re.compile(r"AddMinutes\((\d+)\)"), "minutes"),                           # C#
    (re.compile(r"AddHours\((\d+)\)"), "hours"),                               # C#
    (re.compile(r"(\d+)\s*\*\s*time\.Minute"), "minutes"),                     # Go
    (re.compile(r"(\d+)\s*\*\s*time\.Second"), "seconds"),                     # Go
    (re.compile(r"(\d+)\s*\*\s*time\.Hour"), "hours"),                         # Go
    (re.compile(r"'\+(\d+)\s*minutes?'"), "minutes"),                          # PHP relative-time string
]

_UNIT_TO_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600}


def extract_expiry(window_text: str) -> dict:
    for pat, unit in _EXPIRY_PATTERNS:
        m = pat.search(window_text)
        if m:
            raw = int(m.group(1))
            seconds = raw * _UNIT_TO_SECONDS[unit]
            return {"expiry_raw_value": raw, "expiry_unit": unit, "expiry_seconds": seconds,
                     "expiry_source_text": m.group(0)}
    return {"expiry_raw_value": None, "expiry_unit": None, "expiry_seconds": None, "expiry_source_text": ""}


def extract_content_length_range(window_text: str) -> bool:
    return bool(_CLR_RE.search(window_text))


# Is a policy Conditions structure visible at all? Critical guard: if it is
# NOT, then content_length_range_present=False means "could not see", NOT
# "no size bound". Conflating those two inflates the UNBOUNDED_POST rate.
_CONDITIONS_VISIBLE_RE = re.compile(
    r"\bConditions\s*[:=]|\bconditions\s*[:=]|\bpolicy\s*[:=]|"
    r"key_starts_with|\bConditions\b\s*\[|content-length-range",
)


def conditions_visible(window_text: str) -> bool:
    return bool(_CONDITIONS_VISIBLE_RE.search(window_text))


def extract_content_type_condition(window_text: str) -> bool:
    return bool(_CONTENT_TYPE_COND_RE.search(window_text))


def extract_acl(window_text: str):
    m = _ACL_RE.search(window_text)
    return m.group(1) if m else None


def params_locality(referenced_var, referenced_resolved) -> str:
    """INLINE - literal object built at the call site (or no separate params
    var at all); REFERENCED_RESOLVED - a named var, found and pulled in from
    elsewhere in the file; REFERENCED_NONLOCAL - a named var whose definition
    could not be found in this file (needs the corpus-wide NEEDS_REVIEW pass)."""
    if referenced_var is None:
        return "INLINE"
    return "REFERENCED_RESOLVED" if referenced_resolved else "REFERENCED_NONLOCAL"
