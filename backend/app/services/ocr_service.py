"""
Reusable OCR service using Tesseract OCR.

The service never crashes the whole API because one image failed OCR.
It returns OCRResult with status="success", "failed", or "unavailable".

This version is optimized for Render:
- one primary OCR pass for normal images
- one fallback OCR pass only when confidence is low
- lightweight preprocessing
- controlled image size to reduce CPU/RAM usage
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from app.core.logging import get_logger
from app.schemas.ocr import OCRResult, OCRTextBlock
from app.utils.versions import package_version

logger = get_logger(__name__)


# -------------------------------------------------------------
# Configuration
# -------------------------------------------------------------

MIN_CONFIDENCE_TO_KEEP = 0.15

# Conditional fallback threshold.
# If primary OCR is below this confidence, one fallback pass runs.
FALLBACK_CONFIDENCE_THRESHOLD = 0.45

# Keep OCR images within a practical range for Render.
MIN_TARGET_SIDE = 1800
MAX_TARGET_SIDE = 2600


def run_ocr(image_bgr: np.ndarray) -> OCRResult:
    """
    Public OCR entry point.
    """

    result = _run_ocr(image_bgr)

    result.engine_version = package_version("pytesseract")

    return result


# =============================================================
# Main OCR pipeline
# =============================================================

def _run_ocr(image_bgr: np.ndarray) -> OCRResult:
    """
    Run OCR using one primary pass and, only when necessary,
    one fallback pass.
    """

    if image_bgr is None or image_bgr.size == 0:
        return OCRResult(
            status="failed",
            error_message="Empty image supplied to OCR.",
        )

    if not isinstance(image_bgr, np.ndarray):
        return OCRResult(
            status="failed",
            error_message="Invalid image type supplied to OCR.",
        )

    try:
        # -----------------------------------------------------
        # 1. Resize image safely
        # -----------------------------------------------------

        image_bgr = _resize_for_ocr(
            image_bgr
        )

        # -----------------------------------------------------
        # 2. Build only two lightweight variants
        #
        # Primary:
        #   enhanced + PSM 11
        #
        # Fallback:
        #   sharpened + PSM 6
        # -----------------------------------------------------

        variants = _build_preprocessing_variants(
            image_bgr
        )

        if not variants:
            return OCRResult(
                status="failed",
                error_message="No OCR preprocessing variants available.",
            )

        candidates: list[OCRResult] = []

        # -----------------------------------------------------
        # 3. PRIMARY OCR PASS
        # -----------------------------------------------------

        primary_name, primary_image, primary_config = (
            variants[0]
        )

        try:
            primary_result = _run_tesseract_pass(
                primary_image,
                config=primary_config,
            )

            if primary_result.status == "success":
                candidates.append(
                    primary_result
                )

            logger.info(
                "OCR pass completed: "
                "variant=%s confidence=%.4f blocks=%d",
                primary_name,
                primary_result.average_confidence,
                len(primary_result.raw_text),
            )

        except pytesseract.TesseractNotFoundError:
            raise

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Primary OCR pass failed: %s",
                exc,
            )

        # -----------------------------------------------------
        # 4. CONDITIONAL FALLBACK OCR PASS
        #
        # Run only when:
        #   - primary pass succeeded
        #   - confidence is below threshold
        # -----------------------------------------------------

        if (
            candidates
            and candidates[0].average_confidence
            < FALLBACK_CONFIDENCE_THRESHOLD
            and len(variants) > 1
        ):

            fallback_name, fallback_image, fallback_config = (
                variants[1]
            )

            try:
                fallback_result = _run_tesseract_pass(
                    fallback_image,
                    config=fallback_config,
                )

                if fallback_result.status == "success":
                    candidates.append(
                        fallback_result
                    )

                logger.info(
                    "OCR fallback completed: "
                    "variant=%s confidence=%.4f blocks=%d",
                    fallback_name,
                    fallback_result.average_confidence,
                    len(fallback_result.raw_text),
                )

            except pytesseract.TesseractNotFoundError:
                raise

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "OCR fallback failed: %s",
                    exc,
                )

        # -----------------------------------------------------
        # 5. No successful OCR pass
        # -----------------------------------------------------

        if not candidates:

            return OCRResult(
                status="failed",
                error_message="All OCR passes failed.",
            )

        # -----------------------------------------------------
        # 6. Select strongest result
        # -----------------------------------------------------

        best_result = max(
            candidates,
            key=_ocr_quality_score,
        )

        return best_result

    except pytesseract.TesseractNotFoundError as exc:

        logger.error(
            "Tesseract executable not found: %s",
            exc,
        )

        return OCRResult(
            status="unavailable",
            error_message=(
                "Tesseract OCR executable is not installed."
            ),
        )

    except Exception as exc:  # noqa: BLE001

        logger.error(
            "OCR inference failed: %s",
            exc,
        )

        return OCRResult(
            status="failed",
            error_message=repr(exc),
        )


# =============================================================
# Image preparation
# =============================================================

def _resize_for_ocr(
    image_bgr: np.ndarray,
) -> np.ndarray:
    """
    Resize image to a practical OCR range.

    Small images are enlarged.

    Very large images are reduced to avoid excessive
    CPU and memory consumption.
    """

    height, width = image_bgr.shape[:2]
    max_side = max(
        height,
        width,
    )

    if max_side == 0:
        return image_bgr

    # ---------------------------------------------------------
    # Small image -> enlarge
    # ---------------------------------------------------------

    if max_side < MIN_TARGET_SIDE:

        scale = (
            MIN_TARGET_SIDE
            / float(max_side)
        )

        resized = cv2.resize(
            image_bgr,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )

        return resized

    # ---------------------------------------------------------
    # Very large image -> reduce
    # ---------------------------------------------------------

    if max_side > MAX_TARGET_SIDE:

        scale = (
            MAX_TARGET_SIDE
            / float(max_side)
        )

        resized = cv2.resize(
            image_bgr,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )

        return resized

    return image_bgr


def _build_preprocessing_variants(
    image_bgr: np.ndarray,
) -> list[
    tuple[
        str,
        np.ndarray,
        str,
    ]
]:
    """
    Build two lightweight OCR-friendly variants.

    Primary:
        CLAHE-enhanced grayscale + PSM 11

    Fallback:
        sharpened grayscale + PSM 6

    Only these two variants are created/used so that Render
    does not spend several minutes running four Tesseract passes.
    """

    gray = cv2.cvtColor(
        image_bgr,
        cv2.COLOR_BGR2GRAY,
    )

    # ---------------------------------------------------------
    # CLAHE local contrast enhancement
    # ---------------------------------------------------------

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    )

    enhanced = clahe.apply(
        gray
    )

    # ---------------------------------------------------------
    # Mild sharpening
    # ---------------------------------------------------------

    sharpen_kernel = np.array(
        [
            [0, -1, 0],
            [-1, 5, -1],
            [0, -1, 0],
        ],
        dtype=np.float32,
    )

    sharpened = cv2.filter2D(
        enhanced,
        -1,
        sharpen_kernel,
    )

    return [
        (
            "enhanced_psm11",
            enhanced,
            (
                "--oem 3 "
                "--psm 11 "
                "-c preserve_interword_spaces=1"
            ),
        ),
        (
            "sharpened_psm6",
            sharpened,
            (
                "--oem 3 "
                "--psm 6 "
                "-c preserve_interword_spaces=1"
            ),
        ),
    ]


# =============================================================
# Tesseract pass
# =============================================================

def _run_tesseract_pass(
    image: np.ndarray,
    *,
    config: str,
) -> OCRResult:
    """
    Run one Tesseract image_to_data pass and convert
    the result into OCRResult.
    """

    # ---------------------------------------------------------
    # Tesseract works reliably with grayscale or RGB images.
    # ---------------------------------------------------------

    if len(image.shape) == 2:

        image_for_tesseract = cv2.cvtColor(
            image,
            cv2.COLOR_GRAY2RGB,
        )

    else:

        image_for_tesseract = image

    # ---------------------------------------------------------
    # Run Tesseract
    # ---------------------------------------------------------

    data = pytesseract.image_to_data(
        image_for_tesseract,
        lang="eng",
        config=config,
        output_type=Output.DICT,
    )

    # ---------------------------------------------------------
    # Convert Tesseract words to project OCR blocks
    # ---------------------------------------------------------

    blocks = _build_ocr_blocks(
        data
    )

    # ---------------------------------------------------------
    # Combined text
    # ---------------------------------------------------------

    combined_text = "\n".join(
        block.text
        for block in blocks
        if block.text.strip()
    )

    # ---------------------------------------------------------
    # Average confidence
    # ---------------------------------------------------------

    if blocks:

        average_confidence = float(
            sum(
                block.confidence
                for block in blocks
            )
            / len(blocks)
        )

    else:

        average_confidence = 0.0

    return OCRResult(
        status="success",
        raw_text=blocks,
        combined_text=combined_text,
        average_confidence=round(
            average_confidence,
            4,
        ),
    )


# =============================================================
# Tesseract output -> OCR blocks
# =============================================================

def _build_ocr_blocks(
    data: dict[str, Any],
) -> list[OCRTextBlock]:
    """
    Group Tesseract words into readable lines.

    Very low-confidence noise is filtered, but useful short
    tokens such as dates and numeric values are preserved.
    """

    line_groups: dict[
        tuple[int, int, int],
        list[
            dict[
                str,
                float | str,
            ]
        ],
    ] = {}

    total_items = len(
        data.get(
            "text",
            [],
        )
    )

    for i in range(
        total_items
    ):

        # -----------------------------------------------------
        # Text
        # -----------------------------------------------------

        try:

            text = str(
                data["text"][i]
            ).strip()

        except (
            KeyError,
            IndexError,
        ):

            continue

        if not text:
            continue

        # -----------------------------------------------------
        # Confidence
        # -----------------------------------------------------

        try:

            confidence = float(
                data["conf"][i]
            )

        except (
            ValueError,
            TypeError,
            IndexError,
            KeyError,
        ):

            continue

        if confidence < 0:
            continue

        confidence_normalized = (
            confidence / 100.0
        )

        # -----------------------------------------------------
        # Filter only the worst OCR noise.
        #
        # Numeric/date-like tokens are preserved because
        # compliance fields depend heavily on them.
        # -----------------------------------------------------

        if (
            confidence_normalized
            < MIN_CONFIDENCE_TO_KEEP
        ):

            if not any(
                char.isalnum()
                for char in text
            ):
                continue

        # -----------------------------------------------------
        # Tesseract hierarchy
        # -----------------------------------------------------

        try:

            block_num = int(
                data["block_num"][i]
            )

            par_num = int(
                data["par_num"][i]
            )

            line_num = int(
                data["line_num"][i]
            )

        except (
            ValueError,
            TypeError,
            IndexError,
            KeyError,
        ):

            continue

        key = (
            block_num,
            par_num,
            line_num,
        )

        # -----------------------------------------------------
        # Bounding box
        # -----------------------------------------------------

        try:

            left = float(
                data["left"][i]
            )

            top = float(
                data["top"][i]
            )

            width = float(
                data["width"][i]
            )

            height = float(
                data["height"][i]
            )

        except (
            ValueError,
            TypeError,
            IndexError,
            KeyError,
        ):

            left = 0.0
            top = 0.0
            width = 0.0
            height = 0.0

        # -----------------------------------------------------
        # Add word to line group
        # -----------------------------------------------------

        line_groups.setdefault(
            key,
            [],
        ).append(
            {
                "text": text,
                "confidence": confidence_normalized,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        )

    # =========================================================
    # Build line blocks
    # =========================================================

    blocks_with_position: list[
        tuple[
            float,
            float,
            OCRTextBlock,
        ]
    ] = []

    for words in line_groups.values():

        if not words:
            continue

        # -----------------------------------------------------
        # Left -> right ordering
        # -----------------------------------------------------

        words.sort(
            key=lambda item: float(
                item["left"]
            )
        )

        # -----------------------------------------------------
        # Build readable line text
        # -----------------------------------------------------

        line_text = " ".join(
            str(
                item["text"]
            )
            for item in words
        ).strip()

        if not line_text:
            continue

        # -----------------------------------------------------
        # Average line confidence
        # -----------------------------------------------------

        confidences = [
            float(
                item["confidence"]
            )
            for item in words
        ]

        average_line_confidence = (
            sum(confidences)
            / len(confidences)
            if confidences
            else 0.0
        )

        # -----------------------------------------------------
        # Bounding rectangle
        # -----------------------------------------------------

        min_x = min(
            float(
                item["left"]
            )
            for item in words
        )

        min_y = min(
            float(
                item["top"]
            )
            for item in words
        )

        max_x = max(
            float(
                item["left"]
            )
            + float(
                item["width"]
            )
            for item in words
        )

        max_y = max(
            float(
                item["top"]
            )
            + float(
                item["height"]
            )
            for item in words
        )

        bbox = [
            [min_x, min_y],
            [max_x, min_y],
            [max_x, max_y],
            [min_x, max_y],
        ]

        block = OCRTextBlock(
            text=line_text,
            confidence=round(
                average_line_confidence,
                4,
            ),
            bbox=bbox,
        )

        blocks_with_position.append(
            (
                min_y,
                min_x,
                block,
            )
        )

    # ---------------------------------------------------------
    # Top -> bottom, left -> right
    # ---------------------------------------------------------

    blocks_with_position.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    return [
        item[2]
        for item in blocks_with_position
    ]


# =============================================================
# OCR candidate scoring
# =============================================================

def _ocr_quality_score(
    result: OCRResult,
) -> float:
    """
    Rank OCR passes.

    Confidence alone is not enough because an OCR pass might
    return only a few high-confidence words.

    This score also rewards useful alphanumeric content.
    """

    if result.status != "success":
        return -1.0

    blocks = result.raw_text or []

    if not blocks:
        return 0.0

    useful_characters = 0
    high_confidence_blocks = 0
    total_weight = 0.0

    for block in blocks:

        text = block.text.strip()

        if not text:
            continue

        confidence = max(
            0.0,
            min(
                1.0,
                float(
                    block.confidence
                ),
            ),
        )

        alphanumeric_count = sum(
            1
            for char in text
            if char.isalnum()
        )

        useful_characters += (
            alphanumeric_count
        )

        if confidence >= 0.60:
            high_confidence_blocks += 1

        total_weight += (
            confidence
            * min(
                len(text),
                80,
            )
        )

    return (
        total_weight
        + (
            useful_characters
            * 0.08
        )
        + (
            high_confidence_blocks
            * 1.5
        )
    )
