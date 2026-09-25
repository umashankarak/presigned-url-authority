#!/usr/bin/env python3
"""Check the boto3 behaviors cited in the paper's Background section.
Runs locally: generating a presigned URL or POST policy sends nothing to AWS.
Needs any configured AWS credentials (the signature is computed, not used)."""
import base64, json, urllib.parse
from datetime import datetime, timezone
import boto3, botocore
from botocore.config import Config

s3 = boto3.client("s3", region_name="us-east-1", config=Config(signature_version="s3v4"))
print("boto3", boto3.__version__, "| botocore", botocore.__version__)

# 1) Key condition that generate_presigned_post adds by itself
for key in ["uploads/photo.png", "uploads/${filename}", "${filename}"]:
    post = s3.generate_presigned_post(Bucket="example-bucket", Key=key)
    policy = json.loads(base64.b64decode(post["fields"]["policy"]))
    print(f"\nKey = {key!r}")
    for c in policy["conditions"]:
        if not (isinstance(c, dict) and ("x-amz-credential" in c)):
            print("   ", c)

# 2) Default expiry when none is given
url = s3.generate_presigned_url("get_object", Params={"Bucket": "example-bucket", "Key": "a.txt"})
q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
print("\ngenerate_presigned_url default X-Amz-Expires:", q.get("X-Amz-Expires"))
post = s3.generate_presigned_post(Bucket="example-bucket", Key="a.txt")
exp = json.loads(base64.b64decode(post["fields"]["policy"]))["expiration"]
print("generate_presigned_post policy expiration:", exp)
print("current UTC time:                         ", datetime.now(timezone.utc).isoformat())
