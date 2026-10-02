from app.schemas.barcode import BarcodeResult
from app.schemas.compliance import ComplianceResult
from app.schemas.ocr import OCRResult
from app.schemas.product import ExtractedFields, ProductMatch, ReferenceComparison
from app.schemas.scan import ScanProductSummary, ScanResponse
from app.schemas.tampering import TamperingResult


def aggregate_scan_response(
    *,
    scan_id: str,
    mode: str,
    ocr: OCRResult,
    barcode: BarcodeResult,
    tampering: TamperingResult,
    fields: ExtractedFields,
    product_match: ProductMatch,
    reference_comparison: ReferenceComparison,
    compliance: ComplianceResult,
    reference_brand: str | None,
    reference_name: str | None,
) -> ScanResponse:
    warnings: list[str] = list(compliance.warnings)

    if ocr.status != "success":
        warnings.append("OCR did not complete successfully; results may be incomplete.")
    if not barcode.found:
        warnings.append("No barcode detected on this image.")
    if tampering.status != "success":
        warnings.append("Tampering evidence unavailable for this scan.")
    if not product_match.reference_found:
        warnings.append("No matching reference product found; showing extraction and available checks only.")

    overall_status = "completed"
    if ocr.status == "failed" and not barcode.found:
        overall_status = "partial"

    return ScanResponse(
        scan_id=scan_id,
        status=overall_status,
        mode=mode,
        product=ScanProductSummary(
            name=reference_name or (fields.product_name.value if fields.product_name.found else None),
            brand=reference_brand or (fields.brand.value if fields.brand.found else None),
            reference_found=product_match.reference_found,
            match_method=product_match.match_method,
        ),
        ocr=ocr,
        barcode=barcode,
        tampering=tampering,
        extracted_fields=fields,
        reference_comparison=reference_comparison,
        compliance=compliance,
        warnings=warnings,
    )
