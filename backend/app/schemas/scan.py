from pydantic import BaseModel

from app.schemas.barcode import BarcodeResult
from app.schemas.compliance import ComplianceResult
from app.schemas.ocr import OCRResult
from app.schemas.product import ExtractedFields, ReferenceComparison
from app.schemas.tampering import TamperingResult


class ScanProductSummary(BaseModel):
    name: str | None = None
    brand: str | None = None
    reference_found: bool = False
    match_method: str | None = None


class ScanResponse(BaseModel):
    scan_id: str
    status: str  # "completed" | "partial" | "failed"
    mode: str = "consumer"  # "consumer" | "inspector"
    product: ScanProductSummary
    ocr: OCRResult
    barcode: BarcodeResult
    tampering: TamperingResult
    extracted_fields: ExtractedFields
    reference_comparison: ReferenceComparison
    compliance: ComplianceResult
    warnings: list[str] = []


class ScanHistoryItem(BaseModel):
    scan_id: str
    created_at: str
    product_name: str | None = None
    reference_found: bool = False
    compliance_status: str | None = None
