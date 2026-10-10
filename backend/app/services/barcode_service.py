"""
Reusable barcode detection service using pyzbar / ZBar.

Detection strategy:

1. Try pyzbar on the original image.
2. Retry pyzbar on a small number of lightweight image variants.
3. If pyzbar cannot decode the barcode:
   - detect barcode-like regions using image morphology
   - crop the likely barcode region
   - OCR the human-readable barcode digits
   - reconstruct candidate EAN-13 values when OCR splits digits
   - accept only checksum-valid EAN-13 values

This fallback is designed for difficult package photographs where
the barcode bars are visible to a human but ZBar cannot decode them.
"""

from __future__ import annotations

import re
from typing import Any

import cv2
import numpy as np
import pytesseract

from app.core.logging import get_logger
from app.models.barcode_model import (
    decoder_load_error,
    get_decoder,
)
from app.schemas.barcode import BarcodeResult
from app.utils.versions import package_version

logger = get_logger(__name__)


# =============================================================
# Configuration
# =============================================================

MAX_WORKING_SIDE = 2200
MIN_UPSCALE_SIDE = 900

SUPPORTED_FORMATS = {
    "EAN13",
    "EAN8",
    "UPCA",
    "UPCE",
    "CODE128",
    "CODE39",
    "ITF",
    "I25",
    "CODABAR",
}

# Only use OCR fallback after pyzbar fails.
BARCODE_OCR_MIN_CONFIDENCE = 0.40

# Barcode-like contour minimum requirements.
MIN_BARCODE_REGION_WIDTH = 60
MIN_BARCODE_REGION_HEIGHT = 30
MIN_BARCODE_ASPECT_RATIO = 1.25
MIN_VERTICAL_GRADIENT_RATIO = 2.0


# =============================================================
# Public API
# =============================================================

def run_barcode_scan(
    image_bgr: np.ndarray,
) -> BarcodeResult:
    """
    Public barcode detection entry point.
    """

    result = _run_barcode_scan(
        image_bgr
    )

    result.engine_version = package_version(
        "pyzbar"
    )

    return result


# =============================================================
# Main barcode pipeline
# =============================================================

def _run_barcode_scan(
    image_bgr: np.ndarray,
) -> BarcodeResult:

    decode = get_decoder()

    if decode is None:

        return BarcodeResult(
            found=False,
            error_message=(
                "Decoder unavailable: "
                f"{decoder_load_error()}"
            ),
        )

    # ---------------------------------------------------------
    # Validate image
    # ---------------------------------------------------------

    if image_bgr is None:

        return BarcodeResult(
            found=False,
            error_message=(
                "Empty image supplied to barcode decoder."
            ),
        )

    if not isinstance(
        image_bgr,
        np.ndarray,
    ):

        return BarcodeResult(
            found=False,
            error_message=(
                "Invalid image type supplied to barcode decoder."
            ),
        )

    if image_bgr.size == 0:

        return BarcodeResult(
            found=False,
            error_message=(
                "Empty image supplied to barcode decoder."
            ),
        )

    try:

        # =====================================================
        # STAGE 1 — pyzbar / ZBar
        # =====================================================

        variants = _build_barcode_variants(
            image_bgr
        )

        all_results: list[Any] = []

        for variant_name, variant_image in variants:

            try:

                decoded = decode(
                    variant_image
                )

            except Exception as exc:  # noqa: BLE001

                logger.warning(
                    "Barcode decode failed for variant=%s: %s",
                    variant_name,
                    exc,
                )

                continue

            if not decoded:
                continue

            logger.info(
                "Barcode candidates found: "
                "variant=%s count=%d",
                variant_name,
                len(decoded),
            )

            all_results.extend(
                decoded
            )

        # -----------------------------------------------------
        # Use ZBar result if available.
        # -----------------------------------------------------

        if all_results:

            best = _select_best_barcode(
                all_results
            )

            if best is not None:

                result = _barcode_result_from_decoded(
                    best
                )

                if result is not None:
                    return result

        # =====================================================
        # STAGE 2 — barcode-region detection
        # =====================================================

        region_candidates = (
            _detect_barcode_like_regions(
                image_bgr
            )
        )

        # =====================================================
        # STAGE 3 — OCR fallback
        # =====================================================

        ocr_fallback = _ocr_barcode_fallback(
            image_bgr,
            region_candidates,
        )

        if ocr_fallback is not None:
            return ocr_fallback

        # -----------------------------------------------------
        # Nothing detected.
        # -----------------------------------------------------

        return BarcodeResult(
            found=False
        )

    except Exception as exc:  # noqa: BLE001

        logger.error(
            "Barcode decoding failed: %s",
            exc,
        )

        return BarcodeResult(
            found=False,
            error_message=repr(exc),
        )


