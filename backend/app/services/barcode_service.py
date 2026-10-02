import cv2
import numpy as np

from app.core.logging import get_logger
from app.models.barcode_model import decoder_load_error, get_decoder
from app.schemas.barcode import BarcodeResult
from app.utils.versions import package_version

logger = get_logger(__name__)


def run_barcode_scan(image_bgr: np.ndarray) -> BarcodeResult:
    result = _run_barcode_scan(image_bgr)
    result.engine_version = package_version("pyzbar")
    return result


def _run_barcode_scan(image_bgr: np.ndarray) -> BarcodeResult:
    decode = get_decoder()
    if decode is None:
        return BarcodeResult(found=False, error_message=f"Decoder unavailable: {decoder_load_error()}")

    try:
        results = decode(image_bgr)
        if not results:
            # Retry once with an Otsu threshold - helps with glare/low-contrast photos.
            gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            results = decode(thresh)

        if not results:
            return BarcodeResult(found=False)

        best = results[0]
        x, y, w, h = best.rect
        return BarcodeResult(
            found=True,
            value=best.data.decode("utf-8", errors="ignore"),
            format=str(best.type),
            confidence=1.0,  # ZBar doesn't expose a confidence score; a clean decode is binary
            bbox=[x, y, w, h],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Barcode decoding failed: %s", exc)
        return BarcodeResult(found=False, error_message=repr(exc))
