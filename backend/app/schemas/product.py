from pydantic import BaseModel


class ExtractedFieldValue(BaseModel):
    value: str | float | int | None = None
    unit: str | None = None
    currency: str | None = None
    raw: str | None = None
    found: bool = False


class ExtractedFields(BaseModel):
    """
    Internal extraction vocabulary. Field names here follow Legal Metrology
    terminology (net_quantity, manufacturing_date) rather than the DB's
    column names (net_weight, pkd) - product_matcher.py is the one place
    that translates between the two when comparing against a reference row.
    """

    brand: ExtractedFieldValue = ExtractedFieldValue()
    product_name: ExtractedFieldValue = ExtractedFieldValue()
    barcode: ExtractedFieldValue = ExtractedFieldValue()
    mrp: ExtractedFieldValue = ExtractedFieldValue()
    net_quantity: ExtractedFieldValue = ExtractedFieldValue()
    manufacturer: ExtractedFieldValue = ExtractedFieldValue()
    manufacturer_address: ExtractedFieldValue = ExtractedFieldValue()
    country_of_origin: ExtractedFieldValue = ExtractedFieldValue()
    batch_lot_number: ExtractedFieldValue = ExtractedFieldValue()
    manufacturing_date: ExtractedFieldValue = ExtractedFieldValue()
    packing_date: ExtractedFieldValue = ExtractedFieldValue()
    best_before: ExtractedFieldValue = ExtractedFieldValue()
    use_by: ExtractedFieldValue = ExtractedFieldValue()
    customer_care: ExtractedFieldValue = ExtractedFieldValue()
    consumer_care_contact: ExtractedFieldValue = ExtractedFieldValue()


class ProductMatch(BaseModel):
    reference_found: bool
    product_id: str | None = None  # holds product_reference.reference_product_id (text business key)
    match_method: str | None = None  # "barcode" | "brand_name" | "fuzzy" | None
    match_score: float = 0.0


class ReferenceProduct(BaseModel):
    """Mirrors the real DB table `product_reference` column-for-column (plus an internal-only source_note)."""

    reference_product_id: str
    brand: str
    product_name: str
    barcode: str | None = None
    mrp: float | None = None
    net_weight: str | None = None
    manufacturer: str | None = None
    batch_no: str | None = None
    pkd: str | None = None
    best_before: str | None = None
    use_by: str | None = None
    reference_ocr_text: str | None = None
    reference_fields_json: dict | None = None
    reference_image: str | None = None
    reference_image_url: str | None = None
    # Not a DB column - only present when loaded from the local JSON seed, to flag rows
    # that still need real values filled in from an actual reference photo.
    source_note: str | None = None


class FieldComparisonEntry(BaseModel):
    live: str | float | None = None
    reference: str | float | None = None
    match: bool | None = None  # None => NOT_AVAILABLE
    status: str = "NOT_AVAILABLE"  # MATCH | MISMATCH | NOT_AVAILABLE | REVIEW_REQUIRED


class ReferenceComparison(BaseModel):
    available: bool
    fields: dict[str, FieldComparisonEntry] = {}
