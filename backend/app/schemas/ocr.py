from pydantic import BaseModel, Field


class OCRTextBlock(BaseModel):

    text: str

    confidence: float

    bbox: list[list[float]] | None = None


class OCRResult(BaseModel):

    status: str  # "success" | "failed" | "unavailable"

    raw_text: list[OCRTextBlock] = Field(default_factory=list)

    combined_text: str = ""

    average_confidence: float | None = None

    engine: str = "tesseract"

    engine_version: str | None = None

    error_message: str | None = None
