import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.tampering_model import heuristic_tampering_score
from app.schemas.tampering import TamperingResult
from app.utils.versions import TAMPERING_HEURISTIC_VERSION

logger = get_logger(__name__)


def run_tampering_check(image_bgr: np.ndarray) -> TamperingResult:
    settings = get_settings()
    mode = settings.tampering_service_mode

    if mode == "disabled":
        return TamperingResult(status="unavailable", engine="disabled", message="Tampering check disabled.")

    if mode == "mantranet_remote":
        return _run_remote_mantranet(image_bgr, settings.tampering_remote_url)

    # Default: in-process heuristic adapter.
    try:
        score, anomaly, _boxes = heuristic_tampering_score(image_bgr)
    except Exception as exc:  # noqa: BLE001
        logger.error("Tampering heuristic failed: %s", exc)
        return TamperingResult(status="failed", engine="heuristic", message=repr(exc))

    message = "Possible manipulation detected - review required." if anomaly else "No significant anomaly detected."
    return TamperingResult(
        status="success",
        tampering_score=score,
        anomaly_detected=anomaly,
        engine="heuristic",
        engine_version=TAMPERING_HEURISTIC_VERSION,
        message=message,
    )


def _run_remote_mantranet(image_bgr: np.ndarray, remote_url: str) -> TamperingResult:
    if not remote_url:
        return TamperingResult(
            status="unavailable",
            engine="mantranet_remote",
            message="tampering_remote_url not configured.",
        )
    try:
        import cv2
        import requests

        ok, encoded = cv2.imencode(".jpg", image_bgr)
        if not ok:
            raise ValueError("Failed to encode image for remote tampering service.")
        resp = requests.post(
            remote_url,
            files={"file": ("image.jpg", encoded.tobytes(), "image/jpeg")},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return TamperingResult(
            status="success",
            tampering_score=data.get("tampering_score"),
            anomaly_detected=data.get("anomaly_detected"),
            heatmap_path=data.get("heatmap_path"),
            engine="mantranet",
            message=data.get("message"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Remote ManTraNet call failed: %s", exc)
        return TamperingResult(status="unavailable", engine="mantranet_remote", message=repr(exc))
