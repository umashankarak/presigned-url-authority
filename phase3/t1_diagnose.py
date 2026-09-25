#!/usr/bin/env python3
"""Diagnose why T1 (empty-prefix POST) returned 403.
Creates a throwaway bucket, disables Block Public Access + sets a permissive
ownership so a POST-policy upload isn't blocked by account defaults, then
retries the empty-prefix write and prints S3's full error body."""
import sys, time, uuid
import boto3, requests
from botocore.exceptions import ClientError

region = sys.argv[1] if len(sys.argv) > 1 else "us-east-1"
s3 = boto3.client("s3", region_name=region)

name = f"paper9-phase3-diag-{uuid.uuid4().hex[:12]}"
if region == "us-east-1":
    s3.create_bucket(Bucket=name)
else:
    s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": region})
s3.get_waiter("bucket_exists").wait(Bucket=name)
print("bucket:", name)

def try_empty_prefix(label):
    post = s3.generate_presigned_post(
        Bucket=name, Key="intended/placeholder",
        Conditions=[["starts-with", "$key", ""]], ExpiresIn=300)
    fields = dict(post["fields"]); fields["key"] = "attacker-controlled/elsewhere.txt"
    r = requests.post(post["url"], data=fields, files={"file": ("x", b"arbitrary-write")})
    print(f"\n[{label}] HTTP {r.status_code}")
    print("  S3 response body:")
    print("  " + (r.text.strip()[:800].replace("\n", "\n  ") or "(empty)"))
    return r.status_code

try:
    # 1) as-is (account defaults)
    try_empty_prefix("default account settings")

    # 2) disable Block Public Access on THIS bucket only
    try:
        s3.put_public_access_block(
            Bucket=name,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False, "IgnorePublicAcls": False,
                "BlockPublicPolicy": False, "RestrictPublicBuckets": False})
        print("\n  -> disabled Block Public Access on the bucket")
    except ClientError as e:
        print("\n  (could not change BPA:", e, ")")
    # ownership controls -> allow ACLs (bucket-owner-preferred)
    try:
        s3.put_bucket_ownership_controls(
            Bucket=name,
            OwnershipControls={"Rules": [{"ObjectOwnership": "BucketOwnerPreferred"}]})
        print("  -> set ObjectOwnership=BucketOwnerPreferred")
    except ClientError as e:
        print("  (could not change ownership:", e, ")")
    time.sleep(3)
    try_empty_prefix("after disabling BPA + allowing ACLs")
finally:
    # cleanup
    try:
        p = s3.get_paginator("list_objects_v2")
        for page in p.paginate(Bucket=name):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs: s3.delete_objects(Bucket=name, Delete={"Objects": objs})
        s3.delete_bucket(Bucket=name)
        print("\ndeleted bucket:", name)
    except ClientError as e:
        print("\ncleanup warning:", e)
