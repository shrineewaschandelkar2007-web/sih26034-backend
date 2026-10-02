"""
Reusable OCR service. Never crashes the whole API because one image
failed OCR - always returns an OCRResult, with status="failed" or
"unavailable" instead of raising, so /scans can still return a
partial result (per spec section 15).
"""

import numpy as np

from app.core.logging import get_logger
from app.models.ocr_model import get_ocr_reader, ocr_load_error
from app.schemas.ocr import OCRResult, OCRTextBlock
from app.utils.versions import package_version

logger = get_logger(__name__)


def run_ocr(image_bgr: np.ndarray) -> OCRResult:
    result = _run_ocr(image_bgr)
    result.engine_version = package_version("paddleocr")
    return result


def _run_ocr(image_bgr: np.ndarray) -> OCRResult:
    reader = get_ocr_reader()
    if reader is None:
        return OCRResult(
            status="unavailable",
            error_message=f"PaddleOCR not initialized: {ocr_load_error()}",
        )

    try:
        result = reader.predict(image_bgr)
    except Exception as exc:  # noqa: BLE001
        logger.error("OCR inference failed: %s", exc)
        return OCRResult(status="failed", error_message=repr(exc))

    if not result:
        return OCRResult(status="success", raw_text=[], combined_text="", average_confidence=0.0)

    page = result[0]
    texts = page.get("rec_texts", [])
    scores = page.get("rec_scores", [])
    polys = page.get("rec_polys", None)

    blocks: list[OCRTextBlock] = []
    for i, (text, score) in enumerate(zip(texts, scores, strict=False)):
        bbox = None
        if polys is not None and i < len(polys):
            try:
                bbox = [[float(pt[0]), float(pt[1])] for pt in polys[i]]
            except Exception:  # noqa: BLE001
                bbox = None
        blocks.append(OCRTextBlock(text=text, confidence=float(score), bbox=bbox))

    combined = "\n".join(texts)
    avg_conf = float(sum(scores) / len(scores)) if scores else 0.0

    return OCRResult(
        status="success",
        raw_text=blocks,
        combined_text=combined,
        average_confidence=round(avg_conf, 4),
    )
