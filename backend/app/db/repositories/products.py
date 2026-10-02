from app.core.errors import DatabaseError
from app.core.logging import get_logger
from app.db.supabase_client import get_client
from app.schemas.product import ReferenceProduct

logger = get_logger(__name__)


def _row_to_reference_product(row: dict) -> ReferenceProduct:
    return ReferenceProduct(
        reference_product_id=row["reference_product_id"],
        brand=row.get("brand", ""),
        product_name=row.get("product_name", ""),
        barcode=row.get("barcode"),
        mrp=row.get("mrp"),
        net_weight=row.get("net_weight"),
        manufacturer=row.get("manufacturer"),
        batch_no=row.get("batch_no"),
        pkd=row.get("pkd"),
        best_before=row.get("best_before"),
        use_by=row.get("use_by"),
        reference_ocr_text=row.get("reference_ocr_text"),
        reference_fields_json=row.get("reference_fields_json"),
        reference_image=row.get("reference_image"),
        reference_image_url=row.get("reference_image_url"),
    )


def fetch_all_reference_products() -> list[ReferenceProduct]:
    client = get_client()
    if client is None:
        raise DatabaseError("Supabase client not available.")

    try:
        response = client.table("product_reference").select("*").execute()
    except Exception as exc:  # noqa: BLE001
        raise DatabaseError(f"Failed to fetch reference products: {exc}") from exc

    rows = response.data or []
    return [_row_to_reference_product(row) for row in rows]


def fetch_product_by_reference_id(reference_product_id: str) -> ReferenceProduct | None:
    client = get_client()
    if client is None:
        raise DatabaseError("Supabase client not available.")

    try:
        response = client.table("product_reference").select("*").eq("reference_product_id", reference_product_id).single().execute()
    except Exception as exc:  # noqa: BLE001
        logger.info("Product lookup for %s failed or not found: %s", reference_product_id, exc)
        return None

    row = response.data
    return _row_to_reference_product(row) if row else None


def insert_reference_product(product: dict) -> None:
    """Used by scripts/seed_demo_products.py. Checks for an existing row first -
    upsert isn't used here because we don't know whether `reference_product_id`
    has a unique constraint in the live database (only the column list was
    confirmed, not constraints)."""
    client = get_client()
    if client is None:
        raise DatabaseError("Supabase client not available.")

    existing = fetch_product_by_reference_id(product["reference_product_id"])
    if existing is not None:
        client.table("product_reference").update(product).eq("reference_product_id", product["reference_product_id"]).execute()
    else:
        client.table("product_reference").insert(product).execute()
