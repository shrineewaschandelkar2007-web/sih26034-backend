from pydantic import BaseModel


class HealthComponent(BaseModel):
    api: str = "ok"
    ocr: str = "unknown"
    barcode: str = "unknown"
    tampering: str = "unknown"
    supabase: str = "unknown"


class HealthResponse(BaseModel):
    status: str
    version: str
    components: HealthComponent | None = None


class APIErrorDetail(BaseModel):
    code: str
    message: str
    scan_id: str | None = None


class APIError(BaseModel):
    error: APIErrorDetail