# =============================================================
# Convert pyzbar result
# =============================================================

def _barcode_result_from_decoded(
    barcode: Any,
) -> BarcodeResult | None:
    """
    Convert a pyzbar decoded object into BarcodeResult.
    """

    value = _decode_barcode_value(
        barcode
    )

    if not value:
        return None

    barcode_format = str(
        getattr(
            barcode,
            "type",
            "",
        )
        or ""
    ).upper()

    bbox = _extract_bbox(
        barcode
    )

    return BarcodeResult(
        found=True,
        value=value,
        format=barcode_format or None,
        confidence=1.0,
        bbox=bbox,
    )


# =============================================================
# Image preparation
# =============================================================

def _resize_keep_aspect(
    image: np.ndarray,
    max_side: int,
) -> np.ndarray:
    """
    Resize only when necessary while preserving aspect ratio.
    """

    height, width = image.shape[:2]

    current_max = max(
        height,
        width,
    )

    if current_max <= max_side:
        return image

    scale = (
        max_side
        / float(current_max)
    )

    return cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_AREA,
    )


def _upscale_small_image(
    image: np.ndarray,
) -> np.ndarray:
    """
    Modestly upscale small images for barcode decoding.
    """

    height, width = image.shape[:2]

    current_max = max(
        height,
        width,
    )

    if current_max >= MIN_UPSCALE_SIDE:
        return image

    scale = (
        MIN_UPSCALE_SIDE
        / float(current_max)
    )

    scale = min(
        scale,
        2.0,
    )

    return cv2.resize(
        image,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )


# =============================================================
# Candidate regions for pyzbar
# =============================================================

def _candidate_regions(
    image_bgr: np.ndarray,
) -> list[
    tuple[
        str,
        np.ndarray,
    ]
]:
    """
    Create practical package-image regions.

    Full image is always included.
    Lower package regions are included because retail barcodes
    are frequently located there.
    """

    height, width = image_bgr.shape[:2]

    regions: list[
        tuple[
            str,
            np.ndarray,
        ]
    ] = [
        (
            "full",
            image_bgr,
        )
    ]

    if (
        height < 20
        or width < 20
    ):
        return regions

    lower_60_y = int(
        height * 0.40
    )

    lower_40_y = int(
        height * 0.60
    )

    lower_left_y = int(
        height * 0.45
    )

    lower_left_x = int(
        width * 0.05
    )

    lower_right_x = int(
        width * 0.65
    )

    regions.extend(
        [
            (
                "lower_60",
                image_bgr[
                    lower_60_y:height,
                    :
                ],
            ),
            (
                "lower_40",
                image_bgr[
                    lower_40_y:height,
                    :
                ],
            ),
            (
                "lower_left",
                image_bgr[
                    lower_left_y:height,
                    lower_left_x:lower_right_x,
                ],
            ),
        ]
    )

    return regions


# =============================================================
# Pyzbar preprocessing variants
# =============================================================

def _build_barcode_variants(
    image_bgr: np.ndarray,
) -> list[
    tuple[
        str,
        np.ndarray,
    ]
]:
    """
    Build a small number of pyzbar-friendly variants.
    """

    base = _resize_keep_aspect(
        image_bgr,
        MAX_WORKING_SIDE,
    )

    base = _upscale_small_image(
        base
    )

    regions = _candidate_regions(
        base
    )

    variants: list[
        tuple[
            str,
            np.ndarray,
        ]
    ] = []

    for (
        region_name,
        region,
    ) in regions:

        if (
            region is None
            or region.size == 0
        ):
            continue

        # Original.
        variants.append(
            (
                f"{region_name}_original",
                region,
            )
        )

        # Grayscale.
        gray = cv2.cvtColor(
            region,
            cv2.COLOR_BGR2GRAY,
        )

        variants.append(
            (
                f"{region_name}_gray",
                gray,
            )
        )

        # Otsu.
        _, otsu = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY
            + cv2.THRESH_OTSU,
        )

        variants.append(
            (
                f"{region_name}_otsu",
                otsu,
            )
        )

    return variants


