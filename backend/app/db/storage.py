"""
Handles image persistence to Supabase Storage per the bucket layout in
spec section 12. Falls back to local disk under
<backend_root>/local_storage/ when Supabase isn't configured, so the
pipeline still works for local development before Supabase is wired up.
"""

from pathlib import Path

from app.core.config import BACKEND_ROOT, get_settings
from app.core.errors import StorageError
from app.core.logging import get_logger
from app.db.supabase_client import get_client

logger = get_logger(__name__)


def _local_fallback_path(object_path: str) -> Path:
    settings = get_settings()
    full_path = BACKEND_ROOT / settings.local_storage_dir / object_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    return full_path


def upload_bytes(bucket: str, object_path: str, data: bytes, *, content_type: str = "image/jpeg") -> str:
    """
    Returns an object reference ("bucket/path") when Supabase Storage is
    used, or a local:// reference when falling back to disk. Callers only store this string, never
    raw bytes, in Postgres (spec section 12).
    """
    client = get_client()
    if client is not None:
        try:
            client.storage.from_(bucket).upload(object_path, data, {"content-type": content_type, "upsert": "true"})
            # Buckets are private (see migrations/003_rls.sql): store only the object
            # reference; mint a short-lived signed URL when the UI needs to display it.
            return f"{bucket}/{object_path}"
        except Exception as exc:  # noqa: BLE001
            logger.error("Supabase Storage upload failed for %s/%s: %s", bucket, object_path, exc)
            raise StorageError(f"Failed to upload to Supabase Storage: {exc}") from exc

    # Local fallback
    try:
        local_path = _local_fallback_path(f"{bucket}/{object_path}")
        local_path.write_bytes(data)
        return f"local://{bucket}/{object_path}"
    except OSError as exc:
        raise StorageError(f"Failed to write local fallback storage: {exc}") from exc


def create_signed_url(bucket: str, object_path: str, *, expires_in_seconds: int = 300) -> str | None:
    """Short-lived URL for displaying a private object. None if Supabase isn't configured."""
    client = get_client()
    if client is None:
        return None
    try:
        result = client.storage.from_(bucket).create_signed_url(object_path, expires_in_seconds)
        return result.get("signedURL") or result.get("signedUrl")
    except Exception as exc:  # noqa: BLE001
        logger.error("Signed URL creation failed for %s/%s: %s", bucket, object_path, exc)
        return None
