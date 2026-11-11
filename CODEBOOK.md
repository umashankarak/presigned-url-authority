# Codebook

This codebook defines every column and code in the coded samples in
`phase2/data/`. Each eligible generation site was coded from a window of
source lines around the presigning call (±15 lines in the blind sample, ±40 in
the targeted POST sample). Every judgment dimension has an `INDETERMINATE`
code, used whenever the value is set outside the window or cannot be resolved
from it.

The worked examples below are short synthetic snippets written to illustrate
each code. They are not taken from the corpus.

## Data columns

| Column | Meaning |
| --- | --- |
| `row_id` | Row identifier (`B…` blind sample, `T…` targeted POST sample). Matches the row identifiers in the reviewers' supplementary files |
| `blob_sha` | Git blob SHA of the source file, as returned by GitHub code search. Identifies the exact file version |
| `term` | The search term that matched the file (see the paper, Table 2) |
| `language_query` | Language filter of the search query |
| `stratum` | `primary`: repository with at least 5 stars and a push within 1,825 days. `sample`: all other repositories (the paper's *low-signal* stratum) |
| `match_type` | Extractor classification of the match (for example, a call site) |
| `mechanism` | Extractor's mechanism label: `GET-URL`, `PUT-URL`, `POST-policy`, or `INDETERMINATE` |
| `content_length_range_present` | Extractor flag: a `content-length-range` condition appears in the window |
| `conditions_visible` | Targeted sample only. Extractor flag: a POST condition list appears in the window |
| `ELIGIBLE`, `INELIGIBLE_REASON` | Eligibility screen (below) |
| `s3_compatible` | `TRUE` if the site targets an S3-compatible service rather than AWS |
| `MULTI_SITE` | `TRUE` if the file contains more than one presigning call; the first matching call was coded |
| `JF1_…` to `JF5_…` | Judgment dimensions (below). Blank means not applicable, or not coded in that sample |

## Eligibility (`ELIGIBLE`, `INELIGIBLE_REASON`)

A site is `ELIGIBLE = TRUE` if it generates a presigned URL or POST policy for
Amazon S3 or an S3-compatible service (MinIO, Cloudflare R2, DigitalOcean
Spaces, Wasabi, LocalStack, and similar).

| `INELIGIBLE_REASON` | Rule |
| --- | --- |
| `SDK_SOURCE` | SDK or library source that defines a presigning function, an interface or abstract declaration, or construction of a presigning client without a presigning call |
| `OTHER_CLOUD` | A request to a non-S3 storage service (Google Cloud Storage, Alibaba Cloud OSS, Tencent COS, Supabase Storage, and similar) |
| `OTHER` | A presigned AWS Security Token Service request, CloudFront signing, a local stub, commented-out code, or another non-generation site |
| `FAKE_MOCK` | A test double or stub that returns a fixed URL |
| `NON_AWS_SAMENAME` | A function with the same name that does not use an AWS or S3-compatible SDK |

```go
// Ineligible (SDK_SOURCE): an interface declaration, not a presigning call
type Storage interface {
    PresignGetObject(ctx context.Context, key string) (string, error)
}
```

## JF1 — Key scope (`JF1_post_key_tightness`), POST policies only

| Code | Rule |
| --- | --- |
| `EXACT` | An exact-match condition on `$key`, or a key fixed at signing time (including a key that embeds user input) |
| `PREFIX` | A `starts-with` condition on `$key` with a non-empty value |
| `EMPTY_PREFIX` | A `starts-with` condition on `$key` with an empty value |
| `UNSCOPED_KEY` | No condition restricts the key, and the client supplies it at upload time |

```python
# EXACT: a literal key; boto3 adds an exact-match condition on $key itself
s3.generate_presigned_post(Bucket=b, Key=f"avatars/{user_id}.png")

# PREFIX: the client picks the file name, but only under this prefix
s3.generate_presigned_post(Bucket=b, Key="uploads/" + user_id + "/${filename}")

# EMPTY_PREFIX: any key in the bucket
s3.generate_presigned_post(Bucket=b, Key="${filename}",
                           Conditions=[["starts-with", "$key", ""]])
```

Note that a missing `$key` condition is not `UNSCOPED_KEY` when the key is
fixed at signing time: most SDKs bind the key into the policy automatically.

## JF2 — Key origin (`JF2_key_provenance`)

| Code | Rule |
| --- | --- |
| `SERVER` | Random identifier, timestamp, database identifier, or authenticated-session value, with no user-supplied part |
| `USER_SANITIZED` | A user-supplied part passes through validation or character filtering applied to the key |
| `USER_RAW` | A user-supplied part enters the key without validation |

```javascript
const key = `uploads/${crypto.randomUUID()}`;               // SERVER
const key = `uploads/${sanitize(req.body.fileName)}`;        // USER_SANITIZED
const key = req.query.file;                                  // USER_RAW
```

## JF2 — Authorization (`JF2_authz_gate`)

| Code | Rule |
| --- | --- |
| `AUTHZ_PRESENT` | A check ties the request to the authenticated caller and the requested object, or the key prefix is derived from the caller's authenticated identity |
| `AUTHN_ONLY` | The handler checks that the caller is logged in but not that the caller may access the object |
| `NONE` | The visible code issues the URL with no check before generation and references no authentication or authorization machinery (decorator, middleware, guard). Machinery that is referenced but not shown is `INDETERMINATE` |

```python
@login_required                       # AUTHN_ONLY: logged in, any document
def download(request, doc_id):
    doc = Document.objects.get(id=doc_id)
    return presign_get(doc.key)

@login_required                       # AUTHZ_PRESENT: must own the document
def download(request, doc_id):
    doc = Document.objects.get(id=doc_id, owner=request.user)
    return presign_get(doc.key)
```

## JF3 — Credential type (`JF3_credential_lifetime`)

| Code | Rule |
| --- | --- |
| `LONG_LIVED_IAM` | Explicit access key and secret key, including values read from environment variables |
| `STS_TEMPORARY` | Assumed-role or session credentials |
| `ROLE_OR_CHAIN` | Client created without explicit credentials (default provider chain) |

```python
boto3.client("s3", aws_access_key_id=os.environ["KEY"],
             aws_secret_access_key=os.environ["SECRET"])      # LONG_LIVED_IAM
boto3.client("s3")                                             # ROLE_OR_CHAIN
```

## JF4 — Size bound (`JF4_upload_size_exposure`)

| Code | Rule |
| --- | --- |
| `BOUNDED_POST` | POST policy with a `content-length-range` condition |
| `UNBOUNDED_POST` | POST policy with visible conditions and no `content-length-range` |
| `APP_BOUNDED_PUT` | PUT URL generated with the expected content length signed into it, so S3 rejects a body of any other length |
| `UNBOUNDED_PUT` | PUT upload URL whose content length is not signed |
| `N_A` | The coded call generates a download URL |

```python
# BOUNDED_POST
s3.generate_presigned_post(Bucket=b, Key=k,
    Conditions=[["content-length-range", 1, 10 * 1024 * 1024]])

# UNBOUNDED_POST: conditions visible, no size range
s3.generate_presigned_post(Bucket=b, Key=k,
    Conditions=[["starts-with", "$Content-Type", "image/"]])

# UNBOUNDED_PUT: a PUT URL carries no size limit
s3.generate_presigned_url("put_object", Params={"Bucket": b, "Key": k})
```

```ruby
# APP_BOUNDED_PUT: content length signed (whitelist_headers puts it in the signature)
obj.presigned_url(:put, content_length: size, whitelist_headers: ["content-length"])
```

```go
// APP_BOUNDED_PUT: setting ContentLength adds content-length to the signed headers
presigner.PresignPutObject(ctx, &s3.PutObjectInput{
    Bucket: aws.String(b), Key: aws.String(k), ContentLength: aws.Int64(size)})
```

A server-side check of a size the client declares, made before signing, does
not limit what the URL holder uploads. Such a site is coded `UNBOUNDED_PUT`
when the signing call is visible and does not sign the content length, and
`INDETERMINATE` when the signing parameters are not visible.

## JF5 — Expiry (`JF5_expiry_bucket`, `JF5_expiry_appropriateness`)

| Code | Rule |
| --- | --- |
| `SHORT` / `MODERATE` / `LONG` / `VERY_LONG` | Up to 15 min / over 15 min to 1 h / over 1 h to 24 h / over 24 h to 7 days. Units follow the SDK, and duration arithmetic is evaluated |
| `DEFAULT_UNSET` | No expiry passed, so the SDK default applies |
| `APPROPRIATE` | The expiry fits the apparent use |
| `OVER_LONG` | The expiry clearly exceeds the apparent use. Uncertain cases and generic utilities are `INDETERMINATE` |

```ruby
obj.presigned_url(:put, expires_in: 5.minutes.to_i)      # SHORT (300 s)
```
```javascript
await getSignedUrl(client, cmd);                         // DEFAULT_UNSET (900 s default)
```

## General rules

- Where a file contains several presigning calls, the first matching call is coded (`MULTI_SITE = TRUE`).
- A POST key fixed at signing time is coded `EXACT` even when it contains user input; the user-supplied part is captured under key origin.
- Presigned Security Token Service requests are ineligible.
- The targeted POST sample was coded for key scope and size bound only.
