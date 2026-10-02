"""
Reads compliance_rules from the real Supabase table (operator/expected_value
model - see compliance_engine.py's module docstring). compliance_engine.py
currently reads from models_data/compliance_rules.json by default; swap
_load_rules() there to call fetch_active_rules() once the team has verified
the live table's rows match the JSON file's shape (or seed the table from
the JSON file - see scripts/seed_demo_products.py for the equivalent
product-seeding pattern; a rules-seeding script can follow the same shape).
"""

from datetime import date

from app.core.logging import get_logger
from app.db.supabase_client import get_client

logger = get_logger(__name__)


def fetch_active_rules() -> list[dict]:
    client = get_client()
    if client is None:
        return []
    try:
        response = client.table("compliance_rules").select("*").eq("is_active", True).execute()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch compliance rules from Supabase: %s", exc)
        return []

    rows = response.data or []
    today = date.today().isoformat()
    return [
        r
        for r in rows
        if (not r.get("effective_from") or r["effective_from"] <= today) and (not r.get("effective_to") or r["effective_to"] >= today)
    ]
