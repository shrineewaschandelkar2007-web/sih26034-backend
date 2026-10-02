from app.services import field_extractor, normalizer

# Real PaddleOCR output captured from the team's Parle-G packet, trimmed
# to the relevant lines. Kept verbatim (including OCR noise) on purpose.
PARLE_G_OCR = """NET WEIGHT:
200 g+50  EXTRA=250
MRP₹30.00 (0.15/g)
INCL OF ALL TAXES
890171913870
PARLE
Parle-G
MFD.BY:
(P)-PARLEBISCUTSPVT LTD.3.SEC.1
CONSUMER CARE CELL
PARLE BISCUITS PVT LTD
NORTH LEVEL CROSSING
VILE PARLE EAST
MUMBAI, MH-400057
PHONE NO.: 1800 209 6929
USE BY: 5/1/27
PKD: 8/8/26"""


def test_extracts_mrp_from_real_ocr():
    raw = field_extractor.extract_raw_fields(PARLE_G_OCR)
    assert raw["mrp"].found
    assert raw["mrp"].raw == "30.00"


def test_extracts_net_quantity_including_extra_total():
    raw = field_extractor.extract_raw_fields(PARLE_G_OCR)
    field = normalizer.normalize_net_quantity(raw["net_quantity"])
    assert (field.value, field.unit) == (250.0, "g")


def test_extracts_dates_and_consumer_care():
    raw = field_extractor.extract_raw_fields(PARLE_G_OCR)
    assert raw["use_by"].raw == "5/1/27"
    assert raw["manufacturing_date"].raw == "8/8/26"
    assert raw["consumer_care_contact"].raw == "1800 209 6929"


def test_manufacturer_captured_on_one_line_only():
    raw = field_extractor.extract_raw_fields(PARLE_G_OCR)
    assert raw["manufacturer_address"].found
    assert "\n" not in raw["manufacturer_address"].raw


def test_missing_fields_stay_explicitly_not_found():
    raw = field_extractor.extract_raw_fields("just some unrelated words on a wrapper")
    for name in ("mrp", "net_quantity", "manufacturing_date", "use_by", "consumer_care_contact"):
        assert raw[name].found is False
        assert raw[name].raw is None


def test_empty_text_does_not_crash():
    raw = field_extractor.extract_raw_fields("")
    assert all(not v.found for v in raw.values())


def test_brand_guess_uses_known_brands_only():
    brand, _ = field_extractor.guess_brand_and_product("PARLE-G GLUCO", ["Parle", "Britannia"])
    assert brand == "Parle"
    brand, _ = field_extractor.guess_brand_and_product("SOME LOCAL BRAND", ["Parle", "Britannia"])
    assert brand is None


def test_number_at_line_end_is_not_misread_as_quantity_with_next_line_word():
    # Regression: "MRP 20\nlocal ..." was read as "20 l" (20 litres).
    raw = field_extractor.extract_raw_fields("mrp rs 20\nlocal banana chips")
    assert raw["net_quantity"].found is False
    raw = field_extractor.extract_raw_fields("MRP 30\nGluco biscuits")
    assert raw["net_quantity"].found is False


def test_quantity_still_found_when_on_same_line():
    raw = field_extractor.extract_raw_fields("net wt 45 g")
    assert raw["net_quantity"].found is True
    field = normalizer.normalize_net_quantity(raw["net_quantity"])
    assert (field.value, field.unit) == (45.0, "g")
