"""
Insert/update the demo reference products into the real `product_reference` table.

    python scripts/seed_demo_products.py            # reads models_data/reference_products.seed.json
    python scripts/seed_demo_products.py --dry-run  # show what would be written

Rows whose source_note starts with "PLACEHOLDER" have null MRP/net_weight/manufacturer on
purpose. Edit the JSON (or the table) with values read from YOUR reference photos before
the demo - never invent label values.
"""

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.repositories.products import insert_reference_product  # noqa: E402
from app.db.supabase_client import get_client  # noqa: E402

SEED_PATH = BACKEND_ROOT / "models_data" / "reference_products.seed.json"

# Columns the real product_reference table actually has - source_note is JSON-file-only.
_DB_COLUMNS = {
    "reference_product_id",
    "brand",
    "product_name",
    "barcode",
    "mrp",
    "net_weight",
    "manufacturer",
    "batch_no",
    "pkd",
    "best_before",
    "use_by",
    "reference_ocr_text",
    "reference_fields_json",
    "reference_image",
    "reference_image_url",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    placeholders = [r["reference_product_id"] for r in rows if str(r.get("source_note", "")).startswith("PLACEHOLDER")]

    print(f"{len(rows)} products in seed file; {len(placeholders)} are still PLACEHOLDERS:")
    for pid in placeholders:
        print(f"  - {pid}")

    if args.dry_run:
        print("Dry run - nothing written.")
        return 0

    if get_client() is None:
        print("Supabase is not configured (set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env). Nothing written.")
        return 1

    for row in rows:
        payload = {k: v for k, v in row.items() if k in _DB_COLUMNS and v is not None}
        insert_reference_product(payload)
    print(f"Upserted {len(rows)} products into product_reference.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
