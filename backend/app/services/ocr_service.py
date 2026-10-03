"""
Reusable OCR service using Tesseract OCR.

The service never crashes the whole API because one image failed OCR.
It returns OCRResult with status="success", "failed", or "unavailable".

This version uses lightweight multi-pass preprocessing to improve OCR
accuracy on packaged-product labels while keeping memory usage suitable
for Render.
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

# Keep OCR images within a reasonable range for Render memory limits.
MIN_TARGET_SIDE = 1800
MAX_TARGET_SIDE = 2600


def run_ocr(image_bgr: np.ndarray) -> OCRResult:
    result = _run_ocr(image_bgr)

    result.engine_version = package_version("pytesseract")

    return result


# =============================================================
# Main OCR pipeline
# =============================================================

def _run_ocr(image_bgr: np.ndarray) -> OCRResult:
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
        image_bgr = _resize_for_ocr(image_bgr)

        # -----------------------------------------------------
        # 2. Build lightweight preprocessing variants
        # -----------------------------------------------------
        variants = _build_preprocessing_variants(image_bgr)

        # -----------------------------------------------------
        # 3. Run multiple Tesseract passes
        # -----------------------------------------------------
        candidates: list[OCRResult] = []

        for variant_name, variant_image, config in variants:
            try:
                candidate = _run_tesseract_pass(
                    variant_image,
                    config=config,
                )

                if candidate.status == "success":
                    candidates.append(candidate)

                logger.info(
                    "OCR pass completed: variant=%s confidence=%.4f blocks=%d",
                    variant_name,
                    candidate.average_confidence,
                    len(candidate.raw_text),
                )

            except pytesseract.TesseractNotFoundError:
                raise

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "OCR pass failed for variant=%s: %s",
                    variant_name,
                    exc,
                )

        # -----------------------------------------------------
        # 4. Select the strongest result
        # -----------------------------------------------------
        if not candidates:
            return OCRResult(
                status="failed",
                error_message="All OCR passes failed.",
            )

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
            error_message="Tesseract OCR executable is not installed.",
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

def _resize_for_ocr(image_bgr: np.ndarray) -> np.ndarray:
    """
    Resize image to a practical OCR range.

    Small images are enlarged.
    Very large images are reduced to avoid excessive memory usage.
    """

    height, width = image_bgr.shape[:2]
    max_side = max(height, width)

    if max_side == 0:
        return image_bgr

    # Small image -> enlarge.
    if max_side < MIN_TARGET_SIDE:
        scale = MIN_TARGET_SIDE / float(max_side)

        resized = cv2.resize(
            image_bgr,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_CUBIC,
        )

        return resized

    # Very large image -> reduce.
    if max_side > MAX_TARGET_SIDE:
        scale = MAX_TARGET_SIDE / float(max_side)

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
) -> list[tuple[str, np.ndarray, str]]:
    """
    Build several lightweight OCR-friendly image variants.

    The variants are deliberately limited to avoid high CPU/RAM usage.
    """

    gray = cv2.cvtColor(
        image_bgr,
        cv2.COLOR_BGR2GRAY,
    )

    # ---------------------------------------------------------
    # Variant 1: CLAHE enhanced grayscale
    # ---------------------------------------------------------

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    )

    enhanced = clahe.apply(gray)

    # Mild sharpening.
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

    # ---------------------------------------------------------
    # Variant 2: Otsu threshold
    # ---------------------------------------------------------

    _, otsu = cv2.threshold(
        sharpened,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU,
    )

    # ---------------------------------------------------------
    # Variant 3: Adaptive threshold
    # ---------------------------------------------------------

    adaptive = cv2.adaptiveThreshold(
        sharpened,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )

    return [
        (
            "enhanced_psm11",
            enhanced,
            "--oem 3 --psm 11 -c preserve_interword_spaces=1",
        ),
        (
            "sharpened_psm6",
            sharpened,
            "--oem 3 --psm 6 -c preserve_interword_spaces=1",
        ),
        (
            "otsu_psm11",
            otsu,
            "--oem 3 --psm 11 -c preserve_interword_spaces=1",
        ),
        (
            "adaptive_psm11",
            adaptive,
            "--oem 3 --psm 11 -c preserve_interword_spaces=1",
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
    Run one Tesseract image_to_data pass and convert the result
    into the project's OCRResult schema.
    """

    # Tesseract works reliably with grayscale or RGB.
    if len(image.shape) == 2:
        image_for_tesseract = cv2.cvtColor(
            image,
            cv2.COLOR_GRAY2RGB,
        )
    else:
        image_for_tesseract = image

    data = pytesseract.image_to_data(
        image_for_tesseract,
        lang="eng",
        config=config,
        output_type=Output.DICT,
    )

    blocks = _build_ocr_blocks(data)

    combined_text = "\n".join(
        block.text
        for block in blocks
        if block.text.strip()
    )

    if blocks:
        average_confidence = float(
            sum(block.confidence for block in blocks)
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
        list[dict[str, float | str]],
    ] = {}

    total_items = len(
        data.get("text", [])
    )

    for i in range(total_items):
        try:
            text = str(
                data["text"][i]
            ).strip()
        except (KeyError, IndexError):
            continue

        if not text:
            continue

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

        confidence_normalized = confidence / 100.0

        # Keep meaningful low-confidence tokens such as:
        # "8/1", "300", "₹", "No", etc.
        # Remove only the worst OCR noise.
        if confidence_normalized < MIN_CONFIDENCE_TO_KEEP:
            if not any(
                char.isalnum()
                for char in text
            ):
                continue

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

    blocks_with_position: list[
        tuple[float, float, OCRTextBlock]
    ] = []

    for words in line_groups.values():
        if not words:
            continue

        # Left-to-right word ordering.
        words.sort(
            key=lambda item: float(
                item["left"]
            )
        )

        line_text = " ".join(
            str(item["text"])
            for item in words
        ).strip()

        if not line_text:
            continue

        confidences = [
            float(item["confidence"])
            for item in words
        ]

        average_line_confidence = (
            sum(confidences)
            / len(confidences)
            if confidences
            else 0.0
        )

        min_x = min(
            float(item["left"])
            for item in words
        )

        min_y = min(
            float(item["top"])
            for item in words
        )

        max_x = max(
            float(item["left"])
            + float(item["width"])
            for item in words
        )

        max_y = max(
            float(item["top"])
            + float(item["height"])
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
    # Ensure final OCR lines are top-to-bottom, left-to-right.
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

    Average confidence alone is not enough because a pass might
    return only a few high-confidence words. This score also
    rewards useful alphanumeric content.
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
                float(block.confidence),
            ),
        )

        alphanumeric_count = sum(
            1
            for char in text
            if char.isalnum()
        )

        useful_characters += alphanumeric_count

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
        + (useful_characters * 0.08)
        + (high_confidence_blocks * 1.5)
    )
