from app.schemas.product import ExtractedFieldValue
from app.services import normalizer
from app.utils.dates import try_parse_date
from app.utils.units import parse_net_quantity


def test_parse_net_quantity_uses_explicit_total_without_unit():
    # Real Parle-G label shape: '+50 EXTRA=250' with the unit omitted on the total.
    assert parse_net_quantity("200 g+50 extra=250") == (250.0, "g")


def test_parse_net_quantity_uses_explicit_total_with_unit():
    assert parse_net_quantity("200 g + 50 g extra = 250 g") == (250.0, "g")


def test_parse_net_quantity_simple():
    assert parse_net_quantity("Net Wt. 71.4 g") == (71.4, "g")
    assert parse_net_quantity("1 kg") == (1.0, "kg")
    assert parse_net_quantity("500 ml") == (500.0, "ml")


def test_parse_net_quantity_no_match():
    assert parse_net_quantity("no quantity here") == (None, None)


def test_normalize_mrp_extracts_number_and_currency():
    field = normalizer.normalize_mrp(ExtractedFieldValue(found=True, raw="30.00"))
    assert field.value == 30.0
    assert field.currency == "INR"


def test_normalize_mrp_leaves_missing_field_untouched():
    field = normalizer.normalize_mrp(ExtractedFieldValue(found=False))
    assert field.value is None


def test_try_parse_date_common_formats():
    assert try_parse_date("8/8/26") == "2026-08-08"
    assert try_parse_date("29/3/27") == "2027-03-29"
    assert try_parse_date("05-01-2027") == "2027-01-05"


def test_try_parse_date_never_invents_a_date():
    assert try_parse_date("garbage") is None
    assert try_parse_date("") is None


def test_raw_value_is_never_overwritten():
    field = normalizer.normalize_net_quantity(ExtractedFieldValue(found=True, raw="200 g+50 extra=250"))
    assert field.raw == "200 g+50 extra=250"
    assert field.value == 250.0
