"""Rules every uploaded image must pass, wherever it is uploaded from.

Avatars and check-in photos share them: one place to change the allowed formats
or the size cap, and no way for the two flows to drift apart.
"""

from app.core.settings import settings
from app.shared.exception.errors import BusinessException
from app.shared.storage.object_storage import StoredObject, object_storage

# The extension is cosmetic; the stored content type is what matters.
IMAGE_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _bare_content_type(content_type: str) -> str:
    # Browsers may send "image/jpeg; charset=binary".
    return content_type.split(";")[0].strip().lower()


def normalize_image_content_type(content_type: str) -> str:
    """The type to sign the upload with, or a 400 if it is not an image we accept."""
    normalized = _bare_content_type(content_type)
    if normalized not in settings.allowed_image_types or normalized not in IMAGE_EXTENSIONS:
        raise BusinessException(f"Unsupported image type: {content_type}.")
    return normalized


def image_extension(content_type: str) -> str:
    return IMAGE_EXTENSIONS[_bare_content_type(content_type)]


async def verify_uploaded_image(key: str) -> StoredObject:
    """Checks what actually landed in storage, deleting it if it breaks the rules.

    A presigned PUT cannot cap the size, and the client controls the headers, so
    nothing about the upload can be trusted until it is read back.
    """
    stored = await object_storage.stat(key)
    if stored is None:
        raise BusinessException("The upload was not found. Request a new upload URL and try again.")

    if stored.size_bytes > settings.storage_max_upload_bytes:
        await object_storage.delete(key)
        raise BusinessException(f"The image is larger than {settings.storage_max_upload_bytes} bytes.")

    if _bare_content_type(stored.content_type) not in settings.allowed_image_types:
        await object_storage.delete(key)
        raise BusinessException(f"Unsupported image type: {stored.content_type}.")

    return stored
