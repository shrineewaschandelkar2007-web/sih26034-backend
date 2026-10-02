"""
Thin wrapper around PaddleOCR. Loaded once as a lazy singleton so the
model is not reloaded on every request (which would be far too slow
for a live demo).
"""

import threading

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_reader = None
_load_error: str | None = None


def get_ocr_reader():
    """
    Returns the shared PaddleOCR instance, initializing it on first
    call. Any initialization failure is cached so we don't retry a
    slow, doomed import on every request; the OCR service surfaces
    this as status="unavailable" instead of crashing the API.
    """
    global _reader, _load_error
    if _reader is not None or _load_error is not None:
        return _reader

    with _lock:
        if _reader is not None or _load_error is not None:
            return _reader
        settings = get_settings()
        try:
            from paddleocr import PaddleOCR  # imported lazily - heavy dependency

            _reader = PaddleOCR(lang=settings.ocr_lang, enable_mkldnn=settings.ocr_enable_mkldnn)
            logger.info("PaddleOCR initialized (lang=%s)", settings.ocr_lang)
        except Exception as exc:  # noqa: BLE001
            _load_error = repr(exc)
            logger.error("PaddleOCR failed to initialize: %s", _load_error)
    return _reader


def ocr_load_error() -> str | None:
    return _load_error
