from pydantic import BaseModel


class TamperingResult(BaseModel):
    status: str  # "success" | "unavailable" | "failed"
    tampering_score: float | None = None  # 0.0 (clean) - 1.0 (highly suspicious)
    anomaly_detected: bool | None = None
    heatmap_path: str | None = None
    engine_version: str | None = None
    engine: str = "heuristic"  # "heuristic" | "mantranet" - see tampering_service.py
    message: str | None = None  # evidence-oriented wording, never a legal claim
