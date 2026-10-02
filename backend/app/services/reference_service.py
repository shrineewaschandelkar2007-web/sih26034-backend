"""
Reference-product lookups. Tries Supabase's `product_reference` table
first; if Supabase isn't configured (common during early local
development), falls back to a local JSON seed file so the demo flow
still works end-to-end.

IMPORTANT: the values in models_data/reference_products.seed.json are
PLACEHOLDERS with source_note="PLACEHOLDER" for every product except
Parle-G. Per spec section 28/13, real MRP/net-quantity/manufacturer
values must come from the team's own reference photos - never invent
them for a real product.
"""

import json

from app.core.config import BACKEND_ROOT, get_settings
from app.core.logging import get_logger
from app.schemas.product import ReferenceProduct

logger = get_logger(__name__)

_SEED_PATH = BACKEND_ROOT / "models_data" / "reference_products.seed.json"

_cache: list[ReferenceProduct] | None = None


def _load_local_seed() -> list[ReferenceProduct]:
    if not _SEED_PATH.exists():
        return []
    with open(_SEED_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return [ReferenceProduct(**row) for row in raw]


def list_reference_products() -> list[ReferenceProduct]:
    global _cache
    if _cache is not None:
        return _cache

    settings = get_settings()
    if settings.supabase_configured:
        try:
            from app.db.repositories.products import fetch_all_reference_products

            _cache = fetch_all_reference_products()
            return _cache
        except Exception as exc:  # noqa: BLE001
            logger.warning("Supabase reference lookup failed, falling back to local seed: %s", exc)

    _cache = _load_local_seed()
    return _cache


def get_by_barcode(barcode: str) -> ReferenceProduct | None:
    for product in list_reference_products():
        if product.barcode and product.barcode == barcode:
            return product
    return None


def known_brands() -> list[str]:
    return sorted({p.brand for p in list_reference_products() if p.brand})
