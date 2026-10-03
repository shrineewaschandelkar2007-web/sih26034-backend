"""
Extract candidate Legal Metrology declarations from raw OCR text.

This module is deliberately rule-based (regex + heuristics), not a
trained classifier.

The extractor is tolerant of common OCR formatting problems such as:
- spaces/newlines inserted inside labels
- punctuation dropped around MRP/date labels
- OCR splitting "USE BY" across lines
- OCR returning net quantity without the unit
- weak manufacturer fragments such as "ltd.,"

Field extraction remains conservative: values are extracted only when
there is enough contextual evidence.
"""

from __future__ import annotations

import re

from app.schemas.product import ExtractedFieldValue
from app.utils.text import clean_whitespace


# =========================================================
# REGEX PATTERNS
# =========================================================

_PATTERNS: dict[str, str] = {

    # -----------------------------------------------------
    # MRP
    # -----------------------------------------------------
    "mrp": (
        r"(?:mrp|m\.r\.p)"
        r"[^\d]{0,20}"
        r"(?:rs\.?|inr|₹)?"
        r"\s*"
        r"([\d]+[.,]?\d*)"
    ),

    # -----------------------------------------------------
    # NET QUANTITY
    #
    # Supports:
    #   NET WEIGHT: 185.6g
    #   NET WT 185.6 g
    #   NET QUANTITY: 185.6
    #   NET WT: 200 g + 50 g EXTRA = 250 g
    #
    # Unit is optional when an explicit net-weight/quantity
    # label is present. This helps when OCR drops "g".
    # -----------------------------------------------------
    "net_quantity": (
        r"(?:net\s*(?:wt|weight|qty|quantity|contents))"
        r"[:\s.]*"
        r"("
        r"\d+\.?\d*"
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
        r"(?:\s*\+\s*\d+\.?\d*"
        r"(?:\s*(?:kg|gms|gm|g|ml|l))?"
        r"\s*extra)?"
        r"(?:\s*=\s*\d+\.?\d*"
        r"(?:\s*(?:kg|gms|gm|g|ml|l))?"
        r")?"
        r")"
    ),

    # -----------------------------------------------------
    # MANUFACTURING / PACKING DATE
    # -----------------------------------------------------
    "manufacturing_date": (
        r"(?:pkd|mfd|mfg|manufactured|packed|packaging)"
        r"[.\s]*(?:date|on|dt)?"
        r"[:\s.]"
        r"("
        r"\d{1,2}\s*[/\-.]\s*\d{1,2}"
        r"(?:\s*[/\-.]\s*\d{2,4})?"
        r")"
    ),

    # -----------------------------------------------------
    # BEST BEFORE
    # -----------------------------------------------------
    "best_before": (
        r"best\s*before"
        r"[:\s.]"
        r"("
        r"\d{1,2}\s*[/\-.]\s*\d{1,2}"
        r"(?:\s*[/\-.]\s*\d{2,4})?"
        r"|\d+\s*months?"
        r")"
    ),

    # -----------------------------------------------------
    # USE BY
    # -----------------------------------------------------
    "use_by": (
        r"use\s*by"
        r"[:\s.]"
        r"("
        r"\d{1,2}\s*[/\-.]\s*\d{1,2}"
        r"(?:\s*[/\-.]\s*\d{2,4})?"
        r")"
    ),

    # -----------------------------------------------------
    # CUSTOMER / CONSUMER CARE
    # -----------------------------------------------------
    "consumer_care_contact": (
        r"(?:phone\s*no\.?|consumer\s*care|customer\s*care|"
        r"toll\s*free)"
        r"[.\s:]*"
        r"("
        r"[\d\s()+\-]{8,25}"
        r"|"
        r"[\w.\-+@]{5,60}"
        r")"
    ),

    # -----------------------------------------------------
    # MANUFACTURER / PACKER DECLARATION
    # -----------------------------------------------------
    "manufacturer_address": (
        r"(?:mfd\.?\s*by|manufactured\s*by|"
        r"marketed\s*by|packed\s*by)"
        r"[:\s]*"
        r"([\w\s,.\-()&]{5,180}?)(?=\n|$)"
    ),

    # -----------------------------------------------------
    # BATCH
    # -----------------------------------------------------
    "batch_lot_number": (
        r"(?:batch|lot)"
        r"[:\s.]*"
        r"([\w\-/]{2,30})"
    ),

    # -----------------------------------------------------
    # COUNTRY OF ORIGIN
    # -----------------------------------------------------
    "country_of_origin": (
        r"country\s*of\s*origin"
        r"[:\s]*"
        r"([\w\s]{3,40}?)(?=\n|$)"
    ),
}