# =============================================================
# Barcode-like region detection
# =============================================================

def _detect_barcode_like_regions(
    image_bgr: np.ndarray,
) -> list[
    tuple[
        np.ndarray,
        list[int],
        float,
    ]
]:
    """
    Detect rectangles containing strong vertical line patterns.

    Retail barcodes have many vertical bars, which produces a
    strong horizontal/vertical-gradient signature.

    Returns:
        (cropped_region, bbox, score)
    """

    working = _resize_keep_aspect(
        image_bgr,
        MAX_WORKING_SIDE,
    )

    gray = cv2.cvtColor(
        working,
        cv2.COLOR_BGR2GRAY,
    )

    # ---------------------------------------------------------
    # Blackhat highlights dark barcode bars on light labels.
    # ---------------------------------------------------------

    blackhat_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (
            21,
            7,
        ),
    )

    blackhat = cv2.morphologyEx(
        gray,
        cv2.MORPH_BLACKHAT,
        blackhat_kernel,
    )

    # ---------------------------------------------------------
    # X-gradient emphasizes vertical barcode edges.
    # ---------------------------------------------------------

    gradient_x = cv2.Sobel(
        blackhat,
        cv2.CV_32F,
        1,
        0,
        ksize=-1,
    )

    gradient_x = np.absolute(
        gradient_x
    )

    if float(
        gradient_x.max()
    ) > 0:

        gradient_x = cv2.normalize(
            gradient_x,
            None,
            0,
            255,
            cv2.NORM_MINMAX,
        )

    gradient_x = gradient_x.astype(
        np.uint8
    )

    gradient_x = cv2.GaussianBlur(
        gradient_x,
        (
            9,
            9,
        ),
        0,
    )

    _, threshold = cv2.threshold(
        gradient_x,
        0,
        255,
        cv2.THRESH_BINARY
        + cv2.THRESH_OTSU,
    )

    # ---------------------------------------------------------
    # Join neighboring barcode bars.
    # ---------------------------------------------------------

    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (
            21,
            7,
        ),
    )

    threshold = cv2.morphologyEx(
        threshold,
        cv2.MORPH_CLOSE,
        close_kernel,
    )

    threshold = cv2.erode(
        threshold,
        None,
        iterations=1,
    )

    threshold = cv2.dilate(
        threshold,
        None,
        iterations=1,
    )

    contours, _ = cv2.findContours(
        threshold,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    height, width = working.shape[:2]

    candidates: list[
        tuple[
            float,
            int,
            int,
            int,
            int,
        ]
    ] = []

    for contour in contours:

        x, y, w, h = cv2.boundingRect(
            contour
        )

        if (
            w < MIN_BARCODE_REGION_WIDTH
            or h < MIN_BARCODE_REGION_HEIGHT
        ):
            continue

        area = w * h

        if area < 1500:
            continue

        aspect_ratio = (
            w / float(
                max(
                    h,
                    1,
                )
            )
        )

        if (
            aspect_ratio
            < MIN_BARCODE_ASPECT_RATIO
        ):
            continue

        # Avoid huge image-wide rectangles.
        if (
            w > width * 0.90
            and h > height * 0.50
        ):
            continue

        roi_gray = gray[
            y:y + h,
            x:x + w,
        ]

        if roi_gray.size == 0:
            continue

        # Strong vertical edges compared with horizontal edges
        # are a useful barcode signature.
        sobel_x = np.absolute(
            cv2.Sobel(
                roi_gray,
                cv2.CV_32F,
                1,
                0,
                ksize=3,
            )
        )

        sobel_y = np.absolute(
            cv2.Sobel(
                roi_gray,
                cv2.CV_32F,
                0,
                1,
                ksize=3,
            )
        )

        vertical_mean = float(
            sobel_x.mean()
        )

        horizontal_mean = float(
            sobel_y.mean()
        )

        gradient_ratio = (
            vertical_mean
            / (
                horizontal_mean
                + 1.0
            )
        )

        if (
            gradient_ratio
            < MIN_VERTICAL_GRADIENT_RATIO
        ):
            continue

        # Favor lower-half barcode locations.
        lower_bonus = (
            2.0
            if y > height * 0.45
            else 0.0
        )

        area_score = min(
            area / 20000.0,
            2.0,
        )

        aspect_score = min(
            aspect_ratio / 4.0,
            2.0,
        )

        score = (
            gradient_ratio
            + lower_bonus
            + area_score
            + aspect_score
        )

        candidates.append(
            (
                score,
                x,
                y,
                w,
                h,
            )
        )

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    output: list[
        tuple[
            np.ndarray,
            list[int],
            float,
        ]
    ] = []

    # Keep only top few candidates.
    for (
        score,
        x,
        y,
        w,
        h,
    ) in candidates[:4]:

        # Add a small margin around the detected region.
        margin_x = max(
            int(w * 0.05),
            5,
        )

        margin_y = max(
            int(h * 0.08),
            5,
        )

        x1 = max(
            x - margin_x,
            0,
        )

        y1 = max(
            y - margin_y,
            0,
        )

        x2 = min(
            x + w + margin_x,
            width,
        )

        y2 = min(
            y + h + margin_y,
            height,
        )

        crop = working[
            y1:y2,
            x1:x2,
        ]

        if (
            crop is None
            or crop.size == 0
        ):
            continue

        bbox = [
            int(x1),
            int(y1),
            int(x2 - x1),
            int(y2 - y1),
        ]

        output.append(
            (
                crop,
                bbox,
                float(score),
            )
        )

    return output


# =============================================================
# Barcode value helpers
# =============================================================

def _decode_barcode_value(
    barcode: Any,
) -> str | None:
    """
    Safely decode pyzbar payload.
    """

    raw_data = getattr(
        barcode,
        "data",
        None,
    )

    if raw_data is None:
        return None

    if isinstance(
        raw_data,
        bytes,
    ):

        value = raw_data.decode(
            "utf-8",
            errors="ignore",
        )

    else:

        value = str(
            raw_data
        )

    value = value.strip()

    if not value:
        return None

    return value


def _extract_bbox(
    barcode: Any,
) -> list[int] | None:
    """
    Safely extract pyzbar rectangle.
    """

    rect = getattr(
        barcode,
        "rect",
        None,
    )

    if rect is None:
        return None

    try:

        x = int(
            rect.left
            if hasattr(
                rect,
                "left",
            )
            else rect[0]
        )

        y = int(
            rect.top
            if hasattr(
                rect,
                "top",
            )
            else rect[1]
        )

        w = int(
            rect.width
            if hasattr(
                rect,
                "width",
            )
            else rect[2]
        )

        h = int(
            rect.height
            if hasattr(
                rect,
                "height",
            )
            else rect[3]
        )

        return [
            x,
            y,
            w,
            h,
        ]

    except Exception:  # noqa: BLE001

        return None


# =============================================================
# Barcode validation
# =============================================================

def _is_valid_barcode_result(
    barcode: Any,
) -> bool:
    """
    Reject malformed pyzbar results.
    """

    value = _decode_barcode_value(
        barcode
    )

    if not value:
        return False

    barcode_type = str(
        getattr(
            barcode,
            "type",
            "",
        )
        or ""
    ).upper()

    if (
        barcode_type
        and barcode_type
        not in SUPPORTED_FORMATS
    ):
        return False

    numeric_formats = {
        "EAN13",
        "EAN8",
        "UPCA",
        "UPCE",
        "ITF",
        "I25",
    }

    if barcode_type in numeric_formats:

        if not value.isdigit():
            return False

    if len(value) > 80:
        return False

    return True


def _barcode_area(
    barcode: Any,
) -> int:
    """
    Approximate barcode area.
    """

    rect = getattr(
        barcode,
        "rect",
        None,
    )

    if rect is None:
        return 0

    try:

        width = int(
            rect.width
            if hasattr(
                rect,
                "width",
            )
            else rect[2]
        )

        height = int(
            rect.height
            if hasattr(
                rect,
                "height",
            )
            else rect[3]
        )

        return max(
            width * height,
            0,
        )

    except Exception:  # noqa: BLE001

        return 0


def _select_best_barcode(
    results: list[Any],
) -> Any | None:
    """
    Select strongest valid pyzbar result.
    """

    valid_results: list[Any] = []

    for result in results:

        if _is_valid_barcode_result(
            result
        ):
            valid_results.append(
                result
            )

    if not valid_results:
        return None

    unique: dict[
        tuple[
            str,
            str,
        ],
        Any,
    ] = {}

    for result in valid_results:

        value = _decode_barcode_value(
            result
        )

        barcode_type = str(
            getattr(
                result,
                "type",
                "",
            )
            or ""
        ).upper()

        if not value:
            continue

        key = (
            value,
            barcode_type,
        )

        current = unique.get(
            key
        )

        if (
            current is None
            or _barcode_area(result)
            > _barcode_area(current)
        ):

            unique[key] = result

    candidates = list(
        unique.values()
    )

    def score(
        result: Any,
    ) -> tuple[
        int,
        int,
        int,
        int,
    ]:

        value = (
            _decode_barcode_value(
                result
            )
            or ""
        )

        barcode_type = str(
            getattr(
                result,
                "type",
                "",
            )
            or ""
        ).upper()

        known_format = int(
            barcode_type
            in SUPPORTED_FORMATS
        )

        numeric_retail = int(
            barcode_type
            in {
                "EAN13",
                "EAN8",
                "UPCA",
                "UPCE",
                "ITF",
                "I25",
            }
            and value.isdigit()
        )

        reasonable_length = int(
            7 <= len(value) <= 20
        )

        return (
            known_format,
            numeric_retail,
            reasonable_length,
            _barcode_area(result),
        )

    candidates.sort(
        key=score,
        reverse=True,
    )

    return candidates[0]


# =============================================================
# OCR fallback — text extraction
# =============================================================

def _ocr_numeric_strings(
    image: np.ndarray,
) -> list[str]:
    """
    Run OCR on a barcode digit region.

    Multiple small PSM variants are used because the human-readable
    barcode digits can be recognized as one line, multiple chunks,
    or a single digit.
    """

    results: list[str] = []

    if (
        image is None
        or image.size == 0
    ):
        return results

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY,
    )

    # Green channel often preserves useful contrast on package labels.
    if len(image.shape) == 3:

        green = image[:, :, 1]

        channels = [
            (
                "gray",
                gray,
            ),
            (
                "green",
                green,
            ),
        ]

    else:

        channels = [
            (
                "gray",
                gray,
            )
        ]

    height = gray.shape[0]

    # Human-readable digits are normally near the bottom of the
    # barcode rectangle.
    crops: list[
        tuple[
            str,
            np.ndarray,
        ]
    ] = []

    for fraction in (
        0.70,
        0.75,
    ):

        start_y = int(
            height * fraction
        )

        digit_crop = gray[
            start_y:height,
            :
        ]

        if (
            digit_crop is not None
            and digit_crop.size > 0
        ):

            crops.append(
                (
                    f"gray_bottom_{fraction}",
                    digit_crop,
                )
            )

        if len(image.shape) == 3:

            green = image[:, :, 1]

            green_crop = green[
                start_y:height,
                :
            ]

            if (
                green_crop is not None
                and green_crop.size > 0
            ):

                crops.append(
                    (
                        f"green_bottom_{fraction}",
                        green_crop,
                    )
                )

    # ---------------------------------------------------------
    # OCR each small crop.
    #
    # This is much cheaper than OCRing the entire product image.
    # ---------------------------------------------------------

    for crop_name, crop in crops:

        upscale = cv2.resize(
            crop,
            None,
            fx=8,
            fy=8,
            interpolation=cv2.INTER_CUBIC,
        )

        upscale = cv2.copyMakeBorder(
            upscale,
            30,
            30,
            30,
            30,
            cv2.BORDER_CONSTANT,
            value=255,
        )

        for psm in (
            6,
            13,
        ):

            config = (
                "--oem 3 "
                f"--psm {psm} "
                "-c tessedit_char_whitelist=0123456789"
            )

            try:

                text = pytesseract.image_to_string(
                    upscale,
                    lang="eng",
                    config=config,
                )

            except Exception as exc:  # noqa: BLE001

                logger.warning(
                    "Barcode OCR failed: crop=%s psm=%s error=%s",
                    crop_name,
                    psm,
                    exc,
                )

                continue

            if not text:
                continue

            for line in text.splitlines():

                digits = re.sub(
                    r"\D",
                    "",
                    line,
                )

                if digits:
                    results.append(
                        digits
                    )

                    logger.info(
                        "Barcode OCR candidate: "
                        "crop=%s psm=%s digits=%s",
                        crop_name,
                        psm,
                        digits,
                    )

    return results


