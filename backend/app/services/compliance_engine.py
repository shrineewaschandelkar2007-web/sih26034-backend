"""
The compliance engine is deterministic and data-driven: rules live in
models_data/compliance_rules.json (mirrors the real `compliance_rules`
table - columns: rule_code, rule_name, category, field_name, operator,
expected_value, severity, description, source_reference, source_url,
effective_from, effective_to, version, is_active). This module only
*evaluates* them - it never hard-codes business logic in scattered
if/else blocks (spec 30.11).

Inputs are pure evidence from the model layer (OCR fields, barcode,
tampering score, reference comparison) - the AI components never
decide compliance themselves (spec section 1).

Output shape mirrors the real `compliance_results` table exactly
(overall_status, risk_level, reference_match, matched_fields,
mismatched_fields, missing_fields, rule_results, explanation,
engine_version, rules_version, processing_time_ms) so
app/db/repositories/results.py can persist it with no translation.

ASSUMPTIONS made because the DB schema doesn't fully specify semantics
(documented here, and in README, so the team can correct them):
  - `reference_match` = a reference product was identified for this
    scan (ProductMatch.reference_found), NOT "every compared field
    matched". Field-level agreement is what matched_fields/
    mismatched_fields are for.
  - `risk_level` is a 4-step scale (NONE/LOW/MEDIUM/HIGH) derived from
    the severities of failed/review-required checks - there was no
    existing rule data to infer this from.

IMPORTANT (spec section 10 / 30.10): this prototype implements a
useful but partial subset of Legal Metrology (Packaged Commodities)
Rules, 2011. It does not claim legal completeness.
"""

import json
import time
from datetime import date

from app.core.config import BACKEND_ROOT
from app.core.logging import get_logger
from app.schemas.compliance import ComplianceCheck, ComplianceResult
from app.schemas.product import ExtractedFields, ReferenceComparison
from app.schemas.tampering import TamperingResult

logger = get_logger(__name__)

ENGINE_VERSION = "compliance-engine-1.0.0"

_RULES_PATH = BACKEND_ROOT / "models_data" / "compliance_rules.json"

_FIELD_PRESENT_MAP = {
    "mrp": lambda f: f.mrp.found,
    "net_quantity": lambda f: f.net_quantity.found,
    "manufacturer_address": lambda f: f.manufacturer_address.found,
    "manufacturing_date": lambda f: f.manufacturing_date.found,
    "use_by": lambda f: f.use_by.found,
    "best_before": lambda f: f.best_before.found,
    "consumer_care_contact": lambda f: f.consumer_care_contact.found,
}

_TEXT_DEPENDENT_OPERATORS = {"field_present", "any_field_present", "min_declarations", "reference_field_match"}


def _load_rules() -> list[dict]:
    if not _RULES_PATH.exists():
        logger.warning("compliance_rules.json not found at %s - no rules will be evaluated.", _RULES_PATH)
        return []
    with open(_RULES_PATH, encoding="utf-8") as f:
        rules = json.load(f)

    today = date.today().isoformat()
    active = []
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


def _declaration_count(fields: ExtractedFields) -> int:
    return sum(1 for check in _FIELD_PRESENT_MAP.values() if check(fields))


def _rules_version(rules: list[dict]) -> str:
    versions = sorted({str(r.get("version", "")) for r in rules if r.get("version")})
    if not versions:
        return "unversioned"
    return versions[0] if len(versions) == 1 else ",".join(versions)


def _risk_level(checks: list[ComplianceCheck]) -> str:
    applicable = [c for c in checks if c.status != "NOT_APPLICABLE"]
    issues = [c for c in applicable if c.status in ("FAIL", "REVIEW_REQUIRED")]
    if any(c.severity == "high" for c in issues):
        return "HIGH"
    if any(c.severity == "medium" for c in issues):
        return "MEDIUM"
    if any(c.severity == "low" for c in issues):
        return "LOW"
    return "NONE"


def _build_explanation(*, missing_fields: list[str], mismatched: dict, risk_level: str, ocr_succeeded: bool) -> str:
    if not ocr_succeeded:
        return "Label text could not be read (OCR unavailable) - declaration checks were skipped for this scan."

    parts = []
    if missing_fields:
        parts.append(f"{len(missing_fields)} mandatory declaration(s) missing: {', '.join(missing_fields)}.")
    if mismatched:
        parts.append(f"{len(mismatched)} field(s) do not match the reference product: {', '.join(mismatched)}.")
    if not parts:
        parts.append("All applicable declarations were found and, where checked, matched the reference product.")
    parts.append(f"Overall risk level: {risk_level}.")
    return " ".join(parts)


