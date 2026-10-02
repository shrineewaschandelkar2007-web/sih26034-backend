import re


def clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def fix_common_ocr_confusions(text: str, *, numeric_context: bool = False) -> str:
    """
    Only apply O/0, I/1-style corrections where safe (i.e. inside a
    numeric-looking token). Applying these globally on free text would
    corrupt real letters (e.g. turning "FOOD" into "F00D").
    """
    if not numeric_context:
        return text
    fixed = text
    fixed = fixed.replace("O", "0").replace("o", "0")
    fixed = fixed.replace("I", "1").replace("l", "1")
    fixed = fixed.replace("S", "5")
    return fixed


def looks_numeric_token(token: str) -> bool:
    # Drop a currency prefix / brackets, then require the rest to look like a number that OCR may have garbled.
    stripped = re.sub(r"^(?:₹|rs\.?|inr)\s*", "", token.strip(" ()"), flags=re.IGNORECASE)
    return bool(re.fullmatch(r"[0-9OoIlS.,/]+", stripped)) if stripped else False
