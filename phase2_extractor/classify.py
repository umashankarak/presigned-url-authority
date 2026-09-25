"""Classifies each manifest row's match type so the extractor can drop junk
before the judgment fields are ever coded.

Categories (first match wins, checked in this order):
  TYPE_DEF      - a .d.ts / type-stub file; the term is a type name, not a call
  TEST          - path looks like test/spec code
  IMPORT_ONLY   - term appears only in an import/using/require line
  ABSTRACT_DEF  - term appears only as an abstract method / interface signature
                  with no body (defines the shape, never calls anything)
  NO_SDK_CALL   - term string is present but there's no recognizable SDK
                  invocation nearby (e.g. a same-named local method, a fake/
                  mock implementation, a comment) - kept as NEEDS_REVIEW,
                  not silently dropped, since this one is easy to get wrong
  CALL          - looks like a genuine SDK invocation

Only CALL rows proceed to the coding sheet as primary rows; everything else
is written to the excluded/junk sheet with its reason, so the exclusion is
auditable rather than silent.
"""
from __future__ import annotations
import re

from . import patterns

TYPE_DEF = "TYPE_DEF"
TEST = "TEST"
IMPORT_ONLY = "IMPORT_ONLY"
ABSTRACT_DEF = "ABSTRACT_DEF"
NO_SDK_CALL = "NO_SDK_CALL"
CALL = "CALL"

_TEST_PATH_RE = re.compile(
    r"(^|/)(test|tests|spec|specs|__tests__|__mocks__|fixtures?)(/|$)"
    r"|[_.](test|spec)\.\w+$"
    r"|Test[s]?\.(java|cs)$"
    r"|test_.*\.py$",
    re.IGNORECASE,
)

_IMPORT_LINE_RE = re.compile(
    r"^\s*(import|from|using|require|const\s+\{[^}]*\}\s*=\s*require|use)\b",
    re.MULTILINE,
)

_ABSTRACT_SIGNAL_RE = re.compile(
    r"@abc\.abstractmethod|abstract\s+\w[\w<>\[\], ]*\s+\w+\s*\([^)]*\)\s*;"
    r"|interface\s+\w+.*\{",
    re.DOTALL,
)


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH_RE.search(path))


def is_type_def_path(path: str) -> bool:
    return path.endswith(".d.ts")


def _term_lines(term: str, text: str, ignore_case: bool = False):
    esc = re.escape(term)
    flags = re.IGNORECASE if ignore_case else 0
    return [ln for ln in text.splitlines() if re.search(esc, ln, flags)]


def _has_call_syntax(term: str, text: str, ignore_case: bool = False) -> bool:
    """True if the term is followed by '(' somewhere close (a call), or
    preceded by '.' + term + '(' (method call), allowing for whitespace/
    generics in between. \\w* after the term absorbs cases where the manifest
    term is a prefix of the actual identifier (e.g. manifest "GetPreSignedURL"
    matching source "GetPresignedUrlRequest(...)")."""
    esc = re.escape(term)
    flags = re.IGNORECASE if ignore_case else 0
    return bool(re.search(esc + r"\w*\s*(<[^>]*>)?\s*\(", text, flags))


def classify_match_type(term: str, path: str, full_text: str) -> tuple[str, str]:
    """Returns (match_type, reason)."""
    if is_type_def_path(path):
        return TYPE_DEF, "path ends with .d.ts"

    if is_test_path(path):
        return TEST, "path matches test/spec pattern"

    lines = _term_lines(term, full_text)
    case_exact = bool(lines)
    if not lines:
        # GitHub code search is case-insensitive; the manifest term's casing
        # doesn't always match the source (e.g. manifest "GetPreSignedURL"
        # vs. source "GetPresignedUrlRequest"). Fall back before giving up.
        lines = _term_lines(term, full_text, ignore_case=True)
        if not lines:
            return NO_SDK_CALL, "term not found verbatim in blob, case-insensitive included (encoding/rename?)"

    non_import_lines = [ln for ln in lines if not _IMPORT_LINE_RE.match(ln)]
    if not non_import_lines:
        # A package-name term (e.g. s3-request-presigner) legitimately lives
        # only in the import line while the imported symbol is called below.
        if patterns.has_call_evidence(term, full_text):
            return CALL, "term is import-only but term-specific call evidence found in body"
        return IMPORT_ONLY, "term appears only in import/require/using lines"

    has_call = _has_call_syntax(term, full_text) or (not case_exact and _has_call_syntax(term, full_text, ignore_case=True))

    if _ABSTRACT_SIGNAL_RE.search(full_text) and not has_call:
        return ABSTRACT_DEF, "term appears in an abstract method/interface signature only, no call found"

    if not has_call:
        if patterns.has_call_evidence(term, full_text):
            return CALL, "term-specific call evidence (class-name usage / paren-less call)"
        return NO_SDK_CALL, "term present but no call syntax ( term(...) ) found nearby"

    suffix = "" if case_exact else " [case-insensitive match: source casing differs from manifest term]"
    return CALL, "term used with call syntax outside import lines" + suffix
