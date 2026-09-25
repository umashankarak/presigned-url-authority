#!/usr/bin/env python3
"""
Phase 3 — Ground-truth validation harness
S3 presigned-URL over-grant study (paper 9)

Runs ONLY on infrastructure you own. Creates one throwaway bucket in YOUR AWS
account, empirically demonstrates the real authority behind each Phase-2
taxonomy pattern, prints a pass/fail evidence table, and deletes everything
at the end (even if a test fails).

It NEVER touches a bucket you don't own, never uses a URL from the corpus,
and never probes a live namespace. This is the "owned-infrastructure only"
discipline the paper commits to.

What it demonstrates (each maps to a paper claim):
  T1  Empty-prefix POST policy  -> S3 ACCEPTS a write to an unrelated key
  T2  Prefix-scoped POST policy -> S3 REJECTS a write outside the prefix
  T3  Unbounded PUT             -> S3 ACCEPTS an oversized body (no size check)  [HEADLINE]
  T4  POST content-length-range -> S3 REJECTS an oversized body
  T5  Signed GET, edited key    -> signature INVALID (GET key-swap does not work)
  T6  (optional) STS vs IAM lifetime note

Requirements: boto3, requests, and AWS credentials with S3 create/put/get/
delete + deletebucket permissions.  pip3 install boto3 requests

Usage:
    python3 phase3_validation.py
    python3 phase3_validation.py --region us-east-1 --keep   # keep bucket for inspection
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    sys.exit("pip3 install boto3 requests")
try:
    import requests
except ImportError:
    sys.exit("pip3 install requests")


RESULTS = []


def record(test_id, claim, expected, observed, passed, evidence):
    RESULTS.append({
        "test": test_id, "claim": claim, "expected": expected,
        "observed": observed, "result": "PASS" if passed else "FAIL",
        "evidence": evidence,
    })
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {test_id}: {claim}")
    print(f"         expected: {expected}")
    print(f"         observed: {observed}")


def make_bucket(s3, region):
    name = f"paper9-phase3-{uuid.uuid4().hex[:16]}"
    if region == "us-east-1":
        s3.create_bucket(Bucket=name)
    else:
        s3.create_bucket(Bucket=name,
                         CreateBucketConfiguration={"LocationConstraint": region})
    # wait until it exists
    s3.get_waiter("bucket_exists").wait(Bucket=name)
    print(f"  created throwaway bucket: {name}\n")
    return name


def nuke_bucket(s3, bucket):
    try:
        # delete all objects first
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objs})
        s3.delete_bucket(Bucket=bucket)
        print(f"\n  deleted bucket: {bucket}")
    except ClientError as e:
        print(f"\n  WARNING: could not fully delete {bucket}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# T1: empty-prefix POST policy permits writing to an ARBITRARY key
# ---------------------------------------------------------------------------
def t1_empty_prefix_post(s3, bucket):
    # Key MUST be the ${filename} POST variable, not a literal: a literal Key
    # makes boto3 inject an implicit ["eq","$key",<literal>] that would pin the
    # key. Using ${filename} leaves ONLY the empty-prefix starts-with, which is
    # exactly the vulnerable shape found in real code.
    post = s3.generate_presigned_post(
        Bucket=bucket,
        Key="${filename}",                          # POST variable, not a fixed key
        Conditions=[["starts-with", "$key", ""]],   # empty prefix = write anywhere
        ExpiresIn=300,
    )
    # attacker fills $key with a completely unrelated path
    evil_key = "attacker-controlled/somewhere-else.txt"
    fields = dict(post["fields"])
    fields["key"] = evil_key
    r = requests.post(post["url"], data=fields,
                      files={"file": ("x", b"arbitrary-write")})
    accepted = r.status_code in (200, 201, 204)
    record("T1",
           "empty-prefix POST permits writing to an arbitrary key",
           "S3 accepts the write (2xx)",
           f"HTTP {r.status_code} to key '{evil_key}'",
           accepted,
           {"http_status": r.status_code, "written_key": evil_key})


# ---------------------------------------------------------------------------
# T2: prefix-scoped POST policy REJECTS writes outside the prefix
# ---------------------------------------------------------------------------
def t2_prefix_scoped_post(s3, bucket):
    post = s3.generate_presigned_post(
        Bucket=bucket,
        Key="${filename}",                                 # POST variable, not pinned
        Conditions=[["starts-with", "$key", "uploads/"]],  # confined to uploads/
        ExpiresIn=300,
    )
    fields = dict(post["fields"])
    fields["key"] = "secrets/stolen.txt"   # outside the allowed prefix
    r = requests.post(post["url"], data=fields,
                      files={"file": ("x", b"should-be-rejected")})
    rejected = r.status_code in (400, 403)
    record("T2",
           "prefix-scoped POST rejects writes outside the prefix",
           "S3 rejects the write (4xx)",
           f"HTTP {r.status_code} to key 'secrets/stolen.txt'",
           rejected,
           {"http_status": r.status_code})


# ---------------------------------------------------------------------------
# T3 (HEADLINE): unbounded PUT ignores Content-Length — accepts oversized body
# ---------------------------------------------------------------------------
def t3_unbounded_put(s3, bucket, oversized_mb=50):
    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": "put-upload/object.bin"},
        ExpiresIn=300,
    )
    body = b"\0" * (oversized_mb * 1024 * 1024)   # capped for cost; still proves the point
    r = requests.put(url, data=body)
    accepted = r.status_code in (200, 201, 204)
    record("T3",
           "signed PUT imposes NO size limit (headline: unbounded write)",
           f"S3 accepts a {oversized_mb} MB body with no size condition",
           f"HTTP {r.status_code} for {oversized_mb} MB PUT",
           accepted,
           {"http_status": r.status_code, "body_bytes": len(body)})


# ---------------------------------------------------------------------------
# T4: POST content-length-range ENFORCES size (the fix works)
# ---------------------------------------------------------------------------
def t4_bounded_post(s3, bucket, cap_bytes=1024):
    post = s3.generate_presigned_post(
        Bucket=bucket,
        Key="${filename}",                                    # POST variable
        Conditions=[["content-length-range", 0, cap_bytes]],  # 1 KB cap, no key pin
        ExpiresIn=300,
    )
    oversized = b"\0" * (cap_bytes * 100)  # 100x the cap
    fields = dict(post["fields"])
    fields["key"] = "bounded/object.bin"
    r = requests.post(post["url"], data=fields,
                      files={"file": ("x", oversized)})
    rejected = r.status_code in (400, 403)
    record("T4",
           "POST content-length-range enforces the size cap server-side",
           f"S3 rejects a body over the {cap_bytes}-byte cap",
           f"HTTP {r.status_code} for oversized POST",
           rejected,
           {"http_status": r.status_code, "cap_bytes": cap_bytes,
            "sent_bytes": len(oversized)})


# ---------------------------------------------------------------------------
# T5: signed GET with an edited key fails (GET key-swap is NOT a vector)
# ---------------------------------------------------------------------------
def t5_get_key_swap(s3, bucket):
    # put a real object so a correct GET would 200
    s3.put_object(Bucket=bucket, Key="get-target/real.txt", Body=b"real")
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": "get-target/real.txt"},
        ExpiresIn=300,
    )
    # tamper: swap the key in the path to a different object
    swapped = url.replace("get-target/real.txt", "get-target/other.txt")
    r = requests.get(swapped)
    invalid = r.status_code == 403
    record("T5",
           "editing the key in a signed GET URL invalidates the signature",
           "tampered URL -> HTTP 403 (SignatureDoesNotMatch)",
           f"HTTP {r.status_code} for key-swapped GET",
           invalid,
           {"http_status": r.status_code,
            "note": "confirms GET key-swap is NOT an over-grant vector"})


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--oversized-mb", type=int, default=50,
                    help="body size for the unbounded-PUT test (default 50 MB; cost is a fraction of a cent)")
    ap.add_argument("--keep", action="store_true", help="do not delete the bucket (for inspection)")
    args = ap.parse_args()

    session = boto3.session.Session(region_name=args.region)
    s3 = session.client("s3")

    # who am I / fail fast if creds are wrong
    ident = session.client("sts").get_caller_identity()
    print("=" * 70)
    print("PHASE 3 — GROUND-TRUTH VALIDATION (owned infrastructure)")
    print("=" * 70)
    print(f"  AWS account: {ident['Account']}   region: {args.region}")
    print(f"  identity:    {ident['Arn']}\n")

    bucket = make_bucket(s3, args.region)
    try:
        t1_empty_prefix_post(s3, bucket)
        t2_prefix_scoped_post(s3, bucket)
        t3_unbounded_put(s3, bucket, args.oversized_mb)
        t4_bounded_post(s3, bucket)
        t5_get_key_swap(s3, bucket)
    finally:
        if not args.keep:
            nuke_bucket(s3, bucket)
        else:
            print(f"\n  --keep set; bucket {bucket} left in place. Delete it manually when done.")

    # summary table + machine-readable evidence
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    npass = sum(1 for r in RESULTS if r["result"] == "PASS")
    for r in RESULTS:
        print(f"  {r['result']:4s}  {r['test']}: {r['claim']}")
    print(f"\n  {npass}/{len(RESULTS)} demonstrations behaved as the taxonomy predicts.")

    out = "phase3_evidence.json"
    with open(out, "w") as f:
        json.dump({"account": "<redacted>", "region": args.region,
                   "results": RESULTS}, f, indent=2)
    print(f"\n  full evidence (HTTP statuses, keys, byte counts) -> {out}")
    print("  include this table + evidence file in the paper's Phase-3 section.")


if __name__ == "__main__":
    main()
