from pydantic import BaseModel


class BarcodeResult(BaseModel):
    found: bool
    value: str | None = None
    format: str | None = None  # e.g. "EAN13", "UPCA"
    confidence: float | None = None
    bbox: list[int] | None = None  # [x, y, w, h]
    engine: str = "pyzbar"
    engine_version: str | None = None
    error_message: str | None = None