# =============================================================
# OCR barcode candidate reconstruction
# =============================================================

def _generate_ean13_candidates(
    digit_strings: list[str],
) -> list[str]:
    """
    Generate EAN-13 candidates from OCR strings.

    Handles cases such as:

        OCR 1 -> 901233027548
        OCR 2 -> 8

    producing:

        8901233027548

    Also handles a 13-digit OCR string containing one extra
    leading/trailing digit by checking every 12-digit window.
    """

    candidates: set[str] = set()

    # ---------------------------------------------------------
    # Normalize and collect strings.
    # ---------------------------------------------------------

    normalized: list[str] = []

    for value in digit_strings:

        digits = re.sub(
            r"\D",
            "",
            value or "",
        )

        if not digits:
            continue

        if len(digits) > 20:
            continue

        normalized.append(
            digits
        )

    # ---------------------------------------------------------
    # Direct 13-digit candidates.
    # ---------------------------------------------------------

    for digits in normalized:

        if len(digits) == 13:

            if _validate_ean13_checksum(
                digits
            ):
                candidates.add(
                    digits
                )

        elif len(digits) > 13:

            for start in range(
                len(digits) - 12
            ):

                window = digits[
                    start:start + 13
                ]

                if _validate_ean13_checksum(
                    window
                ):
                    candidates.add(
                        window
                    )

    # ---------------------------------------------------------
    # Collect single-digit OCR candidates.
    #
    # This is important for the Oreo image:
    #
    #   body = 901233027548
    #   prefix = 8
    # ---------------------------------------------------------

    single_digits: set[str] = set()

    for digits in normalized:

        if len(digits) == 1:
            single_digits.add(
                digits
            )

    # ---------------------------------------------------------
    # Every 12-digit body + observed single digit.
    # ---------------------------------------------------------

    twelve_digit_bodies: set[str] = set()

    for digits in normalized:

        if len(digits) == 12:

            twelve_digit_bodies.add(
                digits
            )

        elif len(digits) > 12:

            for start in range(
                len(digits) - 11
            ):

                window = digits[
                    start:start + 12
                ]

                twelve_digit_bodies.add(
                    window
                )

    for body in twelve_digit_bodies:

        for digit in single_digits:

            prefix_candidate = (
                digit
                + body
            )

            if _validate_ean13_checksum(
                prefix_candidate
            ):
                candidates.add(
                    prefix_candidate
                )

            suffix_candidate = (
                body
                + digit
            )

            if _validate_ean13_checksum(
                suffix_candidate
            ):
                candidates.add(
                    suffix_candidate
                )

    return sorted(
        candidates
    )