# =========================================================
# BASIC HELPERS
# =========================================================

def _normalise_for_matching(text: str) -> str:
    """
    Normalise OCR text without destroying line boundaries.

    This helps patterns survive OCR formatting such as:
        USE
        BY:
    becoming:
        USE BY:
    """
    if not text:
        return ""

    text = text.replace("\u00a0", " ")
    text = text.replace("₹", " ₹ ")

    # Collapse repeated spaces/tabs but preserve newlines.
    text = re.sub(r"[ \t]+", " ", text)

    # Normalize spaces around separators.
    text = re.sub(r"\s*([:/])\s*", r"\1", text)

    return text.strip()


def _flat_text(text: str) -> str:
    """
    Flatten OCR lines into one searchable string.

    Useful when OCR produces:
        USE
        BY:
        1/6/26
    """
    return clean_whitespace(
        re.sub(r"\s+", " ", text)
    )


def _find(field: str, text: str) -> re.Match | None:
    return re.search(
        _PATTERNS[field],
        text,
        flags=re.IGNORECASE,
    )


# =========================================================
# MRP EXTRACTION
# =========================================================

def _find_all_mrp_candidates(
    text: str,
) -> list[tuple[str, bool]]:
    """
    Finds all MRP candidates.

    Returns:
        [(value, has_currency_marker), ...]

    Currency-marked candidates such as:
        ₹40.00
        Rs.40.00
        INR 40.00

    are preferred over weaker candidates such as:
        MRP35.60
    """

    flat = _flat_text(text)

    pattern = (
        r"(?:mrp|m\.r\.p)"
        r"(?P<prefix>[^\d]{0,20})"
        r"(?:rs\.?|inr|₹)?\s*"
        r"(?P<value>[\d]+[.,]?\d*)"
    )

    candidates: list[tuple[str, bool]] = []

    for match in re.finditer(
        pattern,
        flat,
        flags=re.IGNORECASE,
    ):
        prefix = match.group("prefix") or ""
        value = clean_whitespace(
            match.group("value")
        )

        has_currency = bool(
            re.search(
                r"(₹|rs\.?|inr)",
                prefix,
                flags=re.IGNORECASE,
            )
        )

        candidates.append(
            (value, has_currency)
        )

    return candidates


# =========================================================
# NET QUANTITY EXTRACTION
# =========================================================

def _extract_net_quantity(
    text: str,
) -> str | None:
    """
    Extract net quantity from explicit net-weight/quantity context.

    Handles:
        NET WEIGHT: 185.6g
        NET WT: 185.6 g
        NET WEIGHT: 185.6
        NET WEIGHT: 200 g + 50 g EXTRA = 250g
    """

    normalised = _normalise_for_matching(text)
    flat = _flat_text(normalised)

    # First try the main regex against flattened OCR.
    match = re.search(
        _PATTERNS["net_quantity"],
        flat,
        flags=re.IGNORECASE,
    )

    if match:
        return clean_whitespace(
            match.group(1)
        )

    # -----------------------------------------------------
    # Fallback: line-based extraction.
    #
    # This is useful when OCR inserts unrelated whitespace
    # between the label and number.
    # -----------------------------------------------------
    for line in normalised.splitlines():

        line_clean = clean_whitespace(line)

        if not line_clean:
            continue

        if not re.search(
            r"\bnet\s*(?:wt|weight|qty|quantity|contents)\b",
            line_clean,
            flags=re.IGNORECASE,
        ):
            continue

        number_match = re.search(
            r"\b\d+(?:\.\d+)?"
            r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
            r"(?:\s*\+\s*\d+(?:\.\d+)?"
            r"(?:\s*(?:kg|gms|gm|g|ml|l))?"
            r"\s*extra)?"
            r"(?:\s*=\s*\d+(?:\.\d+)?"
            r"(?:\s*(?:kg|gms|gm|g|ml|l))?)?",
            line_clean,
            flags=re.IGNORECASE,
        )

        if number_match:
            return clean_whitespace(
                number_match.group(0)
            )

    return None


