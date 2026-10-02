"""
Extracts candidate Legal Metrology declarations from raw OCR text.

This is deliberately rule-based (regex + heuristics), not a trained
classifier. Field extraction remains conservative: values are extracted
only when recognizable patterns are present.
"""

import re

from app.schemas.product import ExtractedFieldValue
from app.utils.text import clean_whitespace


_PATTERNS: dict[str, str] = {
    # Capture all MRP candidates later; this pattern is still used for
    # ordinary single-MRP labels.
    "mrp": (
        r"(?:mrp|m\.r\.p)[^\d]{0,15}"
        r"(?:rs\.?|inr|₹)?\s*([\d]+[.,]?\d*)"
    ),

    "net_quantity": (
        r"(?:net\s*(?:wt|weight|qty|quantity|contents))?[:\s.]*"
        r"(\d+\.?\d*[ \t]*(?:kg|gms|gm|g|ml|litre|liter|l)s?\b"
        r"(?:[ \t]*\+[ \t]*\d+\.?\d*[ \t]*(?:kg|gms|gm|g|ml|l)?s?[ \t]*extra)?"
        r"(?:[ \t]*=[ \t]*\d+\.?\d*[ \t]*(?:kg|gms|gm|g|ml|l)?s?\b)?)"
    ),

    "manufacturing_date": (
        r"(?:pkd|mfg|manufactured|packed|packaging)"
        r"[.\s]*(?:date|on|dt)?[:\s.]*(\d{1,2}[/\-.]\d{1,2}"
        r"(?:[/\-.]\d{2,4})?)"
    ),

    "best_before": (
        r"best\s*before[:\s.]*(\d{1,2}[/\-.]\d{1,2}"
        r"(?:[/\-.]\d{2,4})?|\d+\s*months?)"
    ),

    "use_by": (
        r"use\s*by[:\s.]*(\d{1,2}[/\-.]\d{1,2}"
        r"(?:[/\-.]\d{2,4})?)"
    ),

    "consumer_care_contact": (
        r"(?:phone\s*no\.?|consumer\s*care|customer\s*care|toll\s*free)"
        r"[.\s:]*([\d\s]{8,15}|[\w.\-+@]{5,60})"
    ),

    "manufacturer_address": (
        r"(?:mfd\.?\s*by|manufactured\s*by|marketed\s*by|packed\s*by)"
        r"[:\s]*([\w\s,.\-()]{5,150}?)(?=\n|$)"
    ),

    "batch_lot_number": r"batch[:\s.]*([\w\-]{2,20})",

    "country_of_origin": (
        r"country\s*of\s*origin[:\s]*([\w\s]{3,40}?)(?=\n|$)"
    ),
}


def _find(field: str, text: str) -> re.Match | None:
    return re.search(_PATTERNS[field], text, flags=re.IGNORECASE)


def _find_all_mrp_candidates(text: str) -> list[tuple[str, bool]]:
    """
    Finds all MRP candidates.

    Returns:
        [(value, has_currency_marker), ...]

    Currency-marked values such as ₹40.00 / Rs.40.00 are preferred
    over plain OCR candidates such as MRP35.60.
    """
    pattern = (
        r"(?:mrp|m\.r\.p)"
        r"(?P<prefix>[^\d]{0,15})"
        r"(?:rs\.?|inr|₹)?\s*"
        r"(?P<value>[\d]+[.,]?\d*)"
    )

    candidates: list[tuple[str, bool]] = []

    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        prefix = match.group("prefix") or ""
        value = clean_whitespace(match.group("value"))

        has_currency = bool(
            re.search(
                r"(₹|rs\.?|inr)",
                prefix,
                flags=re.IGNORECASE,
            )
        )

        candidates.append((value, has_currency))

    return candidates


def _extract_spatially_separated_dates(
    text: str,
) -> tuple[str | None, str | None, str | None]:
    """
    OCR can return declaration labels first and their values later.

    Example:
        PKD:
        BATCH:
        USE BY:
        4/10/25
        ...
        1/6/26

    In such cases, fall back to nearby date candidates while keeping
    extraction conservative.
    """
    date_pattern = r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b"
    dates = re.findall(date_pattern, text)

    pkd = None
    use_by = None

    # First use normal label-adjacent matching.
    mfg_match = re.search(
        _PATTERNS["manufacturing_date"],
        text,
        flags=re.IGNORECASE,
    )

    if mfg_match:
        pkd = clean_whitespace(mfg_match.group(1))

    use_match = re.search(
        _PATTERNS["use_by"],
        text,
        flags=re.IGNORECASE,
    )

    if use_match:
        use_by = clean_whitespace(use_match.group(1))

    # Fallback for OCR ordering where labels and values are separated.
    if dates:
        if pkd is None and "pkd" in text.lower():
            pkd = dates[0]

        if use_by is None and "use by" in text.lower():
            # Avoid assigning the same value to both fields when there
            # are multiple dates visible.
            if len(dates) >= 2:
                use_by = dates[1]
            elif len(dates) == 1 and pkd != dates[0]:
                use_by = dates[0]

    return pkd, use_by, None


