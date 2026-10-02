from app.utils.text import clean_whitespace, fix_common_ocr_confusions, looks_numeric_token


def test_ocr_confusions_only_fixed_in_numeric_context():
    assert fix_common_ocr_confusions("3O.OO", numeric_context=True) == "30.00"
    # free text must never be "corrected": FOOD must not become F00D
    assert fix_common_ocr_confusions("FOOD", numeric_context=False) == "FOOD"


def test_looks_numeric_token():
    assert looks_numeric_token("Rs. 3O.OO")
    assert looks_numeric_token("₹30")
    assert not looks_numeric_token("FOOD")
    assert not looks_numeric_token("")


def test_clean_whitespace():
    assert clean_whitespace("  a \n  b\t c ") == "a b c"