# =========================================================
# DATE EXTRACTION
# =========================================================

def _date_candidates(text: str) -> list[str]:
    """
    Returns date-like candidates from OCR text.

    Supports:
        4/10/25
        04/10/2025
        4-10-25
        4.10.25
    """

    flat = _flat_text(text)

    return re.findall(
        r"\b"
        r"\d{1,2}\s*[/\-.]\s*"
        r"\d{1,2}"
        r"(?:\s*[/\-.]\s*\d{2,4})?"
        r"\b",
        flat,
        flags=re.IGNORECASE,
    )


def _extract_date_after_label(
    text: str,
    label_pattern: str,
) -> str | None:
    """
    Extract a date appearing shortly after a label.

    Works even when OCR inserts line breaks:
        USE
        BY:
        1/6/26
    """

    flat = _flat_text(text)

    pattern = (
        rf"(?:{label_pattern})"
        rf"(?:\s|[:.\-])*"
        rf"("
        rf"\d{{1,2}}\s*[/\-.]\s*"
        rf"\d{{1,2}}"
        rf"(?:\s*[/\-.]\s*\d{{2,4}})?"
        rf")"
    )

    match = re.search(
        pattern,
        flat,
        flags=re.IGNORECASE,
    )

    if match:
        return clean_whitespace(
            match.group(1)
        )

    return None


def _extract_spatially_separated_dates(
    text: str,
) -> tuple[str | None, str | None, str | None]:
    """
    OCR sometimes returns declaration labels first and their values later.

    Example:

        PKD:
        BATCH:
        USE BY:
        4/10/25
        ...
        1/6/26

    First try direct label-adjacent extraction.

    Then use date candidates conservatively when labels and values
    have been spatially separated by OCR.
    """

    pkd: str | None = None
    use_by: str | None = None
    best_before: str | None = None

    # -----------------------------------------------------
    # Direct matching
    # -----------------------------------------------------

    pkd = _extract_date_after_label(
        text,
        r"(?:pkd|mfd|mfg|manufactured|packed|packaging)",
    )

    use_by = _extract_date_after_label(
        text,
        r"use\s*by",
    )

    best_before = _extract_date_after_label(
        text,
        r"best\s*before",
    )

    # -----------------------------------------------------
    # Date candidates
    # -----------------------------------------------------

    dates = _date_candidates(text)

    flat_lower = _flat_text(text).lower()

    # -----------------------------------------------------
    # PKD / MFD fallback
    # -----------------------------------------------------

    if pkd is None and dates:

        if (
            "pkd" in flat_lower
            or "mfd" in flat_lower
            or "mfg" in flat_lower
            or "manufactured" in flat_lower
            or "packed" in flat_lower
        ):
            pkd = dates[0]

    # -----------------------------------------------------
    # USE BY fallback
    # -----------------------------------------------------

    if use_by is None and dates:

        if "use by" in flat_lower:

            # Avoid reusing the same date where a second
            # date candidate exists.
            if len(dates) >= 2:
                use_by = dates[1]

            elif len(dates) == 1 and pkd != dates[0]:
                use_by = dates[0]

    # -----------------------------------------------------
    # BEST BEFORE fallback
    # -----------------------------------------------------

    if best_before is None and dates:

        if "best before" in flat_lower:

            if len(dates) >= 2:
                best_before = dates[-1]

            elif len(dates) == 1:
                best_before = dates[0]

    return (
        pkd,
        use_by,
        best_before,
    )


# =========================================================
# MANUFACTURER EXTRACTION
# =========================================================

