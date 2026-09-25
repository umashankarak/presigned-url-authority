# Scoped Keys, Unbounded Uploads

Code, codebook, and de-identified data for the paper **"Scoped Keys, Unbounded
Uploads: An Empirical Study of Amazon S3 Presigned URL Authority in
Open-Source Code"** (Umashankara Kalaiah, 2026).

The study coded 621 presigned-URL generation sites from public GitHub code in
eight languages and reproduced each authority pattern on an author-owned S3
bucket. With this repository you can:

1. recompute every number in the paper's Results section (two commands, no AWS account needed),
2. regenerate the two figures,
3. rerun the SDK checks cited in the Background section (no AWS account needed), and
4. rerun the ground-truth validation on your own AWS account.

## Repository layout

```
.
├── README.md
├── CODEBOOK.md                  # every data column and code, with worked examples
├── LICENSE                      # MIT (code); data and codebook are CC BY 4.0
├── requirements.txt
├── .gitignore                   # blocks raw corpus files and identified data
├── phase1/                      # corpus construction pipeline (GitHub code search)
│   ├── *.py                     # pipeline modules; entry point run.py
│   ├── config.yaml              # frozen sampling frame: seed, caps, strata thresholds
│   └── reports/
│       ├── sampling_frame.md    # corpus funnel and strata counts
│       └── subsample_report.json
├── phase2_extractor/            # call-site extraction tool (Python package)
├── phase2/
│   ├── analyze_phase2.py        # computes all Results numbers and intervals
│   ├── check_paper_numbers.py   # confirms the output matches the paper
│   ├── deidentify.py            # how the public data files were produced
│   ├── data/
│   │   ├── blind_sample_coded.xlsx    # 383 coded sites (blind sample)
│   │   └── targeted_post_coded.xlsx   # 238 coded sites (targeted POST sample)
│   └── results/
│       └── phase2_results.txt   # analysis output behind the paper's numbers
├── phase3/
│   ├── phase3_validation.py     # ground-truth tests T1–T5 on an owned bucket
│   ├── phase3_evidence.json     # results of the run reported in the paper
│   ├── t1_diagnose.py           # diagnostic that exposed the SDK-added key condition
│   ├── verify_sdk.py            # boto3 key-condition and default-expiry checks
│   └── check_js_default.mjs     # JavaScript v3 presigner default-expiry check
└── figures/
    ├── make_figure1.py
    ├── make_figure2.py
    ├── figure1_pipeline.pdf
    └── figure2_overgrant.pdf
```

## 1. Reproduce the Results (no AWS account needed)

Requires Python 3.9 or later. From the repository root:

```bash
pip install -r requirements.txt
cd phase2
python3 analyze_phase2.py data/blind_sample_coded.xlsx data/targeted_post_coded.xlsx > results/phase2_results.txt
python3 check_paper_numbers.py results/phase2_results.txt
```

The last command checks 35 numbers against the paper and should end with
`35/35 paper numbers confirmed`.

Analysis rules, as stated in the paper:

- Rates are computed over *determinable* sites. `INDETERMINATE` codes are excluded from denominators and reported separately. `N_A` (a download site under size bound) is excluded as well.
- Proportions carry 95% Wilson score intervals.
- Key scope and size bound pool the POST sites of both samples. All other rates use the blind sample only, because the targeted sample over-represents POST policies by design.

The data files are described column by column in `CODEBOOK.md`.

## 2. Regenerate the figures

```bash
cd figures
python3 make_figure1.py    # Figure 1: study pipeline
python3 make_figure2.py    # Figure 2: over-grant rates with 95% intervals
```

## 3. Check the SDK behaviors cited in the paper (no AWS account needed)

Generating a presigned URL or POST policy is a local computation, so these
checks send nothing to AWS. The SDKs only require credentials to be present;
AWS's documented example credentials work:

```bash
cd phase3
export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
python3 verify_sdk.py
```

Expected output:

- `Key = 'uploads/photo.png'` → an exact condition `{'key': 'uploads/photo.png'}`
- `Key = 'uploads/${filename}'` → `['starts-with', '$key', 'uploads/']`
- `Key = '${filename}'` → `['starts-with', '$key', '']`
- default `X-Amz-Expires` of `['3600']`, and a POST policy expiring one hour after the current time

For the JavaScript v3 presigner (requires Node.js; expected: `X-Amz-Expires: 900`),
using the same environment variables:

```bash
npm install @aws-sdk/client-s3 @aws-sdk/s3-request-presigner
node check_js_default.mjs
```

The paper reports these results for boto3 1.42.97 and
`@aws-sdk/s3-request-presigner` 3.1140.0.

## 4. Rerun the ground-truth validation (your own AWS account)

**Run this only in an AWS account you own.** It needs real credentials allowed
to create and delete an S3 bucket (unset the example credentials from step 3
first). The script creates one uniquely named bucket, runs five tests against
it, and deletes the bucket and all objects when it finishes, even if a test
fails. It contacts no other bucket. Cost is well under one cent.

```bash
cd phase3
python3 phase3_validation.py --region us-east-1
```

Expected result: all five tests behave as the codebook predicts. The script
also writes `phase3_evidence.json` with the HTTP status of each test; the AWS
account ID is redacted automatically.

| Test | Grant | Expected S3 response |
| --- | --- | --- |
| T1 | POST policy with an empty `$key` prefix, upload to an unrelated key | accepted (2xx) |
| T2 | POST policy with `$key` prefix `uploads/`, upload outside it | rejected (403) |
| T3 | PUT URL with no size condition, 50 MB body | accepted (200) |
| T4 | POST policy with a 1 KB size range, 100 KB body | rejected (400) |
| T5 | GET URL with the key edited after signing | rejected (403) |

## Corpus pipeline and extraction tool

`phase1/` rebuilds the corpus from GitHub code search with the frozen settings
in `config.yaml` (snapshot label 2026-08-22, seed 42, per-term caps, strata
thresholds). It needs a GitHub personal access token; see the header of
`run.py`. Search results change over time, so a rerun will not return exactly
the original snapshot; `phase1/reports/` records the original counts.

`phase2_extractor/` turns sampled files into coding sheets, for example:

```bash
python3 -m phase2_extractor.cli extract \
  --manifest <sample.jsonl> --blobs <blobs_dir> \
  --out coding_sheet.csv --xlsx --window-lines 40
```

The blind sample used the default 15-line window; the targeted POST sample
used `--window-lines 40`. The extractor's test fixtures are real corpus files
and are not included, so its built-in self-test does not run from this
repository.

## Data release and reviewer access

The public data files include each file's Git blob SHA but not repository
names, file paths, URLs, extracted source code, or coder notes. Publishing
those together with the security codes would amount to a list of
identifiable, possibly still-deployed projects paired with their weaknesses.

The identified coding sheets (repository, path, SHA, extracted code window,
coder notes, and codes, keyed by the same `row_id`) were provided to the
journal's reviewers as confidential supplementary material. They are
available from the author on reasonable request for research verification.

## Citation

```
Kalaiah, U. Scoped Keys, Unbounded Uploads: An Empirical Study of Amazon S3
Presigned URL Authority in Open-Source Code. [Journal], [Year], [Volume], [Article].
```

## License

Code is released under the MIT License (see `LICENSE`). The de-identified data
files and the codebook are released under CC BY 4.0.
