import re

_UNIT_ALIASES = {
    "g": "g",
    "gm": "g",
    "gms": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "kgs": "kg",
    "ml": "ml",
    "mls": "ml",
    "l": "l",
    "lt": "l",
    "ltr": "l",
    "litre": "l",
    "liter": "l",
    "litres": "l",
}

_QUANTITY_RE = re.compile(
    r"(\d+\.?\d*)\s*(g|gm|gms|gram|grams|kg|kgs|ml|mls|l|lt|ltr|litre|liter|litres)\b",
    flags=re.IGNORECASE,
)


def normalize_unit(raw_unit: str) -> str | None:
    return _UNIT_ALIASES.get(raw_unit.strip().lower())


def parse_net_quantity(raw: str) -> tuple[float | None, str | None]:
    """
    Parses forms like '200 g+50 EXTRA=250 g', '200 g+50  extra=250' or
    'Net Wt. 71.4 g' into a (value, unit) pair.

    Indian labels often print the final total after '=' - sometimes
    without repeating the unit ('=250'). If a '=TOTAL' is present it wins,
    taking its unit from the total itself or, failing that, from the
    first quantity+unit on the line. Otherwise the last quantity+unit
    found is used.
    """
    matches = list(_QUANTITY_RE.finditer(raw))
    if not matches:
        return None, None

    total = re.search(r"=\s*(\d+\.?\d*)\s*(g|gm|gms|gram|grams|kg|kgs|ml|mls|l|lt|ltr|litre|liter|litres)?\b", raw, flags=re.IGNORECASE)
    if total:
        unit = normalize_unit(total.group(2)) if total.group(2) else normalize_unit(matches[0].group(2))
        return float(total.group(1)), unit

    last = matches[-1]
    return float(last.group(1)), normalize_unit(last.group(2))


def normalize_currency_prefix(raw: str) -> str:
    """Collapses Rs / Rs. / INR / ₹ variants for downstream MRP parsing."""
    cleaned = re.sub(r"(?i)\b(rs\.?|inr)\b", "₹", raw)
    return cleaned