def _is_valid_company_candidate(
    candidate: str,
) -> bool:
    """
    Reject obvious OCR fragments such as:
        ltd.,
        pvt
        ltd
        .
    """

    candidate = clean_whitespace(candidate)

    if len(candidate) < 8:
        return False

    if not re.search(
        r"[A-Za-z]{3}",
        candidate,
    ):
        return False

    words = candidate.split()

    if len(words) < 2:
        return False

    # Reject candidates consisting almost entirely of generic
    # legal suffixes.
    meaningful_words = [
        word.lower().strip(".,()")
        for word in words
        if word.lower().strip(".,()")
        not in {
            "pvt",
            "ltd",
            "limited",
            "private",
        }
    ]

    if not meaningful_words:
        return False

    return True


def _extract_manufacturer_candidates(
    text: str,
) -> tuple[str | None, str | None]:
    """
    Extract manufacturer/address from common company/address patterns.

    Strongly prefers meaningful company names such as:
        Parle Biscuits Pvt Ltd

    and rejects weak fragments such as:
        ltd.,
        pvt
    """

    manufacturer: str | None = None
    address: str | None = None

    normalised = _normalise_for_matching(text)

    lines = [
        clean_whitespace(line)
        for line in normalised.splitlines()
        if clean_whitespace(line)
    ]

    # -----------------------------------------------------
    # 1. Explicit manufacturer declaration
    # -----------------------------------------------------

    explicit_match = re.search(
        _PATTERNS["manufacturer_address"],
        normalised,
        flags=re.IGNORECASE,
    )

    if explicit_match:

        candidate = clean_whitespace(
            explicit_match.group(1)
        )

        if _is_valid_company_candidate(candidate):
            manufacturer = candidate

    # -----------------------------------------------------
    # 2. Score company-name candidates
    # -----------------------------------------------------

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
        "manufacturer",
        "manufacturers",
    )

    negative_prefixes = (
        "from ",
        "visit us",
        "manufactured for",
        "marketed by",
        "storage conditions",
        "for sale",
    )

    company_candidates: list[
        tuple[int, str]
    ] = []

    for line in lines:

        lower = line.lower()

        if not any(
            keyword in lower
            for keyword in company_keywords
        ):
            continue

        if not _is_valid_company_candidate(line):
            continue

        score = 0

        # Strong company-name indicators.
        for keyword in positive_keywords:
            if keyword in lower:
                score += 2

        # Explicit manufacturer wording is strong evidence.
        if (
            "manufacturer" in lower
            or "manufactured by" in lower
            or "mfd by" in lower
        ):
            score += 6

        # Penalize informational/sentence-like lines.
        if lower.startswith(
            (
                "from ",
                "visit us",
                "manufactured for",
            )
        ):
            score -= 5

        for prefix in negative_prefixes:
            if lower.startswith(prefix):
                score -= 1
                break

        # Prefer names with multiple meaningful alphabetic words.
        alpha_word_count = len(
            re.findall(
                r"[A-Za-z]{3,}",
                line,
            )
        )

        if alpha_word_count >= 3:
            score += 2

        company_candidates.append(
            (score, line)
        )

    if company_candidates:

        company_candidates.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        best_score, best_line = company_candidates[0]

        if manufacturer is None or best_score >= 0:
            manufacturer = best_line

    # -----------------------------------------------------
    # 3. Address detection
    # -----------------------------------------------------

    address_keywords = (
        "road",
        "crossing",
        "mumbai",
        "pune",
        "delhi",
        "bengaluru",
        "bangalore",
        "kolkata",
        "chennai",
        "maharashtra",
        "mh-",
        "pin",
        "india",
        "east",
        "west",
    )

    for line in lines:

        lower = line.lower()

        if not any(
            keyword in lower
            for keyword in address_keywords
        ):
            continue

        if not any(
            char.isalpha()
            for char in line
        ):
            continue

        # Avoid obvious sentence-like lines.
        if lower.startswith(
            (
                "from ",
                "visit us",
                "manufactured for",
            )
        ):
            continue

        address = line
        break

    return (
        manufacturer,
        address,
    )


# =========================================================
# RAW FIELD EXTRACTION
# =========================================================

