#!/usr/bin/env python3
"""Check that phase2_results.txt contains every number the paper reports.
Usage: python3 check_paper_numbers.py phase2_results.txt"""
import sys

EXPECTED = [
    # eligibility
    ("Blind sample coded/eligible", "BLIND sample: 383 coded  |  eligible 260"),
    ("Targeted sample coded/eligible", "TARGETED POST stratum: 238 coded  |  eligible 231"),
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
    ("Key scope indeterminate", "INDETERMINATE:     134  (45.0% of coded)"),
    # size bound
    ("Size bound overall", "67/229 = 29.3%  [95% CI 23.7%-35.5%]"),
    ("Size bound POST", "POST unbounded:  38/194 = 19.6%"),
    ("Size bound PUT", "PUT unbounded:   29/35 = 82.9%  [95% CI 67.3%-91.9%]"),
    ("Size bound indeterminate", "INDETERMINATE:     105  (31.4% of coded)"),
    # key origin / authorization
    ("Raw user key", "24/139 = 17.3%"),
    ("No resource-level authz", "51/86 = 59.3%"),
    ("Raw key + no authz", "17/71 = 23.9%"),
    # credentials / expiry
    ("Credentials determinable", "determinable:      19"),
    ("Expiry over-long", "1/83 = 1.2%"),
    # supplementary (stratum table, PUT sensitivity, short expiries)
    ("Stratum: primary write-anywhere", "write-anywhere POST key scope:   0/44 = 0.0%"),
    ("Stratum: low-signal write-anywhere", "write-anywhere POST key scope:   0/120 = 0.0%"),
    ("Stratum: primary POST no size", "POST without size range:         10/49 = 20.4%"),
    ("Stratum: low-signal POST no size", "POST without size range:         28/145 = 19.3%"),
    ("Stratum: primary PUT no size", "PUT without size bound:          20/26 = 76.9%"),
    ("Stratum: low-signal PUT no size", "PUT without size bound:          9/9 = 100.0%"),
    ("Stratum: primary no authz", "no resource-level authorization: 38/64 = 59.4%"),
    ("Stratum: low-signal no authz", "no resource-level authorization: 13/22 = 59.1%"),
    ("PUT sensitivity", "PUT without size bound:          42/48 = 87.5%"),
    ("Expiry <= 1 hour", "expiry <= 1 hour:                81/99 = 81.8%"),
    # revision 1 (Frontiers): weighted estimates, bounds, denominator flow
    ("Weighted write-anywhere", "write-anywhere POST key scope      weighted 0.0%"),
    ("Weighted POST no size", "POST without size range            weighted 19.4%"),
    ("Weighted PUT no size", "PUT without size bound             weighted 96.6%"),
    ("Weighted no authz", "no resource-level authorization    weighted 59.1%"),
    ("Weighted raw key", "raw user-supplied key              weighted 20.3%"),
    ("Bounds write-anywhere", "all coded 298 (134 indeterminate): 0.0% to 45.0%"),
    ("Bounds POST no size", "all coded 297 (103 indeterminate): 12.8% to 47.5%"),
    ("Bounds all uploads", "all coded 334 (105 indeterminate): 20.1% to 51.5%"),
    ("Bounds no authz", "all coded 260 (174 indeterminate): 19.6% to 86.5%"),
    ("Bounds raw key", "all coded 260 (121 indeterminate): 9.2% to 55.8%"),
    ("Flow: extracted sites", "blind 383; targeted 238; total 621"),
    ("Flow: eligible", "blind 260; targeted 231"),
    ("Flow: key scope pooled", "key scope (pooled)                          298    134     164"),
    ("Flow: authorization", "authorization (blind)                       260    174      86"),
]

text = open(sys.argv[1] if len(sys.argv) > 1 else "phase2_results.txt", encoding="utf-8").read()
fails = 0
for label, needle in EXPECTED:
    ok = needle in text
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
print(f"\n{len(EXPECTED) - fails}/{len(EXPECTED)} paper numbers confirmed")
