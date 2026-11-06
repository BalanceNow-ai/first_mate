"""S3-compatible private object store (SJ-D5): production buckets and VersityGW locally.

Two clients share the credentials:

* the *internal* client talks to ``OBJECT_STORE_ENDPOINT_URL`` (e.g. ``http://objectstore:7070``
  inside the local stack; empty = AWS) for put/get/delete/head;
* the *signer* is configured with ``OBJECT_STORE_PUBLIC_ENDPOINT_URL`` — the origin the
  browser reaches (locally the nginx proxy on :18080, which forwards ``/<bucket>/`` to the
  gateway with the original ``Host`` header so the SigV4 signature still verifies).

Path-style addressing everywhere (no bucket subdomains). Objects are written with
``Content-Disposition: attachment`` and ``Cache-Control: no-store`` so a signed URL never
renders inline; signed URLs are capped at five minutes regardless of configuration.
Every boto error becomes :class:`ObjectStoreError` (callers keep the asset unavailable).
"""

from __future__ import annotations

import re

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.services.service_jobs.storage import MAX_SIGNED_URL_SECONDS, ObjectStoreError

_MISSING = {"404", "NoSuchKey", "NotFound", "NoSuchBucket"}
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    """ASCII-only, quote-free filename for Content-Disposition (never user-controlled raw)."""
    cleaned = _SAFE_FILENAME.sub("_", name).strip("._") or "download"
    return cleaned[:100]


def _code(exc: ClientError) -> str:
    err = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
    return str(err.get("Code") or exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))


class S3Store:
    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        public_endpoint_url: str | None,
        region: str,
        access_key: str | None,
        secret_key: str | None,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
    ) -> None:
        if not bucket:
            raise ObjectStoreError("OBJECT_STORE_BUCKET is not configured")
        self.bucket = bucket
        self.region = region or "us-east-1"
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )
        session = boto3.session.Session(
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=self.region,
        )
        self._client = session.client("s3", endpoint_url=endpoint_url or None, config=config)
        self._signer = session.client("s3", endpoint_url=public_endpoint_url or endpoint_url or None, config=config)

    @classmethod
    def from_settings(cls, settings) -> S3Store:
        return cls(
            bucket=settings.object_store_bucket,
            endpoint_url=settings.object_store_endpoint_url or None,
            public_endpoint_url=settings.object_store_public_endpoint_url or None,
            region=settings.object_store_region,
            access_key=settings.object_store_access_key or None,
            secret_key=settings.object_store_secret_key or None,
        )

    # --- object operations -------------------------------------------------------
    def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type or "application/octet-stream",
                ContentDisposition="attachment",
                CacheControl="no-store",
            )
        except (ClientError, BotoCoreError) as exc:
            raise ObjectStoreError(f"put failed ({type(exc).__name__})") from None

    def get(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if _code(exc) in _MISSING:
                raise ObjectStoreError("missing object") from None
            raise ObjectStoreError(f"get failed ({_code(exc)})") from None
        except BotoCoreError as exc:
            raise ObjectStoreError(f"get failed ({type(exc).__name__})") from None

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _code(exc) in _MISSING:
                return
            raise ObjectStoreError(f"delete failed ({_code(exc)})") from None
        except BotoCoreError as exc:
            raise ObjectStoreError(f"delete failed ({type(exc).__name__})") from None

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if _code(exc) in _MISSING:
                return False
            raise ObjectStoreError(f"head failed ({_code(exc)})") from None
        except BotoCoreError as exc:
            raise ObjectStoreError(f"head failed ({type(exc).__name__})") from None

    def signed_get_url(self, key: str, *, filename: str, content_type: str, seconds: int) -> str:
        """A presigned GET for the browser host, at most five minutes long."""
        expires_in = max(1, min(int(seconds), MAX_SIGNED_URL_SECONDS))
        try:
            return self._signer.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{safe_filename(filename)}"',
                    "ResponseContentType": content_type or "application/octet-stream",
                    "ResponseCacheControl": "no-store",
                },
                ExpiresIn=expires_in,
            )
        except (ClientError, BotoCoreError) as exc:
            raise ObjectStoreError(f"sign failed ({type(exc).__name__})") from None

    # --- provisioning (local stack / CLI) ------------------------------------------
    def ensure_bucket(self) -> bool:
        """Create the private bucket if it does not exist. Returns True when created."""
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return False
        except ClientError as exc:
            if _code(exc) not in _MISSING:
                raise ObjectStoreError(f"bucket check failed ({_code(exc)})") from None
        except BotoCoreError as exc:
            raise ObjectStoreError(f"bucket check failed ({type(exc).__name__})") from None
        kwargs: dict = {"Bucket": self.bucket}
        if self.region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
        try:
            self._client.create_bucket(**kwargs)
        except ClientError as exc:
            if _code(exc) not in {"BucketAlreadyOwnedByYou"}:
                raise ObjectStoreError(f"bucket create failed ({_code(exc)})") from None
            return False
        except BotoCoreError as exc:
            raise ObjectStoreError(f"bucket create failed ({type(exc).__name__})") from None
        return True
