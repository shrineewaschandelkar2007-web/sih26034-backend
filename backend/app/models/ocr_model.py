"""
Thin wrapper around PaddleOCR. Loaded once as a lazy singleton so the
model is not reloaded on every request (which would be far too slow
for a live demo).

The Render free instance has limited memory, so this wrapper explicitly
uses lightweight PP-OCRv5 mobile models and disables optional OCR
pipeline stages that are not required for packaged-label compliance.
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
    Returns the shared PaddleOCR instance.

    Uses lightweight mobile OCR models to reduce memory usage on the
    Render free instance.

    Initialization is lazy and happens only once. Any initialization
    failure is cached so the API does not repeatedly retry a heavy
    model load on every request.
    """
    global _reader, _load_error

    if _reader is not None or _load_error is not None:
        return _reader

    with _lock:
        if _reader is not None or _load_error is not None:
            return _reader

        settings = get_settings()

        try:
            from paddleocr import PaddleOCR

            _reader = PaddleOCR(
                # Keep the configured language.
                lang=settings.ocr_lang,

                # Lightweight PP-OCRv5 mobile models.
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="en_PP-OCRv5_mobile_rec",

                # Disable optional pipeline stages to reduce memory use.
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,

                # Keep MKL-DNN setting from application config.
                enable_mkldnn=settings.ocr_enable_mkldnn,

                # Process one text recognition item at a time.
                text_recognition_batch_size=1,

                # Reduce maximum image side used for text detection.
                text_det_limit_side_len=640,
                text_det_limit_type="max",
            )

            logger.info(
                "PaddleOCR initialized with lightweight mobile models "
                "(det=PP-OCRv5_mobile_det, rec=en_PP-OCRv5_mobile_rec, lang=%s)",
                settings.ocr_lang,
            )

        except Exception as exc:  # noqa: BLE001
            _load_error = repr(exc)
            logger.error(
                "PaddleOCR failed to initialize: %s",
                _load_error,
            )

    return _reader


def ocr_load_error() -> str | None:
    return _load_error