"""
Small security helpers. Auth (Supabase Auth) is optional for the SIH
prototype; this module keeps hooks ready without forcing login flows
into the first demo.
"""

import re
import uuid

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(filename: str) -> str:
    """Never trust the client-provided filename as-is."""
    base = filename.strip().replace(" ", "_")
    base = _SAFE_FILENAME_RE.sub("", base)
    return base[-100:] or "upload"


def new_scan_id() -> str:
    return str(uuid.uuid4())
