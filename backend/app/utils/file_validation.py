"""
Validate uploads before anything touches OCR/barcode/tampering models.
Never trust content-type header alone from the client; verify by
actually decoding the image.
"""

import io

import numpy as np
from PIL import Image

from app.core.errors import InvalidImageError


def validate_and_decode_image(raw_bytes: bytes, *, max_bytes: int) -> np.ndarray:
    """
    Returns a BGR numpy array (OpenCV convention) if the bytes are a
    genuinely decodable image, otherwise raises InvalidImageError.
    """
    if not raw_bytes:
        raise InvalidImageError("Uploaded file is empty.")

    if len(raw_bytes) > max_bytes:
        # Handled separately by ImageTooLargeError in the route, but guard here too.
        raise InvalidImageError("Uploaded file exceeds the maximum allowed size.")

    try:
        pil_image = Image.open(io.BytesIO(raw_bytes))
        pil_image.verify()  # cheap structural check, catches truncated/corrupt files

        # verify() invalidates the file pointer state; reopen to actually decode.
        pil_image = Image.open(io.BytesIO(raw_bytes))
        pil_image = pil_image.convert("RGB")
    except Exception as exc:
        raise InvalidImageError("Unsupported or unreadable image.") from exc

    # Guard against pathological decompression-bomb-style dimensions.
    width, height = pil_image.size
    if width * height > 60_000_000:  # ~60 megapixels
        raise InvalidImageError("Image resolution is unreasonably large.")
    if width < 20 or height < 20:
        raise InvalidImageError("Image resolution is too small to process.")

    rgb_array = np.array(pil_image)
    bgr_array = rgb_array[:, :, ::-1].copy()  # RGB -> BGR for OpenCV-based services
    return bgr_array
