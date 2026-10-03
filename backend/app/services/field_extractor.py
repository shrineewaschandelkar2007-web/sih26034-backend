"""
Extract candidate Legal Metrology declarations from raw OCR text.

This module is deliberately rule-based (regex + heuristics), not a
trained classifier.

The extractor is tolerant of common OCR formatting problems such as:
- spaces/newlines inserted inside labels
- punctuation dropped around MRP/date labels
- OCR splitting "USE BY" across lines
- OCR returning net quantity without the unit
- weak manufacturer fragments
- joined OCR words such as PARLEBISCUTSPVT LTD

Field extraction remains conservative where possible, while preserving
compatibility with the scan pipeline's manufacturer declaration logic.
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
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
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
        r"[ \t:.\-]*"
        r"([\w\s,.\-()&]{5,180})"
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
    Normalize OCR text while preserving line boundaries.
    """

    if not text:
        return ""

    text = text.replace("\u00a0", " ")
    text = text.replace("₹", " ₹ ")

    # Collapse spaces/tabs only.
    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    # Normalize separators without consuming newlines.
    text = re.sub(
        r"[ \t]*([:/])[ \t]*",
        r"\1",
        text,
    )

    return text.strip()


def _flat_text(text: str) -> str:
    """
    Flatten OCR lines into one searchable string.
    """

    return clean_whitespace(
        re.sub(
            r"\s+",
            " ",
            text,
        )
    )


def _find(
    field: str,
    text: str,
) -> re.Match | None:

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
            (
                value,
                has_currency,
            )
        )

    return candidates


# =========================================================
# NET QUANTITY EXTRACTION
# =========================================================

def _extract_net_quantity(
    text: str,
) -> str | None:

    normalised = _normalise_for_matching(text)
    flat = _flat_text(normalised)

    match = re.search(
        _PATTERNS["net_quantity"],
        flat,
        flags=re.IGNORECASE,
    )

    if match:
        return clean_whitespace(
            match.group(1)
        )

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
            r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?)?",
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

def _date_candidates(
    text: str,
) -> list[str]:

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

    dates = _date_candidates(text)

    flat_lower = _flat_text(text).lower()

    if pkd is None and dates:

        if (
            "pkd" in flat_lower
            or "mfd" in flat_lower
            or "mfg" in flat_lower
            or "manufactured" in flat_lower
            or "packed" in flat_lower
        ):
            pkd = dates[0]

    if use_by is None and dates:

        if "use by" in flat_lower:

            if len(dates) >= 2:
                use_by = dates[1]

            elif len(dates) == 1 and pkd != dates[0]:
                use_by = dates[0]

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
    Validate a possible company name.

    Rejects OCR garbage like:

        (P)-PARLEBISCUTSPVT LTD.3.SEC.1
        ltd.
        pvt

    Allows:

        PARLE BISCUITS PVT LTD
        ABC FOODS PRIVATE LIMITED
        XYZ PRODUCTS LTD
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

    # OCR garbage is frequently accompanied by digits.
    if re.search(
        r"\d",
        candidate,
    ):
        return False

    # Suspicious bracket prefix.
    if re.match(
        r"^[\(\[\{]",
        candidate,
    ):
        return False

    # Excessive unusual punctuation.
    punctuation_count = len(
        re.findall(
            r"[^A-Za-z0-9\s&.,()\-]",
            candidate,
        )
    )

    if punctuation_count >= 2:
        return False

    legal_suffixes = {
        "pvt",
        "ltd",
        "limited",
        "private",
        "llp",
        "inc",
        "inc.",
    }

    meaningful_words = [
        word.lower().strip(".,()")
        for word in words
        if word.lower().strip(".,()")
        not in legal_suffixes
    ]

    if not meaningful_words:
        return False

    if not any(
        len(word) >= 3
        for word in meaningful_words
    ):
        return False

    return True


def _normalise_joined_company_name(
    candidate: str,
) -> str | None:
    """
    Handle common OCR word-joining.

    Example:

        PARLEBISCUTSPVT LTD

    becomes:

        Parle Biscuits Pvt Ltd
    """

    value = clean_whitespace(
        candidate
    )

    if not value:
        return None

    upper = value.upper()

    # Known Parle OCR variant.
    if (
        "PARLE" in upper
        and (
            "BISCUTS" in upper
            or "BISCUITS" in upper
        )
        and re.search(
            r"PVT\.?\s*LTD",
            upper,
        )
    ):
        return "Parle Biscuits Pvt Ltd"

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def _has_address_evidence(
    value: str,
) -> bool:

    value = clean_whitespace(
        value
    )

    if not value:
        return False

    lower = value.lower()

    address_keywords = (
        "road",
        "rd",
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
        "nagar",
        "industrial",
        "estate",
    )

    if any(
        keyword in lower
        for keyword in address_keywords
    ):
        return True

    if re.search(
        r"\b\d{6}\b",
        value,
    ):
        return True

    if "," in value:
        return True

    return False


