import json
import re
from difflib import SequenceMatcher

from app.schemas.product import (
    ExtractedFields,
    FieldComparisonEntry,
    ProductMatch,
    ReferenceComparison,
    ReferenceProduct,
)
from app.services import reference_service
from app.utils.dates import try_parse_date
from app.utils.units import parse_net_quantity

_FUZZY_THRESHOLD = 0.72


def _fuzzy_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def match_product(
    *,
    barcode_value: str | None,
    ocr_text: str,
    brand_guess: str | None,
) -> tuple[ProductMatch, ReferenceProduct | None]:
    """
    Priority order (per spec section 8):
      1. exact barcode match
      2. normalized brand + product name (fuzzy against OCR text)
      3. no match -> reference_found=False, but callers must still
         proceed with the OCR/compliance flow (spec section 8/29).
    """
    products = reference_service.list_reference_products()

    if barcode_value:
        for product in products:
            if product.barcode and product.barcode == barcode_value:
                return (
                    ProductMatch(
                        reference_found=True,
                        product_id=product.reference_product_id,
                        match_method="barcode",
                        match_score=1.0,
                    ),
                    product,
                )

    best_product: ReferenceProduct | None = None
    best_score = 0.0

    for product in products:
        haystack = f"{product.brand} {product.product_name}"

        if brand_guess and product.brand.lower() == brand_guess.lower():
            score = (
                0.85
                if product.product_name.lower() in ocr_text.lower()
                else 0.6
            )
        else:
            score = _fuzzy_ratio(haystack, ocr_text[:200])

        if score > best_score:
            best_score = score
            best_product = product

    if best_product and best_score >= _FUZZY_THRESHOLD:
        return (
            ProductMatch(
                reference_found=True,
                product_id=best_product.reference_product_id,
                match_method="fuzzy",
                match_score=round(best_score, 3),
            ),
            best_product,
        )

    return (
        ProductMatch(
            reference_found=False,
            match_method=None,
            match_score=0.0,
        ),
        None,
    )


def _reference_json(reference: ReferenceProduct) -> dict:
    """
    Reads reference_fields_json safely.

    In the live database this column may arrive as either:
      - a JSON string
      - an already-decoded dict
      - None / invalid JSON
    """
    raw = reference.reference_fields_json

    if not raw:
        return {}

    if isinstance(raw, dict):
        return raw

    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    return {}


def _reference_value(
    reference: ReferenceProduct,
    column_name: str,
    *json_names: str,
):
    """
    Prefer the normal DB column.

    If that column is empty, fall back to the corresponding
    value stored inside reference_fields_json.
    """
    direct_value = getattr(reference, column_name, None)

    if direct_value not in (None, ""):
        return direct_value

    reference_data = _reference_json(reference)

    for name in json_names:
        value = reference_data.get(name)
        if value not in (None, ""):
            return value

    return None


