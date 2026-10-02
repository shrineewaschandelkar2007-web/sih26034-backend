from datetime import UTC, datetime

from app.core.errors import DatabaseError
from app.core.logging import get_logger
from app.db.supabase_client import get_client

logger = get_logger(__name__)


def create_scan_record(
    *,
    image_path: str | None,
    image_url: str | None,
    detected_barcode: str | None,
    detected_product_name: str | None,
    detected_brand: str | None,
    reference_product_id: str | None,
    ocr_confidence: float | None,
    tampering_score: float | None,
    status: str,
) -> int | None:
    """
    Inserts one row into `scan_records` and returns its auto-generated
    bigint `id` - this id becomes the scan_id used by every other
    *_results table. Returns None (rather than raising) when Supabase
    isn't configured, so the pipeline still runs without persistence.
    """
    client = get_client()
    if client is None:
        logger.warning("Supabase unavailable - scan not persisted to scan_records.")
        return None

    payload = {
        "image_path": image_path,
        "image_url": image_url,
        "detected_barcode": detected_barcode,
        "detected_product_name": detected_product_name,
        "detected_brand": detected_brand,
        "reference_product_id": reference_product_id,
        "ocr_confidence": ocr_confidence,
        "tampering_score": tampering_score,
        "status": status,
        "created_at": datetime.now(UTC).isoformat(),
    }
    try:
        response = client.table("scan_records").insert(payload).execute()
        rows = response.data or []
        return rows[0]["id"] if rows else None
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(f"Failed to insert scan_records row: {exc}") from exc


def get_scan(scan_id: int) -> dict | None:
    client = get_client()
    if client is None:
        return None

    try:
        response = client.table("scan_records").select("*").eq("id", scan_id).single().execute()
        return response.data
    except Exception as exc:  # noqa: BLE001
        logger.info("Scan %s not found or lookup failed: %s", scan_id, exc)
        return None


def list_recent_scans(limit: int = 50) -> list[dict]:
    client = get_client()
    if client is None:
        return []

    try:
        response = client.table("scan_records").select("*").order("created_at", desc=True).limit(limit).execute()
        return response.data or []
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to list recent scans: %s", exc)
        return []
