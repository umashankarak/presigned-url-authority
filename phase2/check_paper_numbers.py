#!/usr/bin/env python3
"""Check that phase2_results.txt contains every number the paper reports.
Usage: python3 check_paper_numbers.py phase2_results.txt"""
import sys

EXPECTED = [
    # eligibility
    ("Blind sample coded/eligible", "BLIND sample: 383 coded  |  eligible 260"),
    ("Targeted sample coded/eligible", "TARGETED POST stratum: 238 coded  |  eligible 232"),
    ("Ineligible reasons", "'SDK_SOURCE': 60"),
    ("Precision POST label", "68/ 80 eligible = 85.0%"),
    ("Precision GET label", "96/126 eligible = 76.2%"),
    ("Precision PUT label", "37/ 48 eligible = 77.1%"),
    ("Precision undetermined", "59/129 eligible = 45.7%"),
    ("S3-compatible", "28/260 = 10.8%"),
    # mechanism
    ("Mechanism GET", "GET-URL            96  36.9%"),
    ("Mechanism POST", "POST-policy        68  26.2%"),
    ("Mechanism PUT", "PUT-URL            37  14.2%"),
    ("Mechanism undetermined", "INDETERMINATE      59  22.7%"),
    # key scope
    ("Key scope exact", "EXACT             144  87.8%"),
    ("Key scope prefix", "PREFIX             20  12.2%"),
    ("Key scope write-anywhere", "0/164 = 0.0%  [95% CI 0.0%-2.3%]"),
    ("Key scope indeterminate", "INDETERMINATE:     135  (45.2% of coded)"),
    # size bound
    ("Size bound overall", "67/230 = 29.1%  [95% CI 23.6%-35.3%]"),
    ("Size bound POST", "POST unbounded:  37/193 = 19.2%"),
    ("Size bound PUT", "PUT unbounded:   30/37 = 81.1%"),
    ("Size bound indeterminate", "INDETERMINATE:     105  (31.3% of coded)"),
    # key origin / authorization
    ("Raw user key", "24/139 = 17.3%"),
    ("No resource-level authz", "50/86 = 58.1%"),
    ("Raw key + no authz", "17/71 = 23.9%"),
    # credentials / expiry
    ("Credentials determinable", "determinable:      19"),
    ("Expiry over-long", "1/83 = 1.2%"),
    # supplementary (stratum table, PUT sensitivity, short expiries)
    ("Stratum: primary write-anywhere", "write-anywhere POST key scope:   0/44 = 0.0%"),
    ("Stratum: low-signal write-anywhere", "write-anywhere POST key scope:   0/120 = 0.0%"),
    ("Stratum: primary POST no size", "POST without size range:         9/48 = 18.8%"),
    ("Stratum: low-signal POST no size", "POST without size range:         28/145 = 19.3%"),
    ("Stratum: primary PUT no size", "PUT without size bound:          21/28 = 75.0%"),
    ("Stratum: low-signal PUT no size", "PUT without size bound:          9/9 = 100.0%"),
    ("Stratum: primary no authz", "no resource-level authorization: 37/64 = 57.8%"),
    ("Stratum: low-signal no authz", "no resource-level authorization: 13/22 = 59.1%"),
    ("PUT sensitivity", "PUT without size bound:          43/50 = 86.0%"),
    ("Expiry <= 1 hour", "expiry <= 1 hour:                81/99 = 81.8%"),
]

text = open(sys.argv[1] if len(sys.argv) > 1 else "phase2_results.txt", encoding="utf-8").read()
fails = 0
for label, needle in EXPECTED:
    ok = needle in text
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
print(f"\n{len(EXPECTED) - fails}/{len(EXPECTED)} paper numbers confirmed")
