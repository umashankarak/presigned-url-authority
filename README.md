# Scoped Keys, Unbounded Uploads

Code, codebook, and de-identified data for the paper **"Scoped Keys, Unbounded
Uploads: An Empirical Study of Amazon S3 Presigned URL Authority in
Open-Source Code"** (Umashankara Kalaiah, 2026).

The study coded 621 presigned-URL generation sites from public GitHub code in
eight languages and reproduced each authority pattern on an author-owned S3
bucket. With this repository you can:

1. recompute every number in the paper's Results section (two commands, no AWS account needed),
2. recompute the coding-reliability agreement (Cohen's kappa) from the second coder's independent codes,
3. regenerate the two figures,
4. rerun the SDK checks cited in the Background section (no AWS account needed), and
5. rerun the ground-truth validation on your own AWS account.

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
│   ├── corrections/             # the two documented code changes (already applied)
│   ├── data/
│   │   ├── blind_sample_coded.xlsx    # 383 coded sites (blind sample)
│   │   └── targeted_post_coded.xlsx   # 238 coded sites (targeted POST sample)
│   └── results/
│       └── phase2_results.txt   # analysis output behind the paper's numbers
├── reliability_audit/
│   ├── draw_audit_sample.py     # draws the 80-site audit sample (seed 20261107)
│   ├── coding_tool.html         # browser tool the second coder used
│   ├── deidentify_audit.py      # writes the two public code files below
│   ├── audit_final_codes.csv    # final codes at the time of the audit
│   ├── audit_second_coder_codes.csv  # the second coder's independent codes
│   ├── kappa_audit.py           # agreement and Cohen's kappa per field
│   ├── audit_agreement.txt      # output behind the paper's agreement table
│   └── audit_resolutions.csv    # how each of the 14 disagreements was resolved
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

The last command checks 49 numbers against the paper and should end with
`49/49 paper numbers confirmed`. Sections 10 to 12 of the output hold the
stratum-weighted estimates, the bounds over all eligible sites (each
indeterminate site counted first as safe and then as over-granting), and the
denominator flow behind the paper's table of coded, indeterminate, and
determinable sites.

Analysis rules, as stated in the paper:

- Rates are computed over *determinable* sites. `INDETERMINATE` codes are excluded from denominators and reported separately. `N_A` (a download site under size bound) is excluded as well.
- Proportions carry 95% Wilson score intervals.
- Key scope and size bound pool the POST sites of both samples. All other rates use the blind sample only, because the targeted sample over-represents POST policies by design.

The data files are described column by column in `CODEBOOK.md`.

### Data corrections

The data files include two documented changes, both already applied. The
scripts in `phase2/corrections/` record exactly what changed:

- `reclassify_put_size.py`: one PUT site (`B0006`) recoded from bounded to
  indeterminate under the PUT size rule in `CODEBOOK.md` (a PUT URL counts as
  bounded only when its content length is signed).
- `apply_audit_resolutions.py`: seven changes from the coding-reliability
  audit (six codes and one site found to be library source and made
  ineligible); see `reliability_audit/audit_resolutions.csv`.

## 2. Reproduce the coding-reliability agreement

A second coder independently coded 80 eligible sites after the main coding was
complete, from the same extraction windows and codebook, without access to the
final codes and without AI tools. The sample oversamples authorization cases
(20 coded none, 20 indeterminate, 10 with a check, 10 other upload sites, and
20 targeted POST sites), so the values describe this subset.

```bash
cd reliability_audit
python3 kappa_audit.py audit_final_codes.csv audit_second_coder_codes.csv
```

Expected: agreement 93.8% to 98.3% and Cohen's kappa 0.89 to 0.97 on all seven
fields, with 14 disagreements. The final codes are those at the time of the
audit, before the disagreements were resolved; `row_id` links each audit site to
the public data files. The coder sheets themselves hold extracted source code
and are not public.

## 3. Regenerate the figures

```bash
cd figures
python3 make_figure1.py    # Figure 1: study pipeline
python3 make_figure2.py    # Figure 2: over-grant rates with 95% intervals
```

## 4. Check the SDK behaviors cited in the paper (no AWS account needed)

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

## 5. Rerun the ground-truth validation (your own AWS account)

**Run this only in an AWS account you own.** It needs real credentials allowed
to create and delete an S3 bucket (unset the example credentials from step 4
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
coder notes, and codes, keyed by the same `row_id`) and the second coder's
working sheets are not public for the same reason. They are available to the
journal's editor and reviewers, and from the author on reasonable request for
research verification.

## Citation

```
Kalaiah, U. Scoped Keys, Unbounded Uploads: An Empirical Study of Amazon S3
Presigned URL Authority in Open-Source Code. [Journal], [Year], [Volume], [Article].
```

## License

Code is released under the MIT License (see `LICENSE`). The de-identified data
files and the codebook are released under CC BY 4.0.
