"""
Normalizes the raw strings from field_extractor.py into typed values
(numbers, units, ISO dates) WITHOUT ever discarding the original raw
text - every ExtractedFieldValue keeps `.raw` untouched.
"""

import re

from app.schemas.product import ExtractedFields, ExtractedFieldValue
from app.utils.dates import try_parse_date
from app.utils.units import parse_net_quantity

_MRP_NUMBER_RE = re.compile(r"[\d]+\.?\d*")


def normalize_mrp(field: ExtractedFieldValue) -> ExtractedFieldValue:
    if not field.found or not field.raw:
        return field
    match = _MRP_NUMBER_RE.search(field.raw)
    if not match:
        return field
    field.value = float(match.group(0))
    field.currency = "INR"
    return field


def normalize_net_quantity(field: ExtractedFieldValue) -> ExtractedFieldValue:
    if not field.found or not field.raw:
        return field
    value, unit = parse_net_quantity(field.raw)
    field.value = value
    field.unit = unit
    return field


def normalize_date_field(field: ExtractedFieldValue) -> ExtractedFieldValue:
    if not field.found or not field.raw:
        return field
    iso = try_parse_date(field.raw)
    # Keep the raw string as the displayed value if parsing fails -
    # never silently invent a date (spec section 7).
    field.value = iso if iso else field.raw
    return field


def build_extracted_fields(
    raw_fields: dict[str, ExtractedFieldValue],
    brand: str | None,
    product_name: str | None,
    barcode_value: str | None,
) -> ExtractedFields:
    fields = ExtractedFields()

    fields.brand = ExtractedFieldValue(found=bool(brand), value=brand, raw=brand)
    fields.product_name = ExtractedFieldValue(found=bool(product_name), value=product_name, raw=product_name)
    fields.barcode = ExtractedFieldValue(found=bool(barcode_value), value=barcode_value, raw=barcode_value)

    fields.mrp = normalize_mrp(raw_fields.get("mrp", ExtractedFieldValue()))
    fields.net_quantity = normalize_net_quantity(raw_fields.get("net_quantity", ExtractedFieldValue()))
    fields.manufacturer_address = raw_fields.get("manufacturer_address", ExtractedFieldValue())
    # `manufacturer` mirrors manufacturer_address unless a more specific
    # company-name-only extraction is added later.
    fields.manufacturer = fields.manufacturer_address

    fields.manufacturing_date = normalize_date_field(raw_fields.get("manufacturing_date", ExtractedFieldValue()))
    fields.packing_date = fields.manufacturing_date  # PKD is treated as packing date on most labels
    fields.best_before = normalize_date_field(raw_fields.get("best_before", ExtractedFieldValue()))
    fields.use_by = normalize_date_field(raw_fields.get("use_by", ExtractedFieldValue()))

    fields.consumer_care_contact = raw_fields.get("consumer_care_contact", ExtractedFieldValue())
    fields.customer_care = fields.consumer_care_contact
    fields.batch_lot_number = raw_fields.get("batch_lot_number", ExtractedFieldValue())
    fields.country_of_origin = raw_fields.get("country_of_origin", ExtractedFieldValue())

    return fields
