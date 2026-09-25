"""Per-term SDK metadata and the regex signals used to disambiguate
GET-URL / PUT-URL / POST-policy generation mechanism from the call-site
window.

This is intentionally heuristic (regex over source text, not a real AST per
language) — that's a scope tradeoff for an 8-language corpus. Every field
this module can't resolve confidently is left AMBIGUOUS/INDETERMINATE and
flagged NEEDS_REVIEW rather than guessed, per the Phase 2 coding discipline
("a flagged indeterminate is a finding; a guess is fabricated data").
"""
from __future__ import annotations
import re

GET = "GET-URL"
PUT = "PUT-URL"
POST = "POST-policy"
OTHER = "other-SDK"
AMBIGUOUS = "AMBIGUOUS"

# term (as it appears in the Phase 1 manifest 'term' field) -> metadata
TERM_INFO = {
    "NewPresignClient":        {"language": "Go", "sdk": "aws-sdk-go-v2", "mechanism": AMBIGUOUS,
                                 "note": "constructs a presign client; method (Get/Put/Post) is usually called elsewhere"},
    "generatePresignedUrl":    {"language": "Java", "sdk": "aws-sdk-java (v1/v2)", "mechanism": AMBIGUOUS},
    "createPresignedPost":     {"language": "JS/TS", "sdk": "aws-sdk (v2) / @aws-sdk/s3-presigned-post (v3)", "mechanism": POST},
    "presigned_url":           {"language": "Ruby", "sdk": "aws-sdk-s3", "mechanism": AMBIGUOUS},
    "GetPreSignedURL":         {"language": "Go/C#", "sdk": "minio-go / AWS SDK", "mechanism": GET},
    "PresignGetObject":        {"language": "Go", "sdk": "aws-sdk-go-v2", "mechanism": GET},
    "S3Presigner":             {"language": "Java", "sdk": "aws-sdk-java-v2 presigner", "mechanism": AMBIGUOUS},
    "getSignedUrl":            {"language": "JS", "sdk": "aws-sdk (v2) or CloudFront signer", "mechanism": AMBIGUOUS,
                                 "note": "watch for CloudFront getSignedUrl contamination - different API, not S3"},
    "generate_presigned_url":  {"language": "Python", "sdk": "boto3", "mechanism": AMBIGUOUS},
    "generate_presigned_post": {"language": "Python", "sdk": "boto3", "mechanism": POST},
    "s3-request-presigner":    {"language": "JS", "sdk": "@aws-sdk/s3-request-presigner", "mechanism": AMBIGUOUS,
                                 "note": "package import; look for getSignedUrl(client, new GetObjectCommand|PutObjectCommand)"},
    "presigned_post":          {"language": "Ruby", "sdk": "aws-sdk-s3", "mechanism": POST},
    "PresignPutObject":        {"language": "Go", "sdk": "aws-sdk-go-v2", "mechanism": PUT},
    "createPresignedRequest":  {"language": "PHP", "sdk": "league/flysystem-aws-s3-v3 or aws-sdk-php", "mechanism": AMBIGUOUS},
    "presignPutObject":        {"language": "Go/other", "sdk": "various", "mechanism": PUT},
    "PostObjectV4":            {"language": "PHP", "sdk": "S3-compatible POST policy helper", "mechanism": POST},
    "GetPreSignedUrlRequest":  {"language": "C#", "sdk": "AWSSDK.S3 (v1-style request object)", "mechanism": GET,
                                 "note": "check .Verb for an explicit PUT override"},
}


def term_info(term: str) -> dict:
    return TERM_INFO.get(term, {"language": "unknown", "sdk": "unknown", "mechanism": AMBIGUOUS})


# --- disambiguation signals (searched within the call-site window) ---

_GET_SIGNALS = [
    r"\bget_object\b", r"\bGetObject", r"\bgetObject", r"['\"]getObject['\"]",
    r":get_object\b", r"HttpMethod\.GET", r"HttpVerb\.GET", r"presignGetObject",
    r"PresignGetObject", r"\.Verb\s*=\s*HttpVerb\.GET",
]
_PUT_SIGNALS = [
    r"\bput_object\b", r"\bPutObject", r"\bputObject", r"['\"]putObject['\"]",
    r":put_object\b", r"HttpMethod\.PUT", r"HttpVerb\.PUT", r"presignPutObject",
    r"PresignPutObject", r"\.Verb\s*=\s*HttpVerb\.PUT",
]
_POST_SIGNALS = [
    r"createPresignedPost", r"generate_presigned_post", r"presigned_post",
    r"PostObjectV4", r"\bConditions\s*[:=]\s*\[", r"content-length-range",
    r"\bFields\s*[:=]\s*\{",
]

_get_re = re.compile("|".join(_GET_SIGNALS))
_put_re = re.compile("|".join(_PUT_SIGNALS))
_post_re = re.compile("|".join(_POST_SIGNALS))


def disambiguate_mechanism(term: str, window_text: str) -> tuple[str, bool]:
    """Returns (mechanism, needs_review).

    mechanism is one of GET-URL / PUT-URL / POST-policy / other-SDK / INDETERMINATE.
    needs_review is True whenever the call is unresolved or multiple signals conflict.
    """
    info = term_info(term)
    base = info["mechanism"]
    if base in (GET, PUT, POST):
        return base, False

    # Ruby: presigned_url(:get, ...) / presigned_url :put, ... -- the method
    # symbol IS the mechanism; check before the generic signal scan.
    if term == "presigned_url":
        rg, rp = bool(_RUBY_PRESIGN_GET.search(window_text)), bool(_RUBY_PRESIGN_PUT.search(window_text))
        if rg and not rp:
            return GET, False
        if rp and not rg:
            return PUT, False

    has_get = bool(_get_re.search(window_text))
    has_put = bool(_put_re.search(window_text))
    has_post = bool(_post_re.search(window_text))
    hits = [m for m, present in [(GET, has_get), (PUT, has_put), (POST, has_post)] if present]

    if len(hits) == 1:
        return hits[0], False
    # zero or conflicting signals -> can't safely resolve
    return "INDETERMINATE", True


# --- per-term call evidence -------------------------------------------------
# When the generic "term followed by (" check fails, these recognize
# term-specific real-call shapes the generic check structurally cannot see:
# class-name usage (S3Presigner.create()), package terms whose call symbol
# differs from the term (s3-request-presigner -> getSignedUrl), and
# paren-less Ruby method calls.
CALL_EVIDENCE = {
    "S3Presigner": [
        r"S3Presigner\s*\.\s*(?:builder|create)\s*\(",
        r"\.presign(?:GetObject|PutObject|PostObject)\s*\(",
        r"\bS3Presigner\s+\w+\s*[=;]",
    ],
    "s3-request-presigner": [r"\bgetSignedUrl\s*\("],
    "presigned_url": [r"\.presigned_url\b"],
    "presigned_post": [r"\.presigned_post\b"],
}

_RUBY_PRESIGN_GET = re.compile(r"presigned_(?:url|request)\s*\(?\s*:get\b")
_RUBY_PRESIGN_PUT = re.compile(r"presigned_(?:url|request)\s*\(?\s*:put\b")


def has_call_evidence(term: str, full_text: str) -> bool:
    for pat in CALL_EVIDENCE.get(term, []):
        if re.search(pat, full_text):
            return True
    return False
