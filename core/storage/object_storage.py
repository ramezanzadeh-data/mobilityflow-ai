import os

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

# Works against real AWS S3 (leave S3_ENDPOINT_URL unset) or any
# S3-compatible store such as MinIO (set S3_ENDPOINT_URL to its address).
# Documents and generated reports live here, never on the app's own
# filesystem - that's what makes them survive a container restart/
# redeploy and be shareable across API/worker/Streamlit instances.
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL") or None
S3_BUCKET = os.environ.get("S3_BUCKET", "mobilityflow-documents")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")

_client = None


def _get_client():

    global _client

    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT_URL,
            region_name=S3_REGION,
            aws_access_key_id=S3_ACCESS_KEY_ID,
            aws_secret_access_key=S3_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
        )

    return _client


def ensure_bucket_exists():

    client = _get_client()

    try:
        client.head_bucket(Bucket=S3_BUCKET)
    except ClientError:
        create_kwargs = {"Bucket": S3_BUCKET}
        if S3_REGION and S3_REGION != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": S3_REGION}
        client.create_bucket(**create_kwargs)


def upload_bytes(key, data, content_type="application/octet-stream"):

    client = _get_client()

    client.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=content_type)

    return key


def download_bytes(key):

    client = _get_client()

    response = client.get_object(Bucket=S3_BUCKET, Key=key)

    return response["Body"].read()


def generate_presigned_url(key, expires_in=3600):

    client = _get_client()

    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def delete_object(key):

    client = _get_client()

    client.delete_object(Bucket=S3_BUCKET, Key=key)


def object_exists(key):

    client = _get_client()

    try:
        client.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError:
        return False
