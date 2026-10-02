"""
End-to-end tests of POST /api/v1/scans.

OCR is monkeypatched with canned text so these tests are deterministic and
do not depend on PaddleOCR model weights being downloadable (they are not,
e.g., in a sandbox without internet). The canned text is real PaddleOCR
output captured from the team's Parle-G packet. Barcode decoding and the
tampering heuristic run for real against the fixture images.

No Supabase credentials are configured in this test environment, so
scan_records is never actually written - `scan_id` in every response here
is the per-request fallback id (see app/api/routes/scan.py), not a real
bigint. tests/integration/test_supabase_repository.py covers the
persistence-layer column mapping separately with a fake client.
"""

from app.api.routes import scan as scan_route
from app.core.config import get_settings
from app.schemas.ocr import OCRResult

PARLE_G_TEXT = """NET WEIGHT:
200 g+50  EXTRA=250
MRP₹30.00 (0.15/g)
INCL OF ALL TAXES
PARLE
Parle-G
MFD.BY:
(P)-PARLEBISCUTSPVT LTD.3.SEC.1
CONSUMER CARE CELL
PHONE NO.: 1800 209 6929
USE BY: 5/1/27
PKD: 8/8/26"""

UNKNOWN_PRODUCT_TEXT = "LOCAL BANANA CHIPS\nMRP Rs 20"


def _ocr_returning(text: str):
    def fake(_image):
        return OCRResult(status="success", combined_text=text, average_confidence=0.95)

    return fake


def _post(client, image_bytes, name="label.png", mode="consumer"):
    return client.post(f"/api/v1/scans?mode={mode}", files={"file": (name, image_bytes, "image/png")})


def test_known_product_flow_matches_reference_and_passes(client, sample_label_bytes, monkeypatch):
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", _ocr_returning(PARLE_G_TEXT))
    r = _post(client, sample_label_bytes, mode="inspector")
    assert r.status_code == 200
    body = r.json()

    assert body["status"] == "completed"
    assert body["mode"] == "inspector"
    assert body["barcode"]["found"] is True
    assert body["barcode"]["value"] == "8901719123870"

    assert body["product"]["reference_found"] is True
    assert body["product"]["match_method"] == "barcode"
    assert body["product"]["name"] == "Parle-G"

    fields = body["reference_comparison"]["fields"]
    assert body["reference_comparison"]["available"] is True
    assert fields["mrp"]["status"] == "MATCH"
    assert fields["net_quantity"]["status"] == "MATCH"

    assert body["extracted_fields"]["mrp"]["value"] == 30.0
    assert body["extracted_fields"]["net_quantity"]["value"] == 250.0

    compliance = body["compliance"]
    assert compliance["overall_status"] == "PASS"
    assert compliance["risk_level"] == "NONE"
    assert compliance["reference_match"] is True
    assert "mrp" in compliance["matched_fields"]


def test_unknown_product_flow_still_returns_extraction_and_rule_results(client, unlabeled_bytes, monkeypatch):
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", _ocr_returning(UNKNOWN_PRODUCT_TEXT))
    r = _post(client, unlabeled_bytes)
    assert r.status_code == 200
    body = r.json()

    assert body["product"]["reference_found"] is False
    assert body["reference_comparison"]["available"] is False
    assert body["barcode"]["found"] is False
    # extraction still happens even though there is no reference record
    assert body["extracted_fields"]["mrp"]["value"] == 20.0
    # rules still run on whatever was found, and missing declarations are reported
    assert body["compliance"]["overall_status"] == "NON_COMPLIANT"
    assert "net_quantity" in body["compliance"]["missing_fields"]
    assert body["compliance"]["reference_match"] is False
    assert any("reference" in w.lower() for w in body["warnings"])


def test_completely_unlabeled_product_is_flagged_high_risk(client, unlabeled_bytes, monkeypatch):
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", _ocr_returning(""))
    body = _post(client, unlabeled_bytes).json()
    checks = {c["rule_id"]: c for c in body["compliance"]["rule_results"]}
    assert checks["LM-006"]["status"] == "FAIL"
    assert body["compliance"]["overall_status"] == "NON_COMPLIANT"
    assert body["compliance"]["risk_level"] == "HIGH"


