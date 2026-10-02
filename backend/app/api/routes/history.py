from fastapi import APIRouter, Query

from app.db.repositories import scans as scans_repo
from app.schemas.scan import ScanHistoryItem

router = APIRouter(prefix="/api/v1", tags=["history"])


@router.get("/scans", response_model=list[ScanHistoryItem])
def list_scan_history(limit: int = Query(default=50, le=200)):
    """
    Scan/audit history (spec section 15 step 16, section 32 checklist).
    Returns an empty list rather than erroring when Supabase isn't
    configured yet - history is a nice-to-have, not a blocker for the
    core /scans pipeline.
    """
    rows = scans_repo.list_recent_scans(limit=limit)
    return [
        ScanHistoryItem(
            scan_id=str(row.get("id", "")),
            created_at=row.get("created_at", ""),
            product_name=row.get("detected_product_name"),
            reference_found=bool(row.get("reference_product_id")),
            compliance_status=row.get("status"),
        )
        for row in rows
    ]
