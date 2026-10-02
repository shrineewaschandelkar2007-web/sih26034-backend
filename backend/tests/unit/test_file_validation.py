import io

import pytest
from PIL import Image

from app.core.errors import InvalidImageError
from app.core.security import sanitize_filename
from app.utils.file_validation import validate_and_decode_image

MAX = 5 * 1024 * 1024


def _png_bytes(size=(200, 200), color="white") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_valid_image_decodes_to_bgr_array():
    arr = validate_and_decode_image(_png_bytes(), max_bytes=MAX)
    assert arr.shape == (200, 200, 3)


def test_bgr_channel_order_is_correct():
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), (255, 0, 0)).save(buf, format="PNG")  # pure red in RGB
    arr = validate_and_decode_image(buf.getvalue(), max_bytes=MAX)
    assert tuple(arr[0, 0]) == (0, 0, 255)  # red in BGR


def test_empty_upload_rejected():
    with pytest.raises(InvalidImageError):
        validate_and_decode_image(b"", max_bytes=MAX)


def test_non_image_bytes_rejected():
    with pytest.raises(InvalidImageError):
        validate_and_decode_image(b"this is definitely not an image", max_bytes=MAX)


def test_renamed_text_file_rejected_even_if_it_claims_to_be_png():
    with pytest.raises(InvalidImageError):
        validate_and_decode_image(b"\x89PNG but actually text", max_bytes=MAX)


def test_truncated_image_rejected():
    with pytest.raises(InvalidImageError):
        validate_and_decode_image(_png_bytes()[:40], max_bytes=MAX)


def test_oversized_upload_rejected():
    with pytest.raises(InvalidImageError):
        validate_and_decode_image(_png_bytes(), max_bytes=10)


def test_tiny_image_rejected():
    with pytest.raises(InvalidImageError):
        validate_and_decode_image(_png_bytes(size=(5, 5)), max_bytes=MAX)


def test_filename_sanitization_strips_path_tricks():
    assert "/" not in sanitize_filename("../../etc/passwd")
    assert "\\" not in sanitize_filename("..\\..\\windows\\system32")
    assert sanitize_filename("my label (1).jpg") == "my_label_1.jpg"
    assert sanitize_filename("") == "upload"
