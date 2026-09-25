# Phase 1 Sampling Frame

- Snapshot label: `2026-08-22`
- RNG seed: `42`

## Corpus funnel

| Stage | Count |
|---|---|
| Raw unique hits (repo,path,sha) | 23994 |
| Unique repositories | 16567 |
| After quality filter | 23986 |
| After near-dup dedup (clusters) | 15832 |
| Near-duplicates collapsed | 8154 |
| **Sampled total** | **500** |

## Strata

| Stratum | Available | Sampled |
|---|---|---|
| primary | 2307 | 400 |
| sample (tutorial/toy) | 13525 | 100 |

## Language distribution (deduped)

| Language query | Files |
|---|---|
| Java | 3442 |
| Go | 2677 |
| TypeScript | 2607 |
| Python | 2110 |
| C# | 2041 |
| Ruby | 1377 |
| JavaScript | 1218 |
| PHP | 360 |

## Term distribution (deduped)

| Term | Files |
|---|---|
| createPresignedPost | 1952 |
| GetPreSignedURL | 1848 |
| generatePresignedUrl | 1791 |
| NewPresignClient | 1762 |
| S3Presigner | 1559 |
| getSignedUrl | 1445 |
| presigned_url | 1120 |
| generate_presigned_url | 1104 |
| generate_presigned_post | 1006 |
| PresignGetObject | 700 |
| s3-request-presigner | 428 |
| createPresignedRequest | 284 |
| presigned_post | 257 |
| PresignPutObject | 215 |
| GetPreSignedUrlRequest | 193 |
| presignPutObject | 92 |
| PostObjectV4 | 76 |

## Truncated slices (hit the 1000 cap irreducibly)

These size-1 slices still exceeded the cap; a small tail of matches is unreachable via the API and is documented here for honesty.

| Query | total_count |
|---|---|
| `"createPresignedRequest" language:PHP size:4254..4254` | 1268 |
