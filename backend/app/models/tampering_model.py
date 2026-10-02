"""
IMPORTANT - read before changing this file.

The spec asks for a ManTraNet-based tampering component. ManTraNet's own
reference implementation pins legacy Keras 2.2.0 + TensorFlow 1.8.0 and
is documented as untested on other versions. Forcing those into the same
process as modern PaddleOCR (which needs a current numpy/opencv stack)
creates real, hard dependency conflicts - exactly what the spec (5.3,
30.14) says to avoid.

This module therefore implements the tampering check as an isolated,
swappable adapter with THREE modes, selected by settings.tampering_service_mode:

  - "heuristic"        (default): a classical CV heuristic (edge/contour
                         analysis for sticker-like overlay regions, plus
                         a simple noise-consistency check) that runs in
                         THIS process with zero extra heavy dependencies.
                         This is a real, working signal - not a stub -
                         but it is NOT ManTraNet, and it is reported to
                         the frontend as engine="heuristic" so nobody
                         mistakes it for the ManTraNet model.
  - "mantranet_remote" : calls out to a separate microservice/container
                         running the legacy ManTraNet stack, at
                         settings.tampering_remote_url. That container
                         is NOT included here (it needs its own legacy
                         Python env) - this mode is wired and ready, but
                         requires the team to stand up that service.
  - "disabled"          : tampering_service reports status="unavailable"
                         cleanly rather than guessing.

This is the "clear adapter interface and documented fallback" the spec
explicitly allows in section 31, item 25, for a dependency that
genuinely cannot be run in the same runtime.
"""

import cv2
import numpy as np

from app.core.logging import get_logger

logger = get_logger(__name__)


def heuristic_tampering_score(image_bgr: np.ndarray) -> tuple[float, bool, list[tuple[int, int, int, int]]]:
    """
    Classical-CV heuristic, deliberately conservative. Two signals:

    1. Sticker-like overlays: large, near-perfect rectangles (4-vertex
       polygons, high rectangularity, 0.4%-12% of the image area).
       Individual text glyphs are far smaller and never qualify.
    2. Noise inconsistency: camera/print noise is roughly uniform across
       a genuine photo, while a pasted or re-printed patch often carries
       a different noise level. We estimate noise per tile from the
       high-frequency residual, but ONLY over textured, non-text tiles
       (flat backgrounds and dense text edges are excluded - they made
       an earlier version flag every clean image).

    Returns (score 0-1, anomaly_detected, suspicious_boxes). Thresholds
    are UNCALIBRATED against real label photos - treat the output as
    weak evidence and tune on your own dataset before trusting it.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    image_area = h * w

    # --- Signal 1: sticker-like rectangles ---
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    suspicious_boxes: list[tuple[int, int, int, int]] = []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        box_area = bw * bh
        if not (0.004 * image_area <= box_area <= 0.12 * image_area):
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        rectangularity = cv2.contourArea(c) / max(box_area, 1)
        if len(approx) == 4 and rectangularity > 0.85:
            suspicious_boxes.append((x, y, bw, bh))

    rect_signal = min(len(suspicious_boxes) / 3.0, 1.0)

    # --- Signal 2: noise inconsistency over textured, non-text tiles ---
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    residual = gray.astype(np.float32) - blurred.astype(np.float32)
    edge_map = cv2.Canny(gray, 50, 150)

    tile = 32
    noise_levels = []
    for y in range(0, h - tile, tile):
        for x in range(0, w - tile, tile):
            if edge_map[y : y + tile, x : x + tile].mean() / 255.0 > 0.08:
                continue  # text / hard edges - not informative about noise
            level = float(np.median(np.abs(residual[y : y + tile, x : x + tile])))
            if level < 0.3:
                continue  # perfectly flat region - no noise to compare
            noise_levels.append(level)

    noise_signal = 0.0
    if len(noise_levels) >= 12:
        arr = np.array(noise_levels)
        cv = float(arr.std() / (arr.mean() + 1e-6))
        noise_signal = min(max((cv - 0.6) / 1.4, 0.0), 1.0)  # CV below 0.6 counts as normal

    score = round(0.5 * rect_signal + 0.5 * noise_signal, 3)
    anomaly_detected = score > 0.55
    return score, anomaly_detected, suspicious_boxes[:20]
