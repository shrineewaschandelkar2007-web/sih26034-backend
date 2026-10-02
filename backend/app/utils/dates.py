import re
from datetime import datetime

# Common label date formats seen on Indian packaged-commodity labels.
_DATE_PATTERNS = [
    "%d/%m/%Y",
    "%d/%m/%y",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%b %Y",
    "%B %Y",
]

_DATE_TOKEN_RE = re.compile(r"\d{1,2}[/\-.]\d{1,2}(?:[/\-.]\d{2,4})?|[A-Za-z]{3,9}\s?\d{4}")


def extract_date_token(text: str) -> str | None:
    match = _DATE_TOKEN_RE.search(text)
    return match.group(0) if match else None


def try_parse_date(raw: str) -> str | None:
    """
    Best-effort normalization to ISO (YYYY-MM-DD). Returns None rather
    than guessing if the format is ambiguous or unparseable — never
    invent a date the label doesn't clearly state.
    """
    raw = raw.strip()
    for fmt in _DATE_PATTERNS:
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.date().isoformat()
        except ValueError:
            continue
    return None