def test_ocr_failure_degrades_gracefully_instead_of_500(client, sample_label_bytes, monkeypatch):
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", lambda _img: OCRResult(status="failed", error_message="boom"))
    r = _post(client, sample_label_bytes)
    assert r.status_code == 200
    body = r.json()
    assert body["ocr"]["status"] == "failed"
    assert any("OCR" in w for w in body["warnings"])
    # the barcode path is independent of OCR, so the product is still identified
    assert body["product"]["reference_found"] is True
    # OCR being down is OUR failure: it must not be reported as the product being non-compliant/unlabeled.
    assert body["compliance"]["overall_status"] == "REVIEW_REQUIRED"
    assert not any("unlabeled" in w.lower() for w in body["warnings"])


def test_barcode_missing_is_a_warning_not_an_error(client, unlabeled_bytes, monkeypatch):
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", _ocr_returning(PARLE_G_TEXT))
    body = _post(client, unlabeled_bytes).json()
    assert body["barcode"]["found"] is False
    assert any("barcode" in w.lower() for w in body["warnings"])


def test_tampering_stage_exception_degrades_to_failed_status(client, sample_label_bytes, monkeypatch):
    def explode(_image):
        raise RuntimeError("tampering model crashed")

    monkeypatch.setattr(scan_route.tampering_service, "run_tampering_check", explode)
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", _ocr_returning(PARLE_G_TEXT))

    r = _post(client, sample_label_bytes)
    assert r.status_code == 200
    body = r.json()
    assert body["tampering"]["status"] == "failed"
    checks = {c["rule_id"]: c for c in body["compliance"]["rule_results"]}
    assert checks["TP-001"]["status"] == "NOT_APPLICABLE"


def test_barcode_stage_exception_degrades_gracefully(client, sample_label_bytes, monkeypatch):
    def explode(_image):
        raise RuntimeError("decoder crashed")

    monkeypatch.setattr(scan_route.barcode_service, "run_barcode_scan", explode)
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", _ocr_returning(PARLE_G_TEXT))

    r = _post(client, sample_label_bytes)
    assert r.status_code == 200
    assert r.json()["barcode"]["found"] is False


def test_invalid_upload_returns_stable_error_shape(client):
    r = client.post("/api/v1/scans", files={"file": ("x.txt", b"not an image", "text/plain")})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "INVALID_IMAGE"
    assert "Traceback" not in r.text


def test_oversized_upload_rejected_with_413(client, sample_label_bytes, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_size_mb", 0)
    r = _post(client, sample_label_bytes)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "IMAGE_TOO_LARGE"


def test_invalid_mode_rejected(client, sample_label_bytes):
    r = client.post("/api/v1/scans?mode=hacker", files={"file": ("a.png", sample_label_bytes, "image/png")})
    assert r.status_code == 422


def test_response_has_stable_top_level_keys(client, sample_label_bytes, monkeypatch):
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", _ocr_returning(PARLE_G_TEXT))
    body = _post(client, sample_label_bytes).json()
    for key in (
        "scan_id",
        "status",
        "product",
        "ocr",
        "barcode",
        "tampering",
        "extracted_fields",
        "reference_comparison",
        "compliance",
        "warnings",
    ):
        assert key in body
    for key in (
        "overall_status",
        "risk_level",
        "reference_match",
        "matched_fields",
        "mismatched_fields",
        "missing_fields",
        "rule_results",
        "explanation",
        "engine_version",
        "rules_version",
        "processing_time_ms",
    ):
        assert key in body["compliance"]


def test_every_scan_gets_a_unique_id_even_for_identical_uploads(client, sample_label_bytes, monkeypatch):
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", _ocr_returning(PARLE_G_TEXT))
    ids = {_post(client, sample_label_bytes).json()["scan_id"] for _ in range(3)}
    assert len(ids) == 3


def test_raw_ocr_text_is_preserved_in_response(client, sample_label_bytes, monkeypatch):
    monkeypatch.setattr(scan_route.ocr_service, "run_ocr", _ocr_returning(PARLE_G_TEXT))
    body = _post(client, sample_label_bytes).json()
    assert "PHONE NO.: 1800 209 6929" in body["ocr"]["combined_text"]


def test_history_and_scan_lookup_do_not_crash_without_supabase(client):
    assert client.get("/api/v1/scans").status_code == 200
    r = client.get("/api/v1/scans/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_scan_lookup_rejects_non_numeric_id_cleanly(client):
    r = client.get("/api/v1/scans/not-a-number")
    assert r.status_code == 404


def test_product_endpoints(client):
    r = client.get("/api/v1/products/search?q=parle")
    assert r.status_code == 200
    assert {p["product_name"] for p in r.json()} >= {"Monaco", "Parle-G"}
    assert client.get("/api/v1/products/demo-parle-g-003").status_code == 200
    assert client.get("/api/v1/products/nope").status_code == 404
