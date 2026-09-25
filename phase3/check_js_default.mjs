// Check the default expiry of the AWS SDK for JavaScript v3 request presigner.
// Setup: npm install @aws-sdk/client-s3 @aws-sdk/s3-request-presigner
// Runs locally; nothing is sent to AWS.
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
const client = new S3Client({ region: "us-east-1" });
const url = await getSignedUrl(client,
  new GetObjectCommand({ Bucket: "example-bucket", Key: "a.txt" }));
console.log("X-Amz-Expires:", new URL(url).searchParams.get("X-Amz-Expires"));