def _extract_manufacturer_candidates(
    text: str,
) -> tuple[str | None, str | None]:
    """
    Extracts manufacturer/address from common company/address patterns.

    Prefers actual manufacturer/company declaration lines over phrases
    such as:
      - FROM ...
      - VISIT US AT ...
      - MANUFACTURED FOR ...
    """
    manufacturer = None
    address = None

    lines = [
        clean_whitespace(line)
        for line in text.splitlines()
        if clean_whitespace(line)
    ]

    # ---------------------------------------------------------
    # 1. Explicit manufacturer declaration
    # ---------------------------------------------------------
    explicit_match = re.search(
        _PATTERNS["manufacturer_address"],
        text,
        flags=re.IGNORECASE,
    )

    if explicit_match:
        candidate = clean_whitespace(explicit_match.group(1))

        if candidate:
            manufacturer = candidate

    # ---------------------------------------------------------
    # 2. Score company-name candidates
    # ---------------------------------------------------------
    company_keywords = (
        "pvt ltd",
        "private limited",
        "limited",
        "ltd",
    )

    positive_keywords = (
        "biscuits",
        "foods",
        "food",
        "products",
        "industries",
        "manufacturers",
        "manufacturer",
    )

    negative_prefixes = (
        "from ",
        "visit us",
        "manufactured for",
        "marketed by",
        "storage conditions",
        "for sale",
    )

    company_candidates: list[tuple[int, str]] = []

    for line in lines:
        lower = line.lower()

        if not any(
            keyword in lower
            for keyword in company_keywords
        ):
            continue

        score = 0

        # Strong company-name indicators
        for keyword in positive_keywords:
            if keyword in lower:
                score += 2

        # Penalize sentence-like / informational lines
        if lower.startswith(
            (
                "from ",
                "visit us",
                "manufactured for",
            )
        ):
            score -= 5

        # Explicit manufacturer wording is very strong
        if (
            "manufacturer" in lower
            or "manufactured by" in lower
        ):
            score += 5

        # Keep this variable meaningful for readability and future
        # extension of the heuristic.
        for prefix in negative_prefixes:
            if lower.startswith(prefix):
                score -= 1
                break

        company_candidates.append((score, line))

    if company_candidates:
        company_candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        best_score, best_line = company_candidates[0]

        if manufacturer is None or best_score >= 0:
            manufacturer = best_line

    # ---------------------------------------------------------
    # 3. Address detection
    # ---------------------------------------------------------
    address_keywords = (
        "road",
        "crossing",
        "mumbai",
        "pune",
        "delhi",
        "bengaluru",
        "kolkata",
        "chennai",
        "maharashtra",
        "mh-",
        "pin",
        "india",
    )

    for line in lines:
        lower = line.lower()

        if (
            any(
                keyword in lower
                for keyword in address_keywords
            )
            and any(ch.isalpha() for ch in line)
        ):
            # Avoid choosing company-description lines as the
            # address when a real location line exists.
            if not lower.startswith(
                (
                    "from ",
                    "visit us",
                    "manufactured for",
                )
            ):
                address = line
                break

    return manufacturer, address


def extract_raw_fields(
    combined_text: str,
) -> dict[str, ExtractedFieldValue]:
    """
    Returns a dict keyed by field name -> ExtractedFieldValue with the
    raw matched string in `.raw`.

    Unit/currency parsing and date normalization happen in
    normalizer.py.
    """
    text = combined_text.lower()
    results: dict[str, ExtractedFieldValue] = {}

    # ---------------------------------------------------------
    # Standard regex fields
    # ---------------------------------------------------------
    for field in _PATTERNS:
        match = _find(field, text)

        if not match:
            results[field] = ExtractedFieldValue(
                found=False
            )
            continue

        raw_value = (
            match.group(1).strip()
            if match.groups()
            else match.group(0)
        )

        results[field] = ExtractedFieldValue(
            found=True,
            raw=clean_whitespace(raw_value),
        )

    # ---------------------------------------------------------
    # MRP improvement
    # ---------------------------------------------------------
    mrp_candidates = _find_all_mrp_candidates(text)

    if mrp_candidates:
        # Prefer a candidate explicitly associated with
        # ₹ / Rs / INR.
        #
        # Example:
        #   MRP35.60      -> no currency marker
        #   MRP₹40.00     -> currency marker
        #
        # Therefore ₹40.00 is preferred.
        preferred = next(
            (
                value
                for value, has_currency in mrp_candidates
                if has_currency
            ),
            mrp_candidates[0][0],
        )

        results["mrp"] = ExtractedFieldValue(
            found=True,
            raw=preferred,
        )

    # ---------------------------------------------------------
    # Date fallback
    # ---------------------------------------------------------
    pkd, use_by, _ = _extract_spatially_separated_dates(
        text
    )

    if pkd:
        results["manufacturing_date"] = ExtractedFieldValue(
            found=True,
            raw=pkd,
        )

    if use_by:
        results["use_by"] = ExtractedFieldValue(
            found=True,
            raw=use_by,
        )

    # ---------------------------------------------------------
    # Manufacturer/address fallback
    # ---------------------------------------------------------
    manufacturer, manufacturer_address = (
        _extract_manufacturer_candidates(text)
    )

    if manufacturer:
        results["manufacturer_address"] = (
            ExtractedFieldValue(
                found=True,
                raw=manufacturer,
            )
        )

    # Preserve missing fields safely.
    for field in _PATTERNS:
        if field not in results:
            results[field] = ExtractedFieldValue(
                found=False
            )

    return results


def guess_brand_and_product(
    combined_text: str,
    known_brands: list[str],
) -> tuple[str | None, str | None]:
    """
    Very simple brand detection: looks for a known brand name from the
    reference-product table appearing verbatim in the OCR text.

    Product-name detection remains handled by product matching.
    """
    text_lower = combined_text.lower()

    for brand in known_brands:
        if brand.lower() in text_lower:
            return brand, None

    return None, None
