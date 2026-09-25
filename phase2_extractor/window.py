"""Extracts the ~15-line call-site window around the matched term, and makes
a best-effort attempt to pull in a referenced params/conditions variable
defined elsewhere in the same file (e.g. `s3.createPresignedPost(params, ...)`
where `params` is built 25 lines up).

If the referenced variable can't be found in the same file, the window is
left as-is and the row is flagged NEEDS_REVIEW / PARAMS_REFERENCED_NONLOCAL —
per the design doc, this is exactly the case Phase 2 should not guess on.
"""
from __future__ import annotations
import re

WINDOW_LINES = 15  # lines of context on each side of the match, per the design doc's "~15-line window"

# Identifier assigned to an object/array literal: `params = { ... }`, `params := map[...]{...}`,
# `const params = {...}`, `$params = [...]`, `params = [...]` etc. Matched loosely across languages.
_ASSIGN_LITERAL_RE_TMPL = r"\b{name}\b\s*[:=]=?\s*(\{{|\[)"


def find_term_line_indices(term: str, lines: list[str]) -> list[int]:
    esc = re.escape(term)
    pat = re.compile(esc)
    idxs = [i for i, ln in enumerate(lines) if pat.search(ln)]
    if idxs:
        return idxs
    # case-insensitive fallback, mirrors classify.classify_match_type
    pat_ci = re.compile(esc, re.IGNORECASE)
    return [i for i, ln in enumerate(lines) if pat_ci.search(ln)]


def extract_window(full_text: str, term: str, window_lines: int = WINDOW_LINES) -> dict:
    """Returns dict with: window_text, match_line_no (1-indexed, first match),
    all_match_line_nos, referenced_var (name or None), referenced_resolved (bool),
    referenced_snippet (str or '')."""
    lines = full_text.splitlines()
    idxs = find_term_line_indices(term, lines)
    if not idxs:
        return {
            "window_text": "", "match_line_no": None, "all_match_line_nos": [],
            "referenced_var": None, "referenced_resolved": False, "referenced_snippet": "",
        }

    # Use the first match as the anchor; if there are several (e.g. import + call),
    # classify.py should already have routed pure-import files away from here, but
    # we still anchor on the first match that isn't inside an import line when possible.
    anchor = idxs[0]
    for i in idxs:
        line = lines[i]
        if not re.match(r"^\s*(import|from|using|require|use)\b", line):
            anchor = i
            break

    start = max(0, anchor - window_lines)
    end = min(len(lines), anchor + window_lines + 1)
    window_text = "\n".join(lines[start:end])

    ref = _detect_referenced_param(window_text, lines, start, end)

    return {
        "window_text": window_text,
        "match_line_no": anchor + 1,
        "all_match_line_nos": [i + 1 for i in idxs],
        **ref,
    }


def _detect_referenced_param(window_text: str, all_lines: list[str], win_start: int, win_end: int) -> dict:
    """Looks for a call argument that is a bare identifier (e.g. `params`,
    `conditions`, `postParams`) rather than an inline literal, then tries to
    resolve that identifier's definition within the full file."""
    # Common call shapes: fn(identifier, ...) or fn(identifier) where identifier
    # is not itself an inline '{' or '[' opener.
    m = re.search(
        r"(?:createPresignedPost|generate_presigned_post|PostObjectV4|presigned_post|"
        r"generatePresignedUrl|generate_presigned_url|createPresignedRequest)\s*\(\s*"
        r"([A-Za-z_][A-Za-z0-9_.]*)\s*[,)]",
        window_text,
    )
    if not m:
        return {"referenced_var": None, "referenced_resolved": False, "referenced_snippet": ""}

    candidate = m.group(1)
    # Skip obvious non-variables (SDK client objects used as receivers, etc. are
    # caught upstream by the '.' in method calls like s3.createPresignedPost).
    if candidate in ("this", "self", "client", "s3", "s3Client"):
        return {"referenced_var": None, "referenced_resolved": False, "referenced_snippet": ""}

    # Is the identifier itself assigned to a literal INSIDE the window already?
    # (then it's effectively inline/local, not a nonlocal reference worth flagging)
    inline_pat = re.compile(_ASSIGN_LITERAL_RE_TMPL.format(name=re.escape(candidate)))
    if inline_pat.search(window_text):
        return {"referenced_var": candidate, "referenced_resolved": True, "referenced_snippet": "(defined inline within window)"}

    # Search the rest of the file for the assignment.
    full_text = "\n".join(all_lines)
    def_pat = re.compile(_ASSIGN_LITERAL_RE_TMPL.format(name=re.escape(candidate)))
    dm = def_pat.search(full_text)
    if not dm:
        return {"referenced_var": candidate, "referenced_resolved": False, "referenced_snippet": ""}

    # Pull a small snippet around that definition too, so a human reviewer
    # doesn't have to re-open the file.
    def_line_no = full_text[: dm.start()].count("\n")
    snippet_lines = all_lines[max(0, def_line_no - 1): def_line_no + 12]
    return {
        "referenced_var": candidate,
        "referenced_resolved": True,
        "referenced_snippet": "\n".join(snippet_lines),
    }
