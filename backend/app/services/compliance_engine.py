"""
Deterministic, data-driven compliance engine.

Rules are loaded from models_data/compliance_rules.json.
This module evaluates evidence supplied by OCR, barcode, tampering,
field extraction and reference comparison.

Important prototype assumptions:
- `reference_match` means a reference product was identified.
- Reference comparison is useful evidence, but batch-specific fields
  such as manufacturing/packing/use-by dates should not by themselves
  make a product non-compliant.
- Mandatory declaration rules remain the primary compliance decision.
- This is a prototype and does not claim complete legal coverage.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date

from app.core.config import BACKEND_ROOT
from app.core.logging import get_logger
from app.schemas.compliance import ComplianceCheck, ComplianceResult
from app.schemas.product import ExtractedFields, ReferenceComparison
from app.schemas.tampering import TamperingResult

logger = get_logger(__name__)


ENGINE_VERSION = "compliance-engine-1.1.0"

_RULES_PATH = (
    BACKEND_ROOT
    / "models_data"
    / "compliance_rules.json"
)


# =========================================================
# FIELD PRESENCE
# =========================================================

_FIELD_PRESENT_MAP = {
    "mrp": lambda f: f.mrp.found,
    "net_quantity": lambda f: f.net_quantity.found,
    "manufacturer_address": lambda f: f.manufacturer_address.found,
    "manufacturing_date": lambda f: f.manufacturing_date.found,
    "use_by": lambda f: f.use_by.found,
    "best_before": lambda f: f.best_before.found,
    "consumer_care_contact": lambda f: f.consumer_care_contact.found,
}


# =========================================================
# OCR-DEPENDENT OPERATORS
# =========================================================

_TEXT_DEPENDENT_OPERATORS = {
    "field_present",
    "any_field_present",
    "min_declarations",
    "reference_field_match",
}


# =========================================================
# REFERENCE-COMPARISON FIELDS
# =========================================================

# These fields can legitimately vary between batches / production runs.
# A reference mismatch for these fields should not by itself cause
# REVIEW_REQUIRED or NON_COMPLIANT.
BATCH_SPECIFIC_REFERENCE_FIELDS = {
    "manufacturing_date",
    "packing_date",
    "use_by",
    "best_before",
}

# These fields are useful for consistency checking against a known
# reference product.
REFERENCE_RELEVANT_FIELDS = {
    "mrp",
    "net_quantity",
    "manufacturer",
}


# =========================================================
# RULE LOADING
# =========================================================

def _load_rules() -> list[dict]:
    if not _RULES_PATH.exists():
        logger.warning(
            "compliance_rules.json not found at %s - "
            "no rules will be evaluated.",
            _RULES_PATH,
        )
        return []

    with open(
        _RULES_PATH,
        encoding="utf-8",
    ) as f:
        rules = json.load(f)

    today = date.today().isoformat()

    active: list[dict] = []

    for rule in rules:

        if not rule.get("is_active", True):
            continue

        starts = rule.get("effective_from")
        ends = rule.get("effective_to")

        if starts and starts > today:
            continue

        if ends and ends < today:
            continue

        active.append(rule)

    return active


# =========================================================
# DECLARATION COUNT
# =========================================================

def _declaration_count(
    fields: ExtractedFields,
) -> int:
    return sum(
        1
        for check in _FIELD_PRESENT_MAP.values()
        if check(fields)
    )


# =========================================================
# RULE VERSION
# =========================================================

def _rules_version(
    rules: list[dict],
) -> str:

    versions = sorted(
        {
            str(rule.get("version", ""))
            for rule in rules
            if rule.get("version")
        }
    )

    if not versions:
        return "unversioned"

    if len(versions) == 1:
        return versions[0]

    return ",".join(versions)


# =========================================================
# TEXT NORMALIZATION
# =========================================================

def _normalize_text(value: str | None) -> str:
    """
    Normalize text for comparison.

    Examples that become equivalent:

        Parle Biscuits Pvt Ltd
        parle biscuits pvt. ltd.
        PARLE BISCUITS PVT LTD

    This is only used for reference consistency checking.
    """

    if not value:
        return ""

    value = value.lower()

    # Normalize common company abbreviations.
    value = re.sub(
        r"\bprivate\b",
        "pvt",
        value,
    )

    value = re.sub(
        r"\blimited\b",
        "ltd",
        value,
    )

    # Remove punctuation.
    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    # Collapse whitespace.
    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return value


def _manufacturer_matches_reference(
    live: str | None,
    reference: str | None,
) -> bool:

    live_normalized = _normalize_text(live)
    reference_normalized = _normalize_text(reference)

    if not live_normalized or not reference_normalized:
        return False

    return (
        live_normalized == reference_normalized
        or live_normalized in reference_normalized
        or reference_normalized in live_normalized
    )


# =========================================================
# RISK LEVEL
# =========================================================

def _risk_level(
    checks: list[ComplianceCheck],
) -> str:

    applicable = [
        check
        for check in checks
        if check.status != "NOT_APPLICABLE"
    ]

    issues = [
        check
        for check in applicable
        if check.status
        in (
            "FAIL",
            "REVIEW_REQUIRED",
        )
    ]

    if any(
        check.severity == "high"
        for check in issues
    ):
        return "HIGH"

    if any(
        check.severity == "medium"
        for check in issues
    ):
        return "MEDIUM"

    if any(
        check.severity == "low"
        for check in issues
    ):
        return "LOW"

    return "NONE"


# =========================================================
# EXPLANATION
# =========================================================

def _build_explanation(
    *,
    missing_fields: list[str],
    mismatched: dict,
    risk_level: str,
    ocr_succeeded: bool,
) -> str:

    if not ocr_succeeded:
        return (
            "Label text could not be read (OCR unavailable) - "
            "declaration checks were skipped for this scan."
        )

    parts: list[str] = []

    if missing_fields:
        parts.append(
            f"{len(missing_fields)} mandatory declaration(s) "
            f"missing: {', '.join(missing_fields)}."
        )

    if mismatched:
        parts.append(
            f"{len(mismatched)} field(s) do not match the "
            f"reference product: {', '.join(mismatched)}."
        )

    if not parts:
        parts.append(
            "All applicable declarations were found and "
            "passed the configured consistency checks."
        )

    parts.append(
        f"Overall risk level: {risk_level}."
    )

    return " ".join(parts)


# =========================================================
# COMPLIANCE EVALUATION
# =========================================================

def evaluate_compliance(
    *,
    fields: ExtractedFields,
    tampering: TamperingResult,
    reference_comparison: ReferenceComparison,
    reference_found: bool,
    ocr_succeeded: bool = True,
) -> ComplianceResult:
    """
    Evaluate deterministic compliance rules.

    Important behavior:

    1. Mandatory declarations remain compliance checks.
    2. Tampering remains a compliance signal.
    3. MRP / net quantity reference consistency remains useful.
    4. Manufacturer is compared using normalized text.
    5. Manufacturing/packing/use-by/best-before reference differences
       do NOT become compliance failures because these are batch/date
       values and can legitimately differ from a reference packet.
    """

    start = time.perf_counter()

    rules = _load_rules()

    checks: list[ComplianceCheck] = []
    missing_fields: list[str] = []

    # ---------------------------------------------------------
    # RULE EVALUATION
    # ---------------------------------------------------------

    for rule in rules:

        rule_id = rule["rule_code"]
        field_name = rule["field_name"]
        operator = rule["operator"]

        expected_value = rule.get(
            "expected_value"
        )

        severity = rule.get(
            "severity",
            "medium",
        )

        description = rule.get(
            "description",
            rule["rule_name"],
        )

        # -----------------------------------------------------
        # OCR unavailable
        # -----------------------------------------------------

        if (
            not ocr_succeeded
            and operator in _TEXT_DEPENDENT_OPERATORS
        ):

            checks.append(
                ComplianceCheck(
                    rule_id=rule_id,
                    field=field_name,
                    status="NOT_APPLICABLE",
                    message=(
                        "Could not be evaluated: text extraction "
                        "(OCR) was unavailable for this scan."
                    ),
                    severity=severity,
                )
            )

            continue

        # Default state.
        status = "NOT_APPLICABLE"

        message = (
            f"OK: {rule['rule_name']}."
        )

        # =====================================================
        # FIELD PRESENT
        # =====================================================

        if operator == "field_present":

            present = (
                _FIELD_PRESENT_MAP
                .get(
                    field_name,
                    lambda f: False,
                )
                (fields)
            )

            status = (
                "PASS"
                if present
                else "FAIL"
            )

            message = (
                f"OK: {rule['rule_name']}."
                if present
                else f"Issue: {description}"
            )

            if not present:
                missing_fields.append(
                    field_name
                )

        # =====================================================
        # ANY FIELD PRESENT
        # =====================================================

        elif operator == "any_field_present":

            candidate_fields = [
                field.strip()
                for field in (
                    expected_value or ""
                ).split(",")
                if field.strip()
            ]

            present = any(
                _FIELD_PRESENT_MAP
                .get(
                    field,
                    lambda f: False,
                )
                (fields)
                for field in candidate_fields
            )

            status = (
                "PASS"
                if present
                else "FAIL"
            )

            message = (
                f"OK: {rule['rule_name']}."
                if present
                else f"Issue: {description}"
            )

            if not present:
                missing_fields.append(
                    field_name
                )

        # =====================================================
        # MINIMUM DECLARATIONS
        # =====================================================

        elif operator == "min_declarations":

            count = _declaration_count(
                fields
            )

            threshold = (
                int(expected_value)
                if expected_value
                else 0
            )

            status = (
                "PASS"
                if count >= threshold
                else "FAIL"
            )

            message = (
                f"OK: {rule['rule_name']}."
                if count >= threshold
                else f"Issue: {description}"
            )

        # =====================================================
        # TAMPERING
        # =====================================================

        elif operator == "tampering_score_below":

            if (
                tampering.status != "success"
                or tampering.tampering_score is None
            ):

                status = "NOT_APPLICABLE"

                message = (
                    "Tampering evidence unavailable "
                    "for this scan."
                )

            else:

                threshold = (
                    float(expected_value)
                    if expected_value
                    else 0.55
                )

                below = (
                    tampering.tampering_score
                    < threshold
                )

                status = (
                    "PASS"
                    if below
                    else "REVIEW_REQUIRED"
                )

                message = (
                    f"OK: {rule['rule_name']}."
                    if below
                    else (
                        "Review required: "
                        f"{description}"
                    )
                )

        # =====================================================
        # REFERENCE FIELD MATCH
        # =====================================================

        elif operator == "reference_field_match":

            # -------------------------------------------------
            # No reference
            # -------------------------------------------------

            if not reference_comparison.available:

                status = "NOT_APPLICABLE"

                message = (
                    "No reference product available "
                    "for comparison."
                )

            # -------------------------------------------------
            # Batch-specific fields
            # -------------------------------------------------

            elif (
                expected_value
                in BATCH_SPECIFIC_REFERENCE_FIELDS
            ):

                status = "NOT_APPLICABLE"

                message = (
                    "Reference comparison skipped for "
                    f"batch-specific field '{expected_value}'. "
                    "The value may legitimately differ between "
                    "production batches."
                )

            else:

                entry = (
                    reference_comparison
                    .fields
                    .get(expected_value)
                )

                # ---------------------------------------------
                # No reference value
                # ---------------------------------------------

                if (
                    entry is None
                    or entry.status
                    == "NOT_AVAILABLE"
                ):

                    status = "NOT_APPLICABLE"

                    message = (
                        "Reference value not available "
                        "for this field."
                    )

                # ---------------------------------------------
                # Normal MATCH
                # ---------------------------------------------

                elif entry.status == "MATCH":

                    status = "PASS"

                    message = (
                        f"OK: {rule['rule_name']}."
                    )

                # ---------------------------------------------
                # Manufacturer normalization
                # ---------------------------------------------

                elif (
                    expected_value
                    == "manufacturer"
                    and _manufacturer_matches_reference(
                        entry.live,
                        entry.reference,
                    )
                ):

                    status = "PASS"

                    message = (
                        "OK: Manufacturer matches the "
                        "reference after text normalization."
                    )

                # ---------------------------------------------
                # Genuine mismatch
                # ---------------------------------------------

                else:

                    status = "REVIEW_REQUIRED"

                    message = (
                        "Review required: "
                        f"{description}"
                    )

        # -----------------------------------------------------
        # Append check
        # -----------------------------------------------------

        checks.append(
            ComplianceCheck(
                rule_id=rule_id,
                field=field_name,
                status=status,
                message=message,
                severity=severity,
            )
        )

    # =========================================================
    # OVERALL STATUS
    # =========================================================

    applicable = [
        check
        for check in checks
        if check.status != "NOT_APPLICABLE"
    ]

    failed_high = [
        check
        for check in applicable
        if (
            check.status == "FAIL"
            and check.severity == "high"
        )
    ]

    review_required = [
        check
        for check in applicable
        if check.status == "REVIEW_REQUIRED"
    ]

    if not ocr_succeeded:

        overall_status = "REVIEW_REQUIRED"

    elif failed_high:

        overall_status = "NON_COMPLIANT"

    elif (
        review_required
        or any(
            check.status == "FAIL"
            for check in applicable
        )
    ):

        overall_status = "REVIEW_REQUIRED"

    else:

        overall_status = "PASS"

    # =========================================================
    # REFERENCE FIELDS FOR RESPONSE
    # =========================================================

    matched_fields: dict = {}
    mismatched_fields: dict = {}

    for name, entry in (
        reference_comparison.fields.items()
    ):

        # Batch-specific reference differences are not treated
        # as compliance mismatches.
        if (
            name
            in BATCH_SPECIFIC_REFERENCE_FIELDS
        ):
            continue

        if entry.status == "MATCH":

            matched_fields[name] = (
                entry.model_dump()
            )

        elif entry.status == "MISMATCH":

            # Manufacturer gets a second normalized comparison.
            if (
                name == "manufacturer"
                and _manufacturer_matches_reference(
                    entry.live,
                    entry.reference,
                )
            ):

                normalized_entry = entry.model_copy(
                    update={
                        "match": True,
                        "status": "MATCH",
                    }
                )

                matched_fields[name] = (
                    normalized_entry.model_dump()
                )

            else:

                mismatched_fields[name] = (
                    entry.model_dump()
                )

    # =========================================================
    # RISK
    # =========================================================

    if ocr_succeeded:

        risk_level = _risk_level(
            checks
        )

    else:

        risk_level = (
            "HIGH"
            if failed_high
            else "MEDIUM"
        )

    # =========================================================
    # EXPLANATION
    # =========================================================

    explanation = _build_explanation(
        missing_fields=missing_fields,
        mismatched=mismatched_fields,
        risk_level=risk_level,
        ocr_succeeded=ocr_succeeded,
    )

    # =========================================================
    # WARNINGS
    # =========================================================

    warnings: list[str] = []

    if not ocr_succeeded:

        warnings.append(
            "Declaration checks could not be run because "
            "OCR was unavailable - rescan or review manually."
        )

    elif any(
        check.rule_id == "LM-006"
        and check.status == "FAIL"
        for check in checks
    ):

        warnings.append(
            "Near-zero declarations found - likely a "
            "completely unlabeled or non-compliant product."
        )

    # =========================================================
    # PROCESSING TIME
    # =========================================================

    processing_time_ms = int(
        (
            time.perf_counter()
            - start
        )
        * 1000
    )

    # =========================================================
    # FINAL RESULT
    # =========================================================

    return ComplianceResult(
        overall_status=overall_status,
        risk_level=risk_level,
        reference_match=reference_found,
        matched_fields=matched_fields,
        mismatched_fields=mismatched_fields,
        missing_fields=missing_fields,
        rule_results=checks,
        explanation=explanation,
        engine_version=ENGINE_VERSION,
        rules_version=_rules_version(
            rules
        ),
        processing_time_ms=processing_time_ms,
        warnings=warnings,
    )
