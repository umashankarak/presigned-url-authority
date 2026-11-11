# Coding-reliability audit

A second coder independently coded a random subset of 80 eligible sites after
the main coding was complete. She worked from the same extraction windows and
codebook (`../CODEBOOK.md`), without access to the final codes, without AI
tools, and without discussing individual sites with the author. Before the
audit she coded 10 separate practice sites on her own; the practice codes were
not compared or discussed, and the codebook did not change between practice
and audit.

## Files

| File | Contents |
| --- | --- |
| `draw_audit_sample.py` | Draws the audit and practice sites with seed 20261107 |
| `coding_tool.html` | Browser tool used for coding (Chrome or Edge); saves choices into the coder's sheet |
| `deidentify_audit.py` | Writes the two public code files from the private audit files |
| `audit_final_codes.csv` | Final codes for the 80 sites at the time of the audit, with the public `row_id` |
| `audit_second_coder_codes.csv` | The second coder's independent codes |
| `kappa_audit.py` | Raw agreement and Cohen's kappa per field |
| `audit_agreement.txt` | Output of `kappa_audit.py` reported in the paper |
| `audit_resolutions.csv` | The 14 disagreements and how each was resolved |

## Sample design

| Stratum | Sites | Pool |
| --- | --- | --- |
| A: blind, authorization coded none | 20 | 46 |
| B: blind, authorization coded indeterminate | 20 | 174 |
| C: blind, authorization check or authentication only | 10 | 40 |
| D: blind, other upload sites | 10 | remaining POST and PUT sites |
| E: targeted POST sample (key scope and size bound only) | 20 | 232 |

Authorization cases are oversampled, so the agreement values describe this
subset rather than the full sample. Sites coded for key scope only when they
are POST policies, so key scope has 48 paired codes.

## Reproduce

```bash
python3 kappa_audit.py audit_final_codes.csv audit_second_coder_codes.csv
```

Indeterminate and not-applicable count as codes in their own right. Fields
marked `NOT_CODED` (the targeted sites were coded for key scope and size bound
only) or left blank are skipped.

## Resolution

Each disagreement was resolved by examining the window against the codebook:
the second coder's code was adopted in six cases, the final code was kept in
seven, and one site was found to be library source and excluded. The changes
were applied with `../phase2/corrections/apply_audit_resolutions.py`. The
kappa values are those of the two independent codings, before resolution.

The audit sample cannot be redrawn from the public data files, because those
files hold the codes after resolution and the strata depend on the codes at
the time of the draw.
