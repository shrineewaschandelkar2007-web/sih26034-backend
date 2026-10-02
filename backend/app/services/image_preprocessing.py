"""
Upload -> validated array -> preprocessed array, ready for OCR/barcode/
tampering. Never mutates the original; callers keep the original bytes
for storage and pass the *returned* processed copy to the model layer.
"""

import cv2
import numpy as np

_MIN_UPSCALE_DIM = 800  # below this, upscale for OCR legibility
_MAX_DOWNSCALE_DIM = 1800  # above this, downscale to save memory/time


def preprocess_for_models(image_bgr: np.ndarray) -> np.ndarray:
    processed = image_bgr.copy()
    h, w = processed.shape[:2]
    longest_side = max(h, w)

    if longest_side < _MIN_UPSCALE_DIM:
        scale = _MIN_UPSCALE_DIM / longest_side
        processed = cv2.resize(processed, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    elif longest_side > _MAX_DOWNSCALE_DIM:
        scale = _MAX_DOWNSCALE_DIM / longest_side
        processed = cv2.resize(processed, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    return processed


def enhance_region_for_ocr(image_bgr: np.ndarray, *, upscale: int = 3) -> np.ndarray:
    """
    Used for zoomed-in re-OCR of a specific crop (e.g. a small date/batch
    strip) when the first pass over the full image doesn't yield a
    confident mfg_date/use_by match.
    """
    resized = cv2.resize(image_bgr, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced_gray = clahe.apply(gray)
    return cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2BGR)


def top_strip(image_bgr: np.ndarray, *, fraction: float = 0.20) -> np.ndarray:
    h, w = image_bgr.shape[:2]
    return image_bgr[0 : int(h * fraction), 0:w]
