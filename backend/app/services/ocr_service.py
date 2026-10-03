"""
Reusable OCR service using Tesseract OCR.

The service never crashes the whole API because one image failed OCR.
It returns OCRResult with status="success", "failed", or "unavailable".
"""

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from app.core.logging import get_logger
from app.schemas.ocr import OCRResult, OCRTextBlock
from app.utils.versions import package_version

logger = get_logger(__name__)


def run_ocr(image_bgr: np.ndarray) -> OCRResult:
    result = _run_ocr(image_bgr)
    result.engine_version = package_version("pytesseract")
    return result


def _run_ocr(image_bgr: np.ndarray) -> OCRResult:
    if image_bgr is None or image_bgr.size == 0:
        return OCRResult(
            status="failed",
            error_message="Empty image supplied to OCR.",
        )

    try:
        # ---------------------------------------------------------
        # 1. Resize image for better OCR accuracy
        # ---------------------------------------------------------
        height, width = image_bgr.shape[:2]
        max_side = max(height, width)

        if max_side < 1800:
            scale = 1.6
            image_bgr = cv2.resize(
                image_bgr,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )

        # ---------------------------------------------------------
        # 2. Mild preprocessing
        # ---------------------------------------------------------
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

        # Improve local contrast without destroying small text.
        clahe = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8),
        )
        enhanced = clahe.apply(gray)

        # Convert back to RGB because pytesseract accepts RGB images.
        image_rgb = cv2.cvtColor(
            enhanced,
            cv2.COLOR_GRAY2RGB,
        )

        # ---------------------------------------------------------
        # 3. Tesseract configuration
        # ---------------------------------------------------------
        config = (
            "--oem 3 "
            "--psm 11 "
            "-c preserve_interword_spaces=1"
        )

        data = pytesseract.image_to_data(
            image_rgb,
            lang="eng",
            config=config,
            output_type=Output.DICT,
        )

    except pytesseract.TesseractNotFoundError as exc:
        logger.error("Tesseract executable not found: %s", exc)

        return OCRResult(
            status="unavailable",
            error_message="Tesseract OCR executable is not installed.",
        )

    except Exception as exc:  # noqa: BLE001
        logger.error("OCR inference failed: %s", exc)

        return OCRResult(
            status="failed",
            error_message=repr(exc),
        )

    # -------------------------------------------------------------
    # 4. Group Tesseract words into actual text lines
    # -------------------------------------------------------------
    line_groups: dict[tuple[int, int, int], list[dict]] = {}

    total_items = len(data.get("text", []))

    for i in range(total_items):
        text = str(data["text"][i]).strip()

        if not text:
            continue

        try:
            confidence = float(data["conf"][i])
        except (ValueError, TypeError, IndexError):
            continue

        if confidence < 0:
            continue

        block_num = int(data["block_num"][i])
        par_num = int(data["par_num"][i])
        line_num = int(data["line_num"][i])

        key = (
            block_num,
            par_num,
            line_num,
        )

        try:
            left = float(data["left"][i])
            top = float(data["top"][i])
            width = float(data["width"][i])
            height = float(data["height"][i])
        except (ValueError, TypeError, IndexError):
            left = top = width = height = 0.0

        line_groups.setdefault(key, []).append(
            {
                "text": text,
                "confidence": confidence / 100.0,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        )

    # -------------------------------------------------------------
    # 5. Build OCRTextBlock per line
    # -------------------------------------------------------------
    blocks: list[OCRTextBlock] = []
    all_lines: list[str] = []

    for words in line_groups.values():

        # Sort words from left to right.
        words.sort(key=lambda item: item["left"])

        line_text = " ".join(
            item["text"]
            for item in words
        ).strip()

        if not line_text:
            continue

        confidences = [
            item["confidence"]
            for item in words
        ]

        average_line_confidence = (
            sum(confidences) / len(confidences)
            if confidences
            else 0.0
        )

        min_x = min(item["left"] for item in words)
        min_y = min(item["top"] for item in words)

        max_x = max(
            item["left"] + item["width"]
            for item in words
        )

        max_y = max(
            item["top"] + item["height"]
            for item in words
        )

        bbox = [
            [min_x, min_y],
            [max_x, min_y],
            [max_x, max_y],
            [min_x, max_y],
        ]

        blocks.append(
            OCRTextBlock(
                text=line_text,
                confidence=average_line_confidence,
                bbox=bbox,
            )
        )

        all_lines.append(line_text)

    combined_text = "\n".join(all_lines)

    average_confidence = (
        float(
            sum(block.confidence for block in blocks)
            / len(blocks)
        )
        if blocks
        else 0.0
    )

    return OCRResult(
        status="success",
        raw_text=blocks,
        combined_text=combined_text,
        average_confidence=round(
            average_confidence,
            4,
        ),
    )