def extract_raw_fields(
    combined_text: str,
) -> dict[str, ExtractedFieldValue]:
    """
    Returns:
        dict[field_name, ExtractedFieldValue]

    Unit/currency parsing and date normalization happen later
    in normalizer.py.
    """

    text = _normalise_for_matching(
        combined_text
    )

    results: dict[
        str,
        ExtractedFieldValue,
    ] = {}

    # -----------------------------------------------------
    # Standard regex fields
    # -----------------------------------------------------

    for field in _PATTERNS:

        # These are handled by dedicated extraction
        # functions below.
        if field in {
            "mrp",
            "net_quantity",
            "manufacturing_date",
            "use_by",
            "best_before",
            "manufacturer_address",
        }:
            continue

        match = _find(
            field,
            text,
        )

        if not match:

            results[field] = ExtractedFieldValue(
                found=False,
            )

            continue

        raw_value = (
            match.group(1).strip()
            if match.groups()
            else match.group(0)
        )

        results[field] = ExtractedFieldValue(
            found=True,
            raw=clean_whitespace(
                raw_value
            ),
        )

    # -----------------------------------------------------
    # MRP improvement
    # -----------------------------------------------------

    mrp_candidates = _find_all_mrp_candidates(
        text
    )

    if mrp_candidates:

        # Prefer candidates with currency marker.
        preferred = next(
            (
                value
                for value, has_currency
                in mrp_candidates
                if has_currency
            ),
            mrp_candidates[0][0],
        )

        results["mrp"] = ExtractedFieldValue(
            found=True,
            raw=preferred,
        )

    else:

        results["mrp"] = ExtractedFieldValue(
            found=False,
        )

    # -----------------------------------------------------
    # Net quantity improvement
    # -----------------------------------------------------

    net_quantity = _extract_net_quantity(
        text
    )

    if net_quantity:

        results["net_quantity"] = (
            ExtractedFieldValue(
                found=True,
                raw=net_quantity,
            )
        )

    else:

        results["net_quantity"] = (
            ExtractedFieldValue(
                found=False,
            )
        )

    # -----------------------------------------------------
    # Date extraction
    # -----------------------------------------------------

    (
        pkd,
        use_by,
        best_before,
    ) = _extract_spatially_separated_dates(
        text
    )

    results["manufacturing_date"] = (
        ExtractedFieldValue(
            found=True,
            raw=pkd,
        )
        if pkd
        else ExtractedFieldValue(
            found=False,
        )
    )

    results["use_by"] = (
        ExtractedFieldValue(
            found=True,
            raw=use_by,
        )
        if use_by
        else ExtractedFieldValue(
            found=False,
        )
    )

    results["best_before"] = (
        ExtractedFieldValue(
            found=True,
            raw=best_before,
        )
        if best_before
        else ExtractedFieldValue(
            found=False,
        )
    )

    # -----------------------------------------------------
    # Manufacturer/address extraction
    # -----------------------------------------------------

    (
        manufacturer,
        manufacturer_address,
    ) = _extract_manufacturer_candidates(
        text
    )

    # Keep manufacturer separate when possible.
    if manufacturer:

        results["manufacturer"] = (
            ExtractedFieldValue(
                found=True,
                raw=manufacturer,
            )
        )

    else:

        results["manufacturer"] = (
            ExtractedFieldValue(
                found=False,
            )
        )

    if manufacturer_address:

        results["manufacturer_address"] = (
            ExtractedFieldValue(
                found=True,
                raw=manufacturer_address,
            )
        )

    else:

        results["manufacturer_address"] = (
            ExtractedFieldValue(
                found=False,
            )
        )

    # -----------------------------------------------------
    # Preserve all expected fields safely
    # -----------------------------------------------------

    for field in _PATTERNS:

        if field not in results:

            results[field] = (
                ExtractedFieldValue(
                    found=False,
                )
            )

    return results


# =========================================================
# BRAND / PRODUCT GUESSING
# =========================================================

def guess_brand_and_product(
    combined_text: str,
    known_brands: list[str],
) -> tuple[str | None, str | None]:
    """
    Very simple brand detection.

    Looks for a known brand name from the reference-product
    table appearing in OCR text verbatim.

    Product-name detection remains handled by product matching.
    """

    text_lower = (
        combined_text.lower()
    )

    for brand in known_brands:

        if brand.lower() in text_lower:
            return brand, None

    return None, None
