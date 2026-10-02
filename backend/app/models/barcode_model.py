"""
pyzbar/ZBar is a classical decoder, not a learned model - we treat it
honestly as a decoding library behind this interface (per spec 5.2),
so a different detector/decoder can be swapped in later without
touching barcode_service.py's callers.
"""

from app.core.logging import get_logger

logger = get_logger(__name__)

_import_error: str | None = None


def get_decoder():
    """Returns the pyzbar.decode callable, or None if ZBar isn't available."""
    global _import_error
    try:
        from pyzbar.pyzbar import decode

        return decode
    except Exception as exc:  # noqa: BLE001
        _import_error = repr(exc)
        logger.error("pyzbar/ZBar unavailable: %s", _import_error)
        return None


def decoder_load_error() -> str | None:
    return _import_error
