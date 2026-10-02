from app.schemas.product import ExtractedFields, ExtractedFieldValue, ReferenceProduct
from app.services import product_matcher


def _reference(**overrides) -> ReferenceProduct:
    data = dict(
        reference_product_id="p1",
        brand="Parle",
        product_name="Parle-G",
        barcode="8901719123870",
        mrp=30.0,
        net_weight="250 g",
        manufacturer="Parle Biscuits Pvt Ltd",
        pkd="08/08/2026",
        use_by="05/01/2027",
    )
    data.update(overrides)
    return ReferenceProduct(**data)


def test_barcode_exact_match_wins():
    match, product = product_matcher.match_product(barcode_value="8901719123870", ocr_text="anything", brand_guess=None)
    assert match.reference_found is True
    assert match.match_method == "barcode"
    assert match.match_score == 1.0
    # match_product reads the real seed catalogue (not the _reference() fixture below),
    # so this must be the seed file's own Parle-G id, not a fixture id.
    assert match.product_id == "demo-parle-g-003"
    assert product is not None and product.product_name == "Parle-G"


def test_unknown_product_is_not_an_error():
    match, product = product_matcher.match_product(barcode_value=None, ocr_text="zzzz qqqq unknown local chips", brand_guess=None)
    assert match.reference_found is False
    assert match.match_method is None
    assert product is None


def test_unknown_barcode_falls_through_without_false_match():
    match, _ = product_matcher.match_product(barcode_value="0000000000000", ocr_text="unrelated text", brand_guess=None)
    assert match.reference_found is False


def test_compare_returns_unavailable_without_reference():
    result = product_matcher.compare_with_reference(ExtractedFields(), None)
    assert result.available is False
    assert result.fields == {}


def test_compare_matches_on_normalized_values_not_raw_strings():
    fields = ExtractedFields()
    fields.mrp = ExtractedFieldValue(found=True, raw="30.00", value=30.0)
    fields.net_quantity = ExtractedFieldValue(found=True, raw="200 g+50 extra=250", value=250.0, unit="g")

    result = product_matcher.compare_with_reference(fields, _reference())
    assert result.available is True
    assert result.fields["mrp"].status == "MATCH"
    assert result.fields["net_quantity"].status == "MATCH"


def test_compare_flags_mrp_mismatch():
    fields = ExtractedFields()
    fields.mrp = ExtractedFieldValue(found=True, raw="35.00", value=35.0)
    result = product_matcher.compare_with_reference(fields, _reference())
    assert result.fields["mrp"].status == "MISMATCH"
    assert result.fields["mrp"].match is False


def test_compare_never_claims_match_when_live_value_missing():
    result = product_matcher.compare_with_reference(ExtractedFields(), _reference())
    assert result.fields["mrp"].status == "REVIEW_REQUIRED"
    assert result.fields["mrp"].match is None


def test_compare_reference_value_absent_is_not_available():
    fields = ExtractedFields()
    fields.mrp = ExtractedFieldValue(found=True, raw="30", value=30.0)
    result = product_matcher.compare_with_reference(fields, _reference(mrp=None))
    assert result.fields["mrp"].status == "NOT_AVAILABLE"


def test_compare_manufacturing_date_against_pkd():
    fields = ExtractedFields()
    fields.manufacturing_date = ExtractedFieldValue(found=True, raw="8/8/26", value="2026-08-08")
    result = product_matcher.compare_with_reference(fields, _reference())
    assert result.fields["manufacturing_date"].status == "MATCH"


def test_compare_use_by_mismatch():
    fields = ExtractedFields()
    fields.use_by = ExtractedFieldValue(found=True, raw="1/1/27", value="2027-01-01")
    result = product_matcher.compare_with_reference(fields, _reference())
    assert result.fields["use_by"].status == "MISMATCH"


def test_compare_manufacturer_text_match_case_insensitive():
    fields = ExtractedFields()
    fields.manufacturer_address = ExtractedFieldValue(found=True, raw="parle biscuits pvt ltd")
    result = product_matcher.compare_with_reference(fields, _reference())
    assert result.fields["manufacturer"].status == "MATCH"