# =============================================================
# OCR fallback main function
# =============================================================

def _ocr_barcode_fallback(
    image_bgr: np.ndarray,
    detected_regions: list[
        tuple[
            np.ndarray,
            list[int],
            float,
        ]
    ],
) -> BarcodeResult | None:
    """
    Attempt barcode recovery from the human-readable digits.

    Priority:

    1. detected barcode-like regions
    2. lower-left package fallback
    3. lower package fallback
    """

    try:

        working = _resize_keep_aspect(
            image_bgr,
            MAX_WORKING_SIDE,
        )

        height, width = working.shape[:2]

        region_inputs: list[
            tuple[
                str,
                np.ndarray,
                list[int],
            ]
        ] = []

        # -----------------------------------------------------
        # First use morphology-detected barcode regions.
        # -----------------------------------------------------

        for index, (
            region,
            bbox,
            score,
        ) in enumerate(
            detected_regions[:3]
        ):

            region_inputs.append(
                (
                    f"detected_{index}",
                    region,
                    bbox,
                )
            )

            logger.info(
                "Barcode-like region selected: "
                "index=%d score=%.3f bbox=%s",
                index,
                score,
                bbox,
            )

        # -----------------------------------------------------
        # Fallback lower-left region.
        #
        # Helpful when morphology cannot produce a strong contour.
        # -----------------------------------------------------

        lower_left_x1 = int(
            width * 0.10
        )

        lower_left_x2 = int(
            width * 0.50
        )

        lower_y = int(
            height * 0.55
        )

        lower_left = working[
            lower_y:height,
            lower_left_x1:lower_left_x2,
        ]

        if (
            lower_left is not None
            and lower_left.size > 0
        ):

            region_inputs.append(
                (
                    "lower_left_fallback",
                    lower_left,
                    [
                        lower_left_x1,
                        lower_y,
                        lower_left_x2
                        - lower_left_x1,
                        height
                        - lower_y,
                    ],
                )
            )

        # -----------------------------------------------------
        # OCR each selected region.
        # -----------------------------------------------------

        all_digit_strings: list[str] = []

        best_bbox: list[int] | None = None

        for (
            region_name,
            region,
            bbox,
        ) in region_inputs:

            strings = _ocr_numeric_strings(
                region
            )

            if strings:

                logger.info(
                    "Barcode OCR strings found: "
                    "region=%s values=%s",
                    region_name,
                    strings,
                )

                all_digit_strings.extend(
                    strings
                )

                if best_bbox is None:
                    best_bbox = bbox

                # -------------------------------------------------
                # Check candidates immediately.
                # -------------------------------------------------

                ean_candidates = (
                    _generate_ean13_candidates(
                        all_digit_strings
                    )
                )

                if len(
                    ean_candidates
                ) == 1:

                    value = ean_candidates[0]

                    logger.info(
                        "Validated EAN-13 barcode via OCR fallback: %s",
                        value,
                    )

                    return BarcodeResult(
                        found=True,
                        value=value,
                        format="EAN13",
                        confidence=0.70,
                        bbox=best_bbox,
                    )

        # -----------------------------------------------------
        # Final global reconstruction attempt.
        # -----------------------------------------------------

        ean_candidates = (
            _generate_ean13_candidates(
                all_digit_strings
            )
        )

        if len(
            ean_candidates
        ) == 1:

            value = ean_candidates[0]

            return BarcodeResult(
                found=True,
                value=value,
                format="EAN13",
                confidence=0.70,
                bbox=best_bbox,
            )

        # -----------------------------------------------------
        # Multiple valid candidates:
        #
        # Do not guess.
        # -----------------------------------------------------

        if len(
            ean_candidates
        ) > 1:

            logger.warning(
                "Multiple checksum-valid EAN-13 candidates found: %s",
                ean_candidates,
            )

            return None

        return None

    except pytesseract.TesseractNotFoundError:

        logger.warning(
            "Tesseract unavailable for barcode OCR fallback."
        )

        return None

    except Exception as exc:  # noqa: BLE001

        logger.warning(
            "Barcode OCR fallback failed: %s",
            exc,
        )

        return None


# =============================================================
# EAN-13 checksum validation
# =============================================================

def _validate_ean13_checksum(
    value: str,
) -> bool:
    """
    Validate EAN-13 checksum.
    """

    if (
        len(value) != 13
        or not value.isdigit()
    ):
        return False

    digits = [
        int(char)
        for char in value
    ]

    checksum_sum = sum(
        digits[index]
        * (
            3
            if index % 2 == 1
            else 1
        )
        for index in range(12)
    )

    checksum = (
        10
        - (
            checksum_sum % 10
        )
    ) % 10

    return checksum == digits[12]