from pydantic import BaseModel


class ComplianceCheck(BaseModel):
    """One evaluated rule. A list of these (as dicts) is what gets stored in compliance_results.rule_results."""

    rule_id: str
    field: str
    status: str  # "PASS" | "FAIL" | "REVIEW_REQUIRED" | "NOT_APPLICABLE"
    message: str
    severity: str = "medium"  # "low" | "medium" | "high"


class ComplianceResult(BaseModel):
    """Mirrors the real DB table `compliance_results` column-for-column."""

    overall_status: str  # "PASS" | "REVIEW_REQUIRED" | "NON_COMPLIANT"
    risk_level: str  # "NONE" | "LOW" | "MEDIUM" | "HIGH" - derived from rule_results, see compliance_engine.py
    reference_match: bool  # a reference product was identified for this scan (not "every field matched")
    matched_fields: dict[str, dict] = {}
    mismatched_fields: dict[str, dict] = {}
    missing_fields: list[str] = []
    rule_results: list[ComplianceCheck] = []
    explanation: str = ""
    engine_version: str = ""
    rules_version: str = ""
    processing_time_ms: int = 0
    warnings: list[str] = []  # not a DB column - carried in the API response only, dropped before persisting
