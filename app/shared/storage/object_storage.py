"""S3-compatible object storage.

Photos never travel through this backend. It signs a short-lived URL, the client
uploads straight to the storage service, and then the backend checks what landed
there. That keeps large uploads off the API and works the same on MinIO, S3, R2
and Supabase Storage.
"""

import asyncio
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.settings import settings


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    key: str
    # The client must send exactly this header: it is part of what was signed.
    content_type: str
    expires_in_seconds: int


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str


class ObjectStorageError(Exception):
    """The storage service could not be reached or refused the operation."""


class ObjectStorage:
    def __init__(self) -> None:
        self.bucket = settings.storage_bucket

    @cached_property
    def _client(self) -> Any:
        return boto3.client(
            "s3",
            # Signed against the host the client will call: the signature covers it.
            endpoint_url=settings.storage_signing_endpoint,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name=settings.storage_region,
            config=Config(
                signature_version="s3v4",
                # Path style keeps localhost working: virtual-host style would
                # need a DNS name per bucket (bucket.localhost).
                s3={"addressing_style": "path"},
                # A storage outage must fail fast instead of holding a request
                # open while botocore retries for a minute.
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 2},
            ),
        )

    def create_upload_url(self, key: str, content_type: str) -> PresignedUpload:
        """A URL the client can PUT one file to. Pure signing: no network call."""
        expires_in = settings.storage_upload_url_expire_seconds
        url = self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
        return PresignedUpload(url=url, key=key, content_type=content_type, expires_in_seconds=expires_in)

    def create_download_url(self, key: str) -> str:
        """A URL to read a private object, valid for a short while."""
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=settings.storage_download_url_expire_seconds,
            )
        )

    async def stat(self, key: str) -> StoredObject | None:
        """What actually landed in storage, or None if nothing did."""
        try:
            # boto3 is synchronous; a thread keeps the event loop free.
            head = await asyncio.to_thread(self._client.head_object, Bucket=self.bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise ObjectStorageError(f"Could not read object {key}.") from error
        except Exception as error:
            raise ObjectStorageError(f"Could not reach object storage for {key}.") from error

        return StoredObject(
            key=key,
            size_bytes=int(head["ContentLength"]),
            content_type=str(head.get("ContentType", "application/octet-stream")),
        )

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)
        except Exception as error:
            raise ObjectStorageError(f"Could not delete object {key}.") from error


object_storage = ObjectStorage()
