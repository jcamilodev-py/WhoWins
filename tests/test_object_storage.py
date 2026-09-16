from urllib.parse import parse_qs, urlparse

import httpx

from app.core.settings import settings
from app.shared.storage.object_storage import ObjectStorage, object_storage

KEY = "users/11111111-1111-1111-1111-111111111111/avatar.jpg"


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


# --- signing (no storage service needed) ---


def test_upload_url_points_at_the_bucket_and_key():
    upload = object_storage.create_upload_url(KEY, "image/jpeg")

    parsed = urlparse(upload.url)
    assert parsed.path == f"/{settings.storage_bucket}/{KEY}"
    assert parsed.netloc == urlparse(settings.storage_signing_endpoint).netloc


def test_upload_url_expires_and_is_signed():
    upload = object_storage.create_upload_url(KEY, "image/jpeg")

    query = _query(upload.url)
    assert query["X-Amz-Expires"] == [str(settings.storage_upload_url_expire_seconds)]
    assert query["X-Amz-Signature"]
    assert upload.expires_in_seconds == settings.storage_upload_url_expire_seconds


def test_upload_url_signature_covers_the_content_type():
    # The client cannot promise a JPEG and then upload something else: the
    # content type is part of what was signed.
    upload = object_storage.create_upload_url(KEY, "image/jpeg")

    assert "content-type" in _query(upload.url)["X-Amz-SignedHeaders"][0]
    assert upload.content_type == "image/jpeg"


def test_upload_urls_for_different_keys_have_different_signatures():
    first = object_storage.create_upload_url(KEY, "image/jpeg")
    second = object_storage.create_upload_url("users/other/avatar.jpg", "image/jpeg")

    assert _query(first.url)["X-Amz-Signature"] != _query(second.url)["X-Amz-Signature"]


def test_download_url_uses_its_own_expiry():
    url = object_storage.create_download_url(KEY)

    assert _query(url)["X-Amz-Expires"] == [str(settings.storage_download_url_expire_seconds)]


# --- round trip against a real MinIO (skipped when it is not running) ---


async def test_uploaded_object_can_be_inspected_and_deleted(storage: ObjectStorage):
    key = f"tests/{KEY}"
    upload = storage.create_upload_url(key, "image/jpeg")

    async with httpx.AsyncClient() as http:
        response = await http.put(upload.url, content=b"fake-jpeg-bytes", headers={"Content-Type": "image/jpeg"})

    assert response.status_code == 200
    stored = await storage.stat(key)
    assert stored is not None
    assert stored.size_bytes == len(b"fake-jpeg-bytes")
    assert stored.content_type == "image/jpeg"

    await storage.delete(key)
    assert await storage.stat(key) is None


async def test_stat_returns_none_for_an_object_that_was_never_uploaded(storage: ObjectStorage):
    assert await storage.stat("tests/never-uploaded.jpg") is None


async def test_upload_is_rejected_when_the_content_type_does_not_match(storage: ObjectStorage):
    upload = storage.create_upload_url(f"tests/{KEY}", "image/jpeg")

    async with httpx.AsyncClient() as http:
        response = await http.put(upload.url, content=b"anything", headers={"Content-Type": "application/pdf"})

    assert response.status_code == 403
    assert await storage.stat(f"tests/{KEY}") is None
