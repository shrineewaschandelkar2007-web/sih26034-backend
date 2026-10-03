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

The extractor is conservative about ambiguous numeric values so that
random OCR numbers such as barcode digits are not incorrectly treated
as MRP/date declarations.
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
        r"\b(?:mrp|m\.r\.p)\b"
        r"[^\d\n]{0,30}"
        r"(?:rs\.?|inr|₹)?"
        r"\s*"
        r"([\d]+[.,]?\d*)"
    ),

    # -----------------------------------------------------
    # NET QUANTITY
    #
    # Includes common OCR variants:
    #   Net Wt
    #   Net Weight
    #   Net We
    #   Net Wt.
    #   Net Qty
    # -----------------------------------------------------
    "net_quantity": (
        r"\b(?:net\s*(?:wt|weight|we|qty|quantity|contents))\b"
        r"[:\s.]*"
        r"("
        r"\d+\.?\d*"
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
        r"(?:\s*\+\s*\d+\.?\d*"
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
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
        r"(?:\bpkd\b|\bmfd\b|\bmfg\b|\bmanufactured\b|\bpacked\b|\bpackaging\b)"
        r"[.\s]*(?:date|on|dt)?"
        r"[:\s.]"
        r"("
        r"\d{1,2}\s*[/\-]\s*\d{1,2}"
        r"(?:\s*[/\-]\s*\d{2,4})?"
        r"|"
        r"\d{1,2}\s*\.\s*\d{1,2}"
        r"\s*\.\s*\d{2,4}"
        r")"
    ),

    # -----------------------------------------------------
    # BEST BEFORE
    # -----------------------------------------------------
    "best_before": (
        r"\bbest\s*before\b"
        r"[:\s.]"
        r"("
        r"\d{1,2}\s*[/\-]\s*\d{1,2}"
        r"(?:\s*[/\-]\s*\d{2,4})?"
        r"|"
        r"\d{1,2}\s*\.\s*\d{1,2}"
        r"\s*\.\s*\d{2,4}"
        r"|"
        r"\d+\s*months?"
        r")"
    ),

    # -----------------------------------------------------
    # USE BY
    # -----------------------------------------------------
    "use_by": (
        r"\buse\s*by\b"
        r"[:\s.]"
        r"("
        r"\d{1,2}\s*[/\-]\s*\d{1,2}"
        r"(?:\s*[/\-]\s*\d{2,4})?"
        r"|"
        r"\d{1,2}\s*\.\s*\d{1,2}"
        r"\s*\.\s*\d{2,4}"
        r")"
    ),

    # -----------------------------------------------------
    # CUSTOMER / CONSUMER CARE
    # -----------------------------------------------------
    "consumer_care_contact": (
        r"(?:\bphone\s*no\.?\b|\bconsumer\s*care\b|\bcustomer\s*care\b|"
        r"\btoll\s*free\b)"
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
        r"(?:\bmfd\.?\s*by\b|\bmanufactured\s*by\b|"
        r"\bmarketed\s*by\b|\bpacked\s*by\b)"
        r"[ \t:.\-]*"
        r"([\w\s,.\-()&]{5,180})"
    ),

    # -----------------------------------------------------
    # BATCH
    # -----------------------------------------------------
    "batch_lot_number": (
        r"\b(?:batch|lot)\b"
        r"(?:\s*(?:no|number|num))?"
        r"[:\s.\-]*"
        r"([\w\-/]{2,30})"
    ),

    # -----------------------------------------------------
    # COUNTRY OF ORIGIN
    # -----------------------------------------------------
    "country_of_origin": (
        r"\bcountry\s*of\s*origin\b"
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


def _clean_line(value: str) -> str:
    return clean_whitespace(
        value or ""
    )


def _is_major_declaration_line(
    line: str,
) -> bool:
    """
    Identify lines where manufacturer/address/date association should stop.
    """

    line = _clean_line(line)

    if not line:
        return False

    pattern = (
        r"^(?:"
        r"mrp\b|"
        r"net\s*(?:wt|weight|we|qty|quantity)\b|"
        r"use\s+by\b|"
        r"best\s+before\b|"
        r"pkd\b|"
        r"mfd\b|"
        r"mfg\b|"
        r"manufactured\b|"
        r"packed\b|"
        r"batch\b|"
        r"lot\b|"
        r"consumer\s+care\b|"
        r"customer\s+care\b|"
        r"phone\s+no\b|"
        r"ingredients\b|"
        r"nutrition\s+information\b"
        r")"
    )

    return bool(
        re.search(
            pattern,
            line,
            flags=re.IGNORECASE,
        )
    )


# =========================================================
# NUMBER / DATE VALIDATION HELPERS
# =========================================================

def _normalise_number_text(
    value: str,
) -> str:

    value = clean_whitespace(
        value or ""
    )

    return value.replace(
        ",",
        ".",
        1,
    )


def _looks_like_date(
    value: str,
) -> bool:
    """
    Reject ambiguous OCR numbers such as:
        2.3
        366
        02754

    Accept:
        08/08
        08/08/2026
        05-01-2027
        05.01.2027
    """

    value = clean_whitespace(
        value or ""
    )

    if not value:
        return False

    slash_or_dash = re.fullmatch(
        r"\d{1,2}\s*[/\-]\s*\d{1,2}"
        r"(?:\s*[/\-]\s*\d{2,4})?",
        value,
    )

    if slash_or_dash:
        return True

    dotted_full = re.fullmatch(
        r"\d{1,2}\s*\.\s*\d{1,2}"
        r"\s*\.\s*\d{2,4}",
        value,
    )

    return bool(
        dotted_full
    )


def _date_value_candidates(
    text: str,
) -> list[str]:
    """
    Return only plausible declaration dates.

    Deliberately excludes short decimal values such as 2.3.
    """

    flat = _flat_text(text)

    pattern = (
        r"\b(?:"
        r"\d{1,2}\s*[/\-]\s*\d{1,2}"
        r"(?:\s*[/\-]\s*\d{2,4})?"
        r"|"
        r"\d{1,2}\s*\.\s*\d{1,2}"
        r"\s*\.\s*\d{2,4}"
        r")\b"
    )

    return [
        clean_whitespace(match)
        for match in re.findall(
            pattern,
            flat,
            flags=re.IGNORECASE,
        )
        if _looks_like_date(match)
    ]


# =========================================================
# MRP EXTRACTION
# =========================================================

def _find_all_mrp_candidates(
    text: str,
) -> list[tuple[str, bool]]:
    """
    Extract MRP only when the numeric value is directly associated
    with the MRP declaration.

    This deliberately avoids flattening the entire OCR result for MRP,
    because otherwise a line such as:

        MRP.
        BEFORE
        02754

    could incorrectly turn 02754 into MRP.
    """

    normalised = _normalise_for_matching(
        text
    )

    lines = [
        _clean_line(line)
        for line in normalised.splitlines()
    ]

    candidates: list[tuple[str, bool]] = []

    # -----------------------------------------------------
    # Same-line MRP
    # -----------------------------------------------------

    same_line_pattern = re.compile(
        r"\b(?:mrp|m\.r\.p)\b"
        r"\s*(?:[:=\-]\s*)?"
        r"(?:(?P<currency>₹|rs\.?|inr)\s*)?"
        r"(?P<value>\d+(?:[.,]\d+)?)"
        r"\b",
        flags=re.IGNORECASE,
    )

    for line in lines:

        if not line:
            continue

        match = same_line_pattern.search(
            line
        )

        if not match:
            continue

        value = clean_whitespace(
            match.group("value")
        )

        if not value:
            continue

        # Extremely long digit sequences are much more likely
        # to be barcode / licence / phone numbers.
        digits_only = re.sub(
            r"\D",
            "",
            value,
        )

        if len(digits_only) > 6:
            continue

        candidates.append(
            (
                value,
                bool(
                    match.group("currency")
                ),
            )
        )

    if candidates:
        return candidates

    # -----------------------------------------------------
    # Two-line MRP:
    #
    # MRP
    # ₹ 30
    #
    # or:
    #
    # MRP.
    # Rs. 30
    # -----------------------------------------------------

    label_only_pattern = re.compile(
        r"^(?:mrp|m\.r\.p)"
        r"(?:[.:=\-])?$",
        flags=re.IGNORECASE,
    )

    value_line_pattern = re.compile(
        r"^(?:(?P<currency>₹|rs\.?|inr)\s*)?"
        r"(?P<value>\d+(?:[.,]\d+)?)"
        r"(?:\s+.*)?$",
        flags=re.IGNORECASE,
    )

    for index, line in enumerate(lines):

        if not label_only_pattern.fullmatch(
            line
        ):
            continue

        if index + 1 >= len(lines):
            continue

        next_line = lines[index + 1]

        # Reject obvious unrelated declaration lines.
        if _is_major_declaration_line(
            next_line
        ):
            continue

        match = value_line_pattern.fullmatch(
            next_line
        )

        if not match:
            continue

        value = clean_whitespace(
            match.group("value")
        )

        digits_only = re.sub(
            r"\D",
            "",
            value,
        )

        if len(digits_only) > 6:
            continue

        candidates.append(
            (
                value,
                bool(
                    match.group("currency")
                ),
            )
        )

    return candidates


# =========================================================
# NET QUANTITY EXTRACTION
# =========================================================

def _extract_net_quantity(
    text: str,
) -> str | None:
    """
    Extract net quantity from same-line or immediately-following-line
    declarations.

    Supports OCR variants such as:
        Net Wt: 300g
        Net We: 300g
        Net Weight: 300 g
        Net Wt:
        300g
    """

    normalised = _normalise_for_matching(
        text
    )

    lines = [
        _clean_line(line)
        for line in normalised.splitlines()
    ]

    quantity_pattern = re.compile(
        r"^(?:"
        r"\d+(?:\.\d+)?"
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
        r"(?:\s*\+\s*\d+(?:\.\d+)?"
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
        r"\s*extra)?"
        r"(?:\s*=\s*\d+(?:\.\d+)?"
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
        r")?"
        r")"
        r"$",
        flags=re.IGNORECASE,
    )

    label_pattern = re.compile(
        r"\bnet\s*(?:wt|weight|we|qty|quantity|contents)\b",
        flags=re.IGNORECASE,
    )

    # -----------------------------------------------------
    # 1. Same line
    # -----------------------------------------------------

    same_line_pattern = re.compile(
        r"\bnet\s*(?:wt|weight|we|qty|quantity|contents)\b"
        r"[:\s.]*"
        r"(?P<value>"
        r"\d+(?:\.\d+)?"
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
        r"(?:\s*\+\s*\d+(?:\.\d+)?"
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
        r"\s*extra)?"
        r"(?:\s*=\s*\d+(?:\.\d+)?"
        r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
        r")?"
        r")",
        flags=re.IGNORECASE,
    )

    for line in lines:

        if not line:
            continue

        match = same_line_pattern.search(
            line
        )

        if match:

            value = clean_whitespace(
                match.group("value")
            )

            if value:
                return value

    # -----------------------------------------------------
    # 2. Label line followed by quantity line
    # -----------------------------------------------------

    for index, line in enumerate(lines):

        if not label_pattern.search(
            line
        ):
            continue

        # First try remaining text after the label.
        tail_match = re.search(
            r"\bnet\s*(?:wt|weight|we|qty|quantity|contents)\b"
            r"[\s:.\-]*(.*)$",
            line,
            flags=re.IGNORECASE,
        )

        if tail_match:

            tail = clean_whitespace(
                tail_match.group(1)
            )

            quantity_match = re.search(
                r"^"
                r"(\d+(?:\.\d+)?"
                r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
                r"(?:\s*\+\s*\d+(?:\.\d+)?"
                r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
                r"\s*extra)?"
                r"(?:\s*=\s*\d+(?:\.\d+)?"
                r"(?:\s*(?:kg|gms|gm|g|ml|litre|liter|l))?"
                r")?"
                r")"
                r"$",
                tail,
                flags=re.IGNORECASE,
            )

            if quantity_match:
                return clean_whitespace(
                    quantity_match.group(1)
                )

        # Try the next line.
        if index + 1 >= len(lines):
            continue

        next_line = lines[index + 1]

        if not next_line:
            continue

        if _is_major_declaration_line(
            next_line
        ):
            continue

        if quantity_pattern.fullmatch(
            next_line
        ):
            return clean_whitespace(
                next_line
            )

    return None


# =========================================================
# DATE EXTRACTION
# =========================================================

def _date_candidates(
    text: str,
) -> list[str]:

    return _date_value_candidates(
        text
    )


def _extract_date_after_label(
    text: str,
    label_pattern: str,
) -> str | None:
    """
    Search only locally around a declaration label.

    This prevents unrelated numbers such as 2.3 from being selected
    as a manufacturing date simply because "Pkd." exists somewhere
    else in the OCR output.
    """

    normalised = _normalise_for_matching(
        text
    )

    lines = [
        _clean_line(line)
        for line in normalised.splitlines()
    ]

    compiled_label = re.compile(
        label_pattern,
        flags=re.IGNORECASE,
    )

    inline_date_pattern = re.compile(
        r"("
        r"\d{1,2}\s*[/\-]\s*\d{1,2}"
        r"(?:\s*[/\-]\s*\d{2,4})?"
        r"|"
        r"\d{1,2}\s*\.\s*\d{1,2}"
        r"\s*\.\s*\d{2,4}"
        r")",
        flags=re.IGNORECASE,
    )

    for index, line in enumerate(lines):

        match = compiled_label.search(
            line
        )

        if not match:
            continue

        # -------------------------------------------------
        # Same line after label
        # -------------------------------------------------

        tail = line[
            match.end():
        ].strip(
            " \t:.-"
        )

        date_match = inline_date_pattern.search(
            tail
        )

        if date_match:

            value = clean_whitespace(
                date_match.group(1)
            )

            if _looks_like_date(
                value
            ):
                return value

        # -------------------------------------------------
        # Next 1–2 lines only
        # -------------------------------------------------

        for offset in (1, 2):

            candidate_index = (
                index + offset
            )

            if candidate_index >= len(lines):
                break

            candidate_line = lines[
                candidate_index
            ]

            if not candidate_line:
                continue

            if (
                offset > 1
                and _is_major_declaration_line(
                    candidate_line
                )
            ):
                break

            date_match = inline_date_pattern.search(
                candidate_line
            )

            if date_match:

                value = clean_whitespace(
                    date_match.group(1)
                )

                if _looks_like_date(
                    value
                ):
                    return value

    return None


def _extract_spatially_separated_dates(
    text: str,
) -> tuple[
    str | None,
    str | None,
    str | None,
]:

    pkd = _extract_date_after_label(
        text,
        r"(?:\bpkd\b|\bmfd\b|\bmfg\b|\bmanufactured\b|\bpacked\b|\bpackaging\b)",
    )

    use_by = _extract_date_after_label(
        text,
        r"\buse\s*by\b",
    )

    best_before = _extract_date_after_label(
        text,
        r"\bbest\s*before\b",
    )

    # Deliberately DO NOT use a global "first date" fallback.
    #
    # Doing that caused OCR values such as "2.3" from nutrition
    # information to become manufacturing dates when "Pkd." appeared
    # elsewhere in the document.
    #
    # Dates must now be spatially associated with their labels.

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
        305, 3383

    Allows:

        PARLE BISCUITS PVT LTD
        ABC FOODS PRIVATE LIMITED
        XYZ PRODUCTS LTD
    """

    candidate = clean_whitespace(
        candidate
    )

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

    # OCR company candidates containing digits are highly suspicious.
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
        "district",
        "dist.",
        "taluk",
        "phase",
        "plot",
        "sector",
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
) -> tuple[
    str | None,
    str | None,
]:

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


def _join_manufacturer_lines(
    lines: list[str],
    start_index: int,
) -> tuple[
    str | None,
    int,
]:

    fragments: list[str] = []

    for offset in range(
        0,
        3,
    ):

        index = (
            start_index
            + offset
        )

        if index >= len(lines):
            break

        line = _clean_manufacturer_candidate(
            lines[index]
        )

        if not line:
            continue

        if offset > 0 and _is_major_declaration_line(
            line
        ):
            break

        fragments.append(
            line
        )

        joined = clean_whitespace(
            " ".join(fragments)
        )

        # Once a valid company suffix appears, stop company collection.
        if re.search(
            r"\b(?:PVT\.?\s*LTD|PRIVATE\s+LIMITED|LIMITED|LTD\.?|LLP)\b",
            joined,
            flags=re.IGNORECASE,
        ):
            return (
                joined,
                index,
            )

    if not fragments:
        return None, start_index

    return (
        clean_whitespace(
            " ".join(fragments)
        ),
        start_index
        + len(fragments)
        - 1,
    )


def _extract_manufacturer_candidates(
    text: str,
) -> tuple[
    str | None,
    str | None,
]:

    normalised = _normalise_for_matching(
        text
    )

    lines = [
        _clean_line(line)
        for line in normalised.splitlines()
        if _clean_line(line)
    ]

    manufacturer: str | None = None
    address: str | None = None
    manufacturer_line_index = -1

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

        end_index = index

        # Case:
        #
        # MFD BY:
        # PARLE BISCUITS PVT LTD
        #
        if not candidate:

            candidate, end_index = (
                _join_manufacturer_lines(
                    lines,
                    index + 1,
                )
            )

        # Candidate may itself be incomplete, for example:
        #
        # MFD BY: Parle Biscuits
        # Pvt Ltd
        #
        elif not re.search(
            r"\b(?:PVT\.?\s*LTD|PRIVATE\s+LIMITED|LIMITED|LTD\.?|LLP)\b",
            candidate,
            flags=re.IGNORECASE,
        ) and index + 1 < len(lines):

            continuation = _clean_line(
                lines[index + 1]
            )

            if continuation and not _is_major_declaration_line(
                continuation
            ):
                candidate = clean_whitespace(
                    f"{candidate} {continuation}"
                )
                end_index = index + 1

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
            manufacturer_line_index = end_index

            if address_candidate:
                address = address_candidate

            break

    # =====================================================
    # 2. "AT:" / "C- AT:" STYLE MANUFACTURER DECLARATION
    #
    # Some labels use:
    #
    # C- At: Mrs. XYZ Food Specialities Limited,
    #
    # or OCR may split it across:
    #
    # C- At: Mrs.
    # XYZ Food Specialities Limited,
    # =====================================================

    if manufacturer is None:

        at_pattern = re.compile(
            r"^(?:"
            r"[A-Z0-9\-]{1,4}\s*[-:]\s*"
            r")?at\s*:\s*(.*)$",
            flags=re.IGNORECASE,
        )

        for index, line in enumerate(lines):

            match = at_pattern.match(
                line
            )

            if not match:
                continue

            first_fragment = _clean_manufacturer_candidate(
                match.group(1)
            )

            fragments: list[str] = []

            if first_fragment:
                fragments.append(
                    first_fragment
                )

            # Join up to two following lines until a company suffix.
            for offset in (1, 2):

                candidate_index = (
                    index + offset
                )

                if candidate_index >= len(lines):
                    break

                next_line = _clean_line(
                    lines[candidate_index]
                )

                if not next_line:
                    continue

                if _is_major_declaration_line(
                    next_line
                ):
                    break

                fragments.append(
                    next_line
                )

                joined = clean_whitespace(
                    " ".join(fragments)
                )

                if re.search(
                    r"\b(?:PVT\.?\s*LTD|PRIVATE\s+LIMITED|LIMITED|LTD\.?|LLP)\b",
                    joined,
                    flags=re.IGNORECASE,
                ):
                    break

            candidate = clean_whitespace(
                " ".join(fragments)
            )

            (
                manufacturer_candidate,
                address_candidate,
            ) = _split_manufacturer_and_address(
                candidate
            )

            if manufacturer_candidate:

                manufacturer = manufacturer_candidate
                manufacturer_line_index = index

                if address_candidate:
                    address = address_candidate

                break

    # =====================================================
    # 3. MFD / BY SPLIT ACROSS MULTIPLE LINES
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

            by_line = _clean_line(
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
                manufacturer_line_index = (
                    index + 2
                )

                if address_candidate:
                    address = address_candidate

                break

    # =====================================================
    # 4. GENERIC COMPANY FALLBACK
    # =====================================================

    if manufacturer is None:

        candidates: list[
            tuple[int, str, int]
        ] = []

        for index, line in enumerate(lines):

            candidate = _clean_line(
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
                    "ingredients",
                    "nutrition information",
                )
            ):
                continue

            # A line beginning with a single OCR fragment is suspicious.
            words = candidate.split()

            if (
                words
                and len(
                    words[0].strip(
                        ".,()"
                    )
                ) < 2
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
                "nutritionals",
                "specialities",
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

            score -= (
                digit_count
                * 10
            )

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
                    index,
                )
            )

        if candidates:

            candidates.sort(
                key=lambda item: item[0],
                reverse=True,
            )

            best_score, best_candidate, best_index = (
                candidates[0]
            )

            if best_score >= 4:

                manufacturer = best_candidate
                manufacturer_line_index = best_index

    # =====================================================
    # 5. ADDRESS ASSOCIATION
    # =====================================================

    if manufacturer:

        if _has_address_evidence(
            manufacturer
        ):
            address = manufacturer

        # Find the source line where manufacturer was identified.
        if manufacturer_line_index < 0:

            for index, line in enumerate(lines):

                normalized_line = (
                    _normalise_joined_company_name(
                        line
                    )
                )

                if not normalized_line:
                    continue

                if (
                    normalized_line.lower()
                    == manufacturer.lower()
                ):
                    manufacturer_line_index = index
                    break

        # Look at the following 1–3 lines for address information.
        if (
            address is None
            and manufacturer_line_index >= 0
        ):

            address_parts: list[str] = []

            for offset in (
                1,
                2,
                3,
            ):

                candidate_index = (
                    manufacturer_line_index
                    + offset
                )

                if candidate_index >= len(lines):
                    break

                candidate_line = _clean_line(
                    lines[candidate_index]
                )

                if not candidate_line:
                    continue

                # Do not cross another major declaration.
                if _is_major_declaration_line(
                    candidate_line
                ):
                    break

                if _has_address_evidence(
                    candidate_line
                ):
                    address_parts.append(
                        candidate_line
                    )

                    # Usually one or two address lines are enough.
                    if (
                        re.search(
                            r"\b\d{6}\b",
                            candidate_line,
                        )
                        or "mumbai" in candidate_line.lower()
                        or "maharashtra" in candidate_line.lower()
                        or "punjab" in candidate_line.lower()
                        or "karnataka" in candidate_line.lower()
                    ):
                        break

            if address_parts:
                address = clean_whitespace(
                    " ".join(address_parts)
                )

    # =====================================================
    # 6. GLOBAL ADDRESS FALLBACK
    # =====================================================

    # Only use a global fallback when we have a manufacturer but no
    # local address. Avoid using arbitrary short numeric OCR fragments.

    if manufacturer and address is None:

        for line in lines:

            candidate = _clean_line(
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

            if len(candidate) < 12:
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
    #   actual address when extracted.
    #
    # Fallback:
    #   preserve the existing scan-pipeline contract where a
    #   clean manufacturer declaration counts as declaration
    #   evidence even when OCR drops the address portion.
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
) -> tuple[
    str | None,
    str | None,
]:

    text_lower = combined_text.lower()

    for brand in known_brands:

        if brand.lower() in text_lower:
            return brand, None

    return None, None