def evaluate_compliance(
    *,
    fields: ExtractedFields,
    tampering: TamperingResult,
    reference_comparison: ReferenceComparison,
    reference_found: bool,
    ocr_succeeded: bool = True,
) -> ComplianceResult:
    """
    `ocr_succeeded=False` means the text-reading stage itself failed or
    was unavailable. Declaration-based rules then become NOT_APPLICABLE
    instead of FAIL: an outage in OUR pipeline must never be reported
    as a violation by the product (that would falsely accuse a
    compliant seller).
    """
    start = time.perf_counter()
    rules = _load_rules()
    checks: list[ComplianceCheck] = []
    missing_fields: list[str] = []

    for rule in rules:
        rule_id = rule["rule_code"]
        field_name = rule["field_name"]
        operator = rule["operator"]
        expected_value = rule.get("expected_value")
        severity = rule.get("severity", "medium")
        description = rule.get("description", rule["rule_name"])

        if not ocr_succeeded and operator in _TEXT_DEPENDENT_OPERATORS:
            checks.append(
                ComplianceCheck(
                    rule_id=rule_id,
                    field=field_name,
                    status="NOT_APPLICABLE",
                    message="Could not be evaluated: text extraction (OCR) was unavailable for this scan.",
                    severity=severity,
                )
            )
            continue

        status = "NOT_APPLICABLE"
        message = f"OK: {rule['rule_name']}."

        if operator == "field_present":
            present = _FIELD_PRESENT_MAP.get(field_name, lambda f: False)(fields)
            status = "PASS" if present else "FAIL"
            message = f"OK: {rule['rule_name']}." if present else f"Issue: {description}"
            if not present:
                missing_fields.append(field_name)

        elif operator == "any_field_present":
            candidate_fields = [f.strip() for f in (expected_value or "").split(",") if f.strip()]
            present = any(_FIELD_PRESENT_MAP.get(f, lambda x: False)(fields) for f in candidate_fields)
            status = "PASS" if present else "FAIL"
            message = f"OK: {rule['rule_name']}." if present else f"Issue: {description}"
            if not present:
                missing_fields.append(field_name)

        elif operator == "min_declarations":
            count = _declaration_count(fields)
            threshold = int(expected_value) if expected_value else 0
            status = "PASS" if count >= threshold else "FAIL"
            message = f"OK: {rule['rule_name']}." if count >= threshold else f"Issue: {description}"

        elif operator == "tampering_score_below":
            if tampering.status != "success" or tampering.tampering_score is None:
                status = "NOT_APPLICABLE"
                message = "Tampering evidence unavailable for this scan."
            else:
                threshold = float(expected_value) if expected_value else 0.55
                below = tampering.tampering_score < threshold
                status = "PASS" if below else "REVIEW_REQUIRED"
                message = f"OK: {rule['rule_name']}." if below else f"Review required: {description}"

        elif operator == "reference_field_match":
            if not reference_comparison.available:
                status = "NOT_APPLICABLE"
                message = "No reference product available for comparison."
            else:
                entry = reference_comparison.fields.get(expected_value)
                if entry is None or entry.status == "NOT_AVAILABLE":
                    status = "NOT_APPLICABLE"
                    message = "Reference value not available for this field."
                elif entry.status == "MATCH":
                    status = "PASS"
                    message = f"OK: {rule['rule_name']}."
                else:
                    status = "REVIEW_REQUIRED"
                    message = f"Review required: {description}"

        checks.append(ComplianceCheck(rule_id=rule_id, field=field_name, status=status, message=message, severity=severity))

    applicable = [c for c in checks if c.status != "NOT_APPLICABLE"]
    failed_high = [c for c in applicable if c.status == "FAIL" and c.severity == "high"]
    review_required = [c for c in applicable if c.status == "REVIEW_REQUIRED"]

    if not ocr_succeeded:
        overall_status = "REVIEW_REQUIRED"
    elif failed_high:
        overall_status = "NON_COMPLIANT"
    elif review_required or any(c.status == "FAIL" for c in applicable):
        overall_status = "REVIEW_REQUIRED"
    else:
        overall_status = "PASS"

    matched_fields = {name: entry.model_dump() for name, entry in reference_comparison.fields.items() if entry.status == "MATCH"}
    mismatched_fields = {name: entry.model_dump() for name, entry in reference_comparison.fields.items() if entry.status == "MISMATCH"}

    risk_level = _risk_level(checks) if ocr_succeeded else ("HIGH" if failed_high else "MEDIUM")
    explanation = _build_explanation(
        missing_fields=missing_fields, mismatched=mismatched_fields, risk_level=risk_level, ocr_succeeded=ocr_succeeded
    )

    warnings: list[str] = []
    if not ocr_succeeded:
        warnings.append("Declaration checks could not be run because OCR was unavailable - rescan or review manually.")
    elif any(c.rule_id == "LM-006" and c.status == "FAIL" for c in checks):
        warnings.append("Near-zero declarations found - likely a completely unlabeled or non-compliant product.")

    processing_time_ms = int((time.perf_counter() - start) * 1000)

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
        rules_version=_rules_version(rules),
        processing_time_ms=processing_time_ms,
        warnings=warnings,
    )