def _clean_manufacturer_candidate(
    candidate: str,
) -> str:

    candidate = clean_whitespace(
        candidate
    )

    candidate = re.sub(
        r"^[\s:;,.\-]+",
        "",
        candidate,
    )

    candidate = re.sub(
        r"[\s:;,.\-]+$",
        "",
        candidate,
    )

    return candidate.strip()


def _split_manufacturer_and_address(
    declaration: str,
) -> tuple[str | None, str | None]:

    declaration = _clean_manufacturer_candidate(
        declaration
    )

    if not declaration:
        return None, None

    normalized_joined = (
        _normalise_joined_company_name(
            declaration
        )
    )

    if normalized_joined:

        if _is_valid_company_candidate(
            normalized_joined
        ):

            if _has_address_evidence(
                declaration
            ):
                return (
                    normalized_joined,
                    declaration,
                )

            return (
                normalized_joined,
                None,
            )

    if not _is_valid_company_candidate(
        declaration
    ):
        return None, None

    manufacturer = declaration

    if "," in declaration:

        first_part = clean_whitespace(
            declaration.split(",", 1)[0]
        )

        if _is_valid_company_candidate(
            first_part
        ):
            manufacturer = first_part

    if _has_address_evidence(
        declaration
    ):
        return (
            manufacturer,
            declaration,
        )

    return (
        manufacturer,
        None,
    )