def _parse_reference_mrp(value):
    """
    Converts reference MRP values such as:
      40
      40.00
      '₹40.00'
      '���40.00'
    into a float.
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        cleaned = value.replace(",", "")
        match = re.search(r"\d+(?:\.\d+)?", cleaned)

        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None

    return None


def _compare_text(
    comparisons: dict,
    name: str,
    live_value,
    reference_value,
) -> None:
    if reference_value is None:
        comparisons[name] = FieldComparisonEntry(
            live=live_value,
            reference=None,
            match=None,
            status="NOT_AVAILABLE",
        )
        return

    if live_value is None:
        comparisons[name] = FieldComparisonEntry(
            live=None,
            reference=reference_value,
            match=None,
            status="REVIEW_REQUIRED",
        )
        return

    is_match = (
        str(live_value).strip().lower()
        == str(reference_value).strip().lower()
    )

    comparisons[name] = FieldComparisonEntry(
        live=live_value,
        reference=reference_value,
        match=is_match,
        status="MATCH" if is_match else "MISMATCH",
    )


def _compare_numeric(
    comparisons: dict,
    name: str,
    live_value,
    reference_value,
) -> None:
    if reference_value is None:
        comparisons[name] = FieldComparisonEntry(
            live=live_value,
            reference=None,
            match=None,
            status="NOT_AVAILABLE",
        )
        return

    if live_value is None:
        comparisons[name] = FieldComparisonEntry(
            live=None,
            reference=reference_value,
            match=None,
            status="REVIEW_REQUIRED",
        )
        return

    try:
        is_match = abs(float(live_value) - float(reference_value)) < 0.01
    except (TypeError, ValueError):
        is_match = (
            str(live_value).strip()
            == str(reference_value).strip()
        )

    comparisons[name] = FieldComparisonEntry(
        live=live_value,
        reference=reference_value,
        match=is_match,
        status="MATCH" if is_match else "MISMATCH",
    )


def _compare_date(
    comparisons: dict,
    name: str,
    live_raw: str | None,
    reference_raw: str | None,
) -> None:
    if reference_raw is None:
        comparisons[name] = FieldComparisonEntry(
            live=live_raw,
            reference=None,
            match=None,
            status="NOT_AVAILABLE",
        )
        return

    if live_raw is None:
        comparisons[name] = FieldComparisonEntry(
            live=None,
            reference=reference_raw,
            match=None,
            status="REVIEW_REQUIRED",
        )
        return

    live_iso = try_parse_date(live_raw) or live_raw
    ref_iso = try_parse_date(reference_raw) or reference_raw

    is_match = live_iso == ref_iso

    comparisons[name] = FieldComparisonEntry(
        live=live_raw,
        reference=reference_raw,
        match=is_match,
        status="MATCH" if is_match else "MISMATCH",
    )


def compare_with_reference(
    fields: ExtractedFields,
    reference: ReferenceProduct | None,
) -> ReferenceComparison:
    """
    Field-level live-vs-reference comparison.

    Normal product_reference columns are preferred. When a field is
    empty in the normal column, reference_fields_json is used as a
    fallback.

    Mapping:
      mrp                -> mrp
      net_quantity       -> net_weight
      manufacturer       -> manufacturer
      manufacturing_date -> pkd
      best_before        -> best_before
      use_by             -> use_by
    """
    if reference is None:
        return ReferenceComparison(
            available=False,
            fields={},
        )

    comparisons: dict[str, FieldComparisonEntry] = {}

    # ---------------------------------------------------------
    # MRP
    # ---------------------------------------------------------
    reference_mrp_raw = _reference_value(
        reference,
        "mrp",
        "mrp",
    )
    reference_mrp = _parse_reference_mrp(reference_mrp_raw)

    _compare_numeric(
        comparisons,
        "mrp",
        fields.mrp.value,
        reference_mrp,
    )

    # ---------------------------------------------------------
    # NET QUANTITY
    # ---------------------------------------------------------
    reference_net_weight = _reference_value(
        reference,
        "net_weight",
        "net_weight",
        "net_quantity",
    )

    ref_qty_value, ref_qty_unit = (
        parse_net_quantity(reference_net_weight)
        if reference_net_weight
        else (None, None)
    )

    live_qty_value = fields.net_quantity.value
    live_qty_unit = fields.net_quantity.unit

    if ref_qty_value is None:
        comparisons["net_quantity"] = FieldComparisonEntry(
            live=fields.net_quantity.raw,
            reference=reference_net_weight,
            match=None,
            status="NOT_AVAILABLE",
        )
    elif live_qty_value is None:
        comparisons["net_quantity"] = FieldComparisonEntry(
            live=None,
            reference=reference_net_weight,
            match=None,
            status="REVIEW_REQUIRED",
        )
    else:
        same = (
            abs(float(live_qty_value) - ref_qty_value) < 0.01
            and live_qty_unit == ref_qty_unit
        )

        comparisons["net_quantity"] = FieldComparisonEntry(
            live=f"{live_qty_value:g} {live_qty_unit or ''}".strip(),
            reference=f"{ref_qty_value:g} {ref_qty_unit or ''}".strip(),
            match=same,
            status="MATCH" if same else "MISMATCH",
        )

    # ---------------------------------------------------------
    # MANUFACTURER
    # ---------------------------------------------------------
    reference_manufacturer = _reference_value(
        reference,
        "manufacturer",
        "manufacturer",
    )

    _compare_text(
        comparisons,
        "manufacturer",
        fields.manufacturer_address.raw,
        reference_manufacturer,
    )

    # ---------------------------------------------------------
    # MANUFACTURING / PACKING DATE
    # ---------------------------------------------------------
    reference_pkd = _reference_value(
        reference,
        "pkd",
        "pkd",
    )

    _compare_date(
        comparisons,
        "manufacturing_date",
        fields.manufacturing_date.raw,
        reference_pkd,
    )

    # ---------------------------------------------------------
    # BEST BEFORE
    # ---------------------------------------------------------
    reference_best_before = _reference_value(
        reference,
        "best_before",
        "best_before",
    )

    _compare_date(
        comparisons,
        "best_before",
        fields.best_before.raw,
        reference_best_before,
    )

    # ---------------------------------------------------------
    # USE BY
    # ---------------------------------------------------------
    reference_use_by = _reference_value(
        reference,
        "use_by",
        "use_by",
    )

    _compare_date(
        comparisons,
        "use_by",
        fields.use_by.raw,
        reference_use_by,
    )

    return ReferenceComparison(
        available=True,
        fields=comparisons,
    )
