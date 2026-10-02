"""
Persists the per-scan detail rows. Column names below match the real
DB exactly - no separate `field_extractions` / `reference_comparisons`
/ `compliance_checks` tables exist in the live schema:

  - extracted fields go into ocr_results.structured_data (jsonb)
  - reference comparison detail folds into compliance_results'
    matched_fields / mismatched_fields
  - individual rule outcomes go into compliance_results.rule_results
    (jsonb list), not a child table
"""

from app.core.logging import get_logger
from app.db.supabase_client import get_client

logger = get_logger(__name__)


def save_ocr_result(
    scan_id: int,
    *,
    raw_text: str,
    confidence: float | None,
    structured_data: dict,
) -> None:
    client = get_client()

    if client is None:
        logger.warning(
            "Supabase unavailable - ocr_results not persisted for scan %s.",
            scan_id,
        )
        return

    try:
        client.table("ocr_results").insert(
            {
                "scan_id": scan_id,
                "raw_text": raw_text,
                "confidence": confidence,
                "structured_data": structured_data,
            }
        ).execute()

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to persist ocr_results for scan %s: %s",
            scan_id,
            exc,
        )


def save_barcode_result(
    scan_id: int,
    *,
    barcode: str | None,
    detected: bool,
    confidence: float | None,
) -> None:
    client = get_client()

    if client is None:
        logger.warning(
            "Supabase unavailable - barcode_results not persisted for scan %s.",
            scan_id,
        )
        return

    try:
        client.table("barcode_results").insert(
            {
                "scan_id": scan_id,
                "barcode": barcode,
                "detected": detected,
                "confidence": confidence,
            }
        ).execute()

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to persist barcode_results for scan %s: %s",
            scan_id,
            exc,
        )


def save_tampering_result(
    scan_id: int,
    *,
    tampering_score: float | None,
    status: str,
    heatmap_path: str | None,
) -> None:
    client = get_client()

    if client is None:
        logger.warning(
            "Supabase unavailable - tampering_results not persisted for scan %s.",
            scan_id,
        )
        return

    try:
        client.table("tampering_results").insert(
            {
                "scan_id": scan_id,
                "tampering_score": tampering_score,
                "status": status,
                "heatmap_path": heatmap_path,
            }
        ).execute()

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to persist tampering_results for scan %s: %s",
            scan_id,
            exc,
        )


def save_compliance_result(scan_id: int, compliance: dict) -> None:
    """
    Persist the final ComplianceResult.

    The incoming `compliance` dictionary is expected to come from
    ComplianceResult.model_dump().

    Live DB constraints:

    overall_status:
        processing
        compliant
        non_compliant
        review_required
        failed

    risk_level:
        low
        medium
        high
        NULL

    The compliance engine may use internal values such as:

        PASS
        COMPLIANT
        NON_COMPLIANT
        REVIEW_REQUIRED
        PROCESSING
        FAILED

    Those values are normalized here before inserting into Supabase.
    """

    client = get_client()

    if client is None:
        logger.warning(
            "Supabase unavailable - compliance_results not persisted for scan %s.",
            scan_id,
        )
        return

    try:
        db_compliance = dict(compliance)

        # =========================================================
        # FIX 1: overall_status mapping
        # =========================================================

        overall_status = db_compliance.get("overall_status")

        if isinstance(overall_status, str):
            normalized_status = overall_status.strip().upper()

            status_map = {
                # Successful compliance result
                "PASS": "compliant",
                "COMPLIANT": "compliant",

                # Non-compliant result
                "NON_COMPLIANT": "non_compliant",

                # Manual / uncertain review
                "REVIEW_REQUIRED": "review_required",

                # Processing state
                "PROCESSING": "processing",

                # Failed processing
                "FAILED": "failed",
            }

            overall_status = status_map.get(
                normalized_status,
                "review_required",
            )

        else:
            overall_status = "review_required"

        db_compliance["overall_status"] = overall_status

        # =========================================================
        # FIX 2: risk_level mapping
        # =========================================================

        risk_level = db_compliance.get("risk_level")

        if isinstance(risk_level, str):
            normalized_risk = risk_level.strip().upper()

            risk_map = {
                "NONE": None,
                "LOW": "low",
                "MEDIUM": "medium",
                "HIGH": "high",
            }

            risk_level = risk_map.get(
                normalized_risk,
                None,
            )

        elif risk_level is not None:
            # Unexpected non-string value
            risk_level = None

        db_compliance["risk_level"] = risk_level

        # =========================================================
        # Persist final compliance result
        # =========================================================

        client.table("compliance_results").insert(
            {
                "scan_id": scan_id,
                **db_compliance,
            }
        ).execute()

        logger.info(
            "Compliance result persisted successfully for scan %s "
            "(status=%s, risk=%s).",
            scan_id,
            overall_status,
            risk_level,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to persist compliance_results for scan %s: %s",
            scan_id,
            exc,
        )