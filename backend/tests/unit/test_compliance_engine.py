from app.schemas.product import ExtractedFields, ExtractedFieldValue, FieldComparisonEntry, ReferenceComparison
from app.schemas.tampering import TamperingResult
from app.services import compliance_engine


def _found(raw="x", value=None):
    return ExtractedFieldValue(found=True, raw=raw, value=value)


def _complete_fields() -> ExtractedFields:
    f = ExtractedFields()
    f.mrp = _found("30.00", 30.0)
    f.net_quantity = _found("250 g", 250.0)
    f.manufacturer_address = _found("parle biscuits pvt ltd")
    f.manufacturing_date = _found("8/8/26")
    f.consumer_care_contact = _found("1800 209 6929")
    return f


CLEAN_TAMPERING = TamperingResult(status="success", tampering_score=0.05, anomaly_detected=False)
NO_REFERENCE = ReferenceComparison(available=False, fields={})


def _by_id(result):
    return {c.rule_id: c for c in result.rule_results}


def _evaluate(**overrides):
    kwargs = dict(
        fields=_complete_fields(),
        tampering=CLEAN_TAMPERING,
        reference_comparison=NO_REFERENCE,
        reference_found=False,
    )
    kwargs.update(overrides)
    return compliance_engine.evaluate_compliance(**kwargs)


def test_fully_declared_product_passes():
    result = _evaluate()
    assert result.overall_status == "PASS"
    assert result.risk_level == "NONE"
    assert result.missing_fields == []
    assert result.reference_match is False  # no reference product was identified


def test_missing_mrp_is_non_compliant():
    fields = _complete_fields()
    fields.mrp = ExtractedFieldValue(found=False)
    result = _evaluate(fields=fields)
    assert result.overall_status == "NON_COMPLIANT"
    assert result.risk_level == "HIGH"
    assert "mrp" in result.missing_fields
    assert _by_id(result)["LM-001"].status == "FAIL"


def test_completely_unlabeled_product_raises_high_risk_flag():
    result = _evaluate(fields=ExtractedFields())
    assert result.overall_status == "NON_COMPLIANT"
    assert _by_id(result)["LM-006"].status == "FAIL"
    assert any("unlabeled" in w.lower() for w in result.warnings)


def test_any_date_field_satisfies_date_rule():
    fields = _complete_fields()
    fields.manufacturing_date = ExtractedFieldValue(found=False)
    fields.use_by = _found("5/1/27")
    result = _evaluate(fields=fields)
    assert _by_id(result)["LM-004"].status == "PASS"


def test_tampering_above_threshold_requires_review_not_fail():
    suspicious = TamperingResult(status="success", tampering_score=0.9, anomaly_detected=True)
    result = _evaluate(tampering=suspicious)
    assert _by_id(result)["TP-001"].status == "REVIEW_REQUIRED"
    assert result.overall_status == "REVIEW_REQUIRED"
    assert result.risk_level == "HIGH"


def test_unavailable_tampering_is_not_applicable_rather_than_pass():
    result = _evaluate(tampering=TamperingResult(status="unavailable"))
    assert _by_id(result)["TP-001"].status == "NOT_APPLICABLE"


def test_reference_mismatch_triggers_review_and_lands_in_mismatched_fields():
    comparison = ReferenceComparison(
        available=True,
        fields={
            "mrp": FieldComparisonEntry(live=35.0, reference=30.0, match=False, status="MISMATCH"),
            "net_quantity": FieldComparisonEntry(live="250 g", reference="250 g", match=True, status="MATCH"),
        },
    )
    result = _evaluate(reference_comparison=comparison, reference_found=True)
    assert _by_id(result)["REF-001"].status == "REVIEW_REQUIRED"
    assert _by_id(result)["REF-002"].status == "PASS"
    assert result.overall_status == "REVIEW_REQUIRED"
    assert "mrp" in result.mismatched_fields
    assert "net_quantity" in result.matched_fields
    assert result.reference_match is True


def test_reference_rules_not_applicable_without_reference():
    result = _evaluate()
    assert _by_id(result)["REF-001"].status == "NOT_APPLICABLE"
    assert _by_id(result)["REF-002"].status == "NOT_APPLICABLE"


def test_reference_match_reflects_product_identification_not_field_agreement():
    # A reference WAS found, even though every compared field mismatches.
    comparison = ReferenceComparison(
        available=True,
        fields={"mrp": FieldComparisonEntry(live=99.0, reference=30.0, match=False, status="MISMATCH")},
    )
    result = _evaluate(reference_comparison=comparison, reference_found=True)
    assert result.reference_match is True
    assert "mrp" in result.mismatched_fields


def test_engine_is_deterministic():
    first = _evaluate().model_dump(exclude={"processing_time_ms"})
    second = _evaluate().model_dump(exclude={"processing_time_ms"})
    assert first == second


def test_ocr_outage_is_never_reported_as_a_violation():
    # Regression: an unavailable OCR must never read as "NON_COMPLIANT - likely unlabeled".
    result = _evaluate(fields=ExtractedFields(), ocr_succeeded=False)
    assert result.overall_status == "REVIEW_REQUIRED"
    statuses = {c.rule_id: c.status for c in result.rule_results}
    assert statuses["LM-001"] == "NOT_APPLICABLE"
    assert statuses["LM-006"] == "NOT_APPLICABLE"
    assert result.missing_fields == []
    assert any("OCR was unavailable" in w for w in result.warnings)
    assert not any("unlabeled" in w.lower() for w in result.warnings)


def test_ocr_outage_does_not_hide_tampering_evidence():
    suspicious = TamperingResult(status="success", tampering_score=0.9, anomaly_detected=True)
    result = _evaluate(fields=ExtractedFields(), tampering=suspicious, ocr_succeeded=False)
    assert {c.rule_id: c.status for c in result.rule_results}["TP-001"] == "REVIEW_REQUIRED"


def test_output_carries_engine_and_rules_version():
    result = _evaluate()
    assert result.engine_version
    assert result.rules_version == "1"  # every seeded rule is version "1"


def test_explanation_mentions_missing_fields():
    fields = _complete_fields()
    fields.mrp = ExtractedFieldValue(found=False)
    result = _evaluate(fields=fields)
    assert "mrp" in result.explanation.lower()