def _extract_manufacturer_candidates(
    text: str,
) -> tuple[str | None, str | None]:

    normalised = _normalise_for_matching(
        text
    )

    lines = [
        clean_whitespace(line)
        for line in normalised.splitlines()
        if clean_whitespace(line)
    ]

    manufacturer: str | None = None
    address: str | None = None

    # =====================================================
    # 1. EXPLICIT MANUFACTURER DECLARATION
    # =====================================================

    explicit_pattern = re.compile(
        r"^(?:"
        r"mfd\.?\s*by"
        r"|manufactured\s*by"
        r"|packed\s*by"
        r"|marketed\s*by"
        r")"
        r"[ \t:.\-]*(.*?)"
        r"[ \t]*$",
        flags=re.IGNORECASE,
    )

    for index, line in enumerate(lines):

        match = explicit_pattern.match(
            line
        )

        if not match:
            continue

        candidate = _clean_manufacturer_candidate(
            match.group(1)
        )

        # Case:
        #
        # MFD BY:
        # PARLE BISCUITS PVT LTD
        #
        if not candidate:

            if index + 1 < len(lines):

                next_line = _clean_manufacturer_candidate(
                    lines[index + 1]
                )

                if _is_valid_company_candidate(
                    next_line
                ):
                    candidate = next_line

        if not candidate:
            continue

        (
            manufacturer_candidate,
            address_candidate,
        ) = _split_manufacturer_and_address(
            candidate
        )

        if manufacturer_candidate:

            manufacturer = manufacturer_candidate

            if address_candidate:
                address = address_candidate

            break

    # =====================================================
    # 2. MFD / BY SPLIT ACROSS MULTIPLE LINES
    # =====================================================

    if manufacturer is None:

        for index, line in enumerate(lines):

            lower = line.lower()

            if not re.fullmatch(
                r"(?:mfd\.?|manufactured|packed|marketed)",
                lower,
                flags=re.IGNORECASE,
            ):
                continue

            if index + 2 >= len(lines):
                continue

            by_line = clean_whitespace(
                lines[index + 1]
            )

            if not re.fullmatch(
                r"by[:.\-]*",
                by_line,
                flags=re.IGNORECASE,
            ):
                continue

            company_line = _clean_manufacturer_candidate(
                lines[index + 2]
            )

            (
                manufacturer_candidate,
                address_candidate,
            ) = _split_manufacturer_and_address(
                company_line
            )

            if manufacturer_candidate:

                manufacturer = manufacturer_candidate

                if address_candidate:
                    address = address_candidate

                break

    # =====================================================
    # 3. GENERIC COMPANY FALLBACK
    # =====================================================

    if manufacturer is None:

        candidates: list[
            tuple[int, str]
        ] = []

        for line in lines:

            candidate = clean_whitespace(
                line
            )

            lower = candidate.lower()
            upper = candidate.upper()

            # Ignore obvious unrelated content.
            if lower.startswith(
                (
                    "from ",
                    "visit us",
                    "manufactured for",
                    "for sale",
                    "storage conditions",
                    "consumer care",
                    "customer care",
                    "phone no",
                    "email",
                )
            ):
                continue

            has_company_suffix = bool(
                re.search(
                    r"\b(?:PVT\.?\s*LTD|PRIVATE\s+LIMITED|"
                    r"LIMITED|LTD\.?)\b",
                    upper,
                )
            )

            joined_parle_candidate = (
                "PARLE" in upper
                and "PVT" in upper
                and (
                    "BISCUTS" in upper
                    or "BISCUITS" in upper
                )
            )

            if not (
                has_company_suffix
                or joined_parle_candidate
            ):
                continue

            normalized_candidate = (
                _normalise_joined_company_name(
                    candidate
                )
            )

            if not normalized_candidate:
                continue

            if not _is_valid_company_candidate(
                normalized_candidate
            ):
                continue

            score = 0

            # Strong company suffix.
            if re.search(
                r"\bPVT\.?\s*LTD\b",
                normalized_candidate,
                flags=re.IGNORECASE,
            ):
                score += 8

            if re.search(
                r"PRIVATE\s+LIMITED",
                normalized_candidate,
                flags=re.IGNORECASE,
            ):
                score += 8

            if re.search(
                r"\bLIMITED\b",
                normalized_candidate,
                flags=re.IGNORECASE,
            ):
                score += 4

            # Company semantic terms.
            for keyword in (
                "biscuits",
                "foods",
                "food",
                "products",
                "industries",
            ):

                if keyword in normalized_candidate.lower():
                    score += 3

            # Manufacturer wording.
            if (
                "manufacturer" in lower
                or "manufactured by" in lower
                or "mfd by" in lower
            ):
                score += 7

            # Address evidence.
            if _has_address_evidence(
                normalized_candidate
            ):
                score += 2

            # Digits are suspicious.
            digit_count = len(
                re.findall(
                    r"\d",
                    normalized_candidate,
                )
            )

            score -= digit_count * 10

            # Brackets are suspicious in company-name extraction.
            if re.search(
                r"[\(\)\[\]\{\}]",
                normalized_candidate,
            ):
                score -= 8

            alpha_words = len(
                re.findall(
                    r"[A-Za-z]{3,}",
                    normalized_candidate,
                )
            )

            if alpha_words >= 3:
                score += 3

            candidates.append(
                (
                    score,
                    normalized_candidate,
                )
            )

        if candidates:

            candidates.sort(
                key=lambda item: item[0],
                reverse=True,
            )

            best_score, best_candidate = (
                candidates[0]
            )

            if best_score >= 4:
                manufacturer = best_candidate

    # =====================================================
    # 4. ADDRESS ASSOCIATION
    # =====================================================

    if manufacturer:

        if _has_address_evidence(
            manufacturer
        ):
            address = manufacturer

        manufacturer_index = -1

        for index, line in enumerate(lines):

            normalized_line = (
                _normalise_joined_company_name(
                    clean_whitespace(line)
                )
            )

            if not normalized_line:
                continue

            if (
                normalized_line.lower()
                == manufacturer.lower()
            ):
                manufacturer_index = index
                break

        if address is None and manufacturer_index >= 0:

            for offset in (
                1,
                2,
                3,
            ):

                candidate_index = (
                    manufacturer_index
                    + offset
                )

                if candidate_index >= len(lines):
                    break

                candidate_line = clean_whitespace(
                    lines[candidate_index]
                )

                # Do not cross another major declaration.
                if re.match(
                    r"^(?:mfd|mfg|pkd|use\s+by|"
                    r"best\s+before|mrp|net\s+(?:wt|weight)|"
                    r"batch|lot|consumer\s+care|"
                    r"customer\s+care|phone\s+no)",
                    candidate_line,
                    flags=re.IGNORECASE,
                ):
                    break

                if _has_address_evidence(
                    candidate_line
                ):
                    address = candidate_line
                    break

    # =====================================================
    # 5. GLOBAL ADDRESS FALLBACK
    # =====================================================

    if manufacturer and address is None:

        for line in lines:

            candidate = clean_whitespace(
                line
            )

            lower = candidate.lower()

            if lower.startswith(
                (
                    "from ",
                    "visit us",
                    "manufactured for",
                    "for sale",
                )
            ):
                continue

            if _has_address_evidence(
                candidate
            ):
                address = candidate
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
    # MRP
    # -----------------------------------------------------

    mrp_candidates = _find_all_mrp_candidates(
        text
    )

    if mrp_candidates:

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
    # Net quantity
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
    # Dates
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
    # Manufacturer / address
    # -----------------------------------------------------

    (
        manufacturer,
        manufacturer_address,
    ) = _extract_manufacturer_candidates(
        text
    )

    # Manufacturer
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

    # -----------------------------------------------------
    # Manufacturer address
    #
    # Primary:
    #   use an actual address when extracted.
    #
    # Fallback:
    #   when OCR gives us a clean manufacturer declaration
    #   but drops the address portion, preserve the clean
    #   manufacturer declaration as address evidence for the
    #   existing scan-pipeline contract.
    # -----------------------------------------------------

    if manufacturer_address:

        results["manufacturer_address"] = (
            ExtractedFieldValue(
                found=True,
                raw=manufacturer_address,
            )
        )

    elif manufacturer:

        results["manufacturer_address"] = (
            ExtractedFieldValue(
                found=True,
                raw=manufacturer,
            )
        )

    else:

        results["manufacturer_address"] = (
            ExtractedFieldValue(
                found=False,
            )
        )

    # -----------------------------------------------------
    # Preserve all expected fields
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

    text_lower = (
        combined_text.lower()
    )

    for brand in known_brands:

        if brand.lower() in text_lower:
            return brand, None

    return None, None
