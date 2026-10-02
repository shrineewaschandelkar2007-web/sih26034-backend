"""
Implements the /api/v1/scans pipeline in the exact order from spec
section 15, adapted to the REAL live database shape (confirmed via a
Supabase information_schema dump from the team's own project, not the
originally-drafted spec schema):

  - scan_records.id (bigint, auto-generated) IS the scan_id used
    everywhere else - there is no separate UUID. Because of this, the
    summary row (detected_barcode, detected_product_name, ...,
    status) is written ONCE, after the whole pipeline has already run
    in memory, and its returned id is then used for the four detail
    tables (ocr_results, barcode_results, tampering_results,
    compliance_results).
  - There is no field_extractions / reference_comparisons /
    compliance_checks table: extracted fields live in
    ocr_results.structured_data, and rule-by-rule detail lives in
    compliance_results.rule_results (jsonb), not a child table.

Keeps partial outputs if one optional component fails - never turns
one missing barcode (or a failed tampering check) into a total 500
error.
"""

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.api.deps import settings_dep
from app.core.config import Settings
from app.core.errors import ImageTooLargeError, NotFoundError
from app.core.logging import get_logger, stage_timer
from app.core.security import new_scan_id, sanitize_filename
from app.db.repositories import results as results_repo
from app.db.repositories import scans as scans_repo
from app.db.storage import create_signed_url, upload_bytes
from app.schemas.barcode import BarcodeResult
from app.schemas.product import ProductMatch, ReferenceComparison
from app.schemas.scan import ScanResponse
from app.schemas.tampering import TamperingResult
from app.services import (
    barcode_service,
    compliance_engine,
    field_extractor,
    image_preprocessing,
    normalizer,
    ocr_service,
    product_matcher,
    reference_service,
    result_aggregator,
    tampering_service,
)
from app.utils.file_validation import validate_and_decode_image
from app.utils.hashing import sha256_bytes

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["scans"])


def _safe(scan_ref: str, stage: str, fn, fallback):
    """
    Runs one OPTIONAL pipeline stage. If it raises, log it and return
    the fallback instead, so one failing component degrades the result
    to 'partial' rather than turning the whole scan into a 500 (spec
    section 15). `scan_ref` is a pre-persistence trace id (image hash
    prefix) since the real bigint scan_id doesn't exist yet at this
    point in the pipeline.
    """
    try:
        with stage_timer(logger, scan_id=scan_ref, stage=stage):
            return fn()
    except Exception as exc:  # noqa: BLE001
        logger.error("scan_ref=%s stage=%s degraded_to_fallback error=%s", scan_ref, stage, repr(exc))
        return fallback


@router.post("/scans", response_model=ScanResponse)
async def create_scan(
    file: UploadFile = File(...),
    mode: str = Query(default="consumer", pattern="^(consumer|inspector)$"),
    settings: Settings = Depends(settings_dep),
):
    safe_filename = sanitize_filename(file.filename or "upload.jpg")

    raw_bytes = await file.read()
    if len(raw_bytes) > settings.max_upload_size_bytes:
        raise ImageTooLargeError("Uploaded file exceeds the maximum allowed size.")

    image_hash = sha256_bytes(raw_bytes)
    # Per-request trace id (log correlation + API scan_id fallback when Supabase isn't
    # configured). Deliberately NOT derived from image_hash: two requests uploading the
    # identical image bytes must still get distinct scan identities.
    scan_ref = new_scan_id()

    # 2. Validate image
    with stage_timer(logger, scan_id=scan_ref, stage="validate_image"):
        image_bgr = validate_and_decode_image(raw_bytes, max_bytes=settings.max_upload_size_bytes)

    # 4. Save original image to Storage - content-addressed path, since the real
    # scan_id doesn't exist until scan_records is inserted later in this pipeline.
    image_path, image_url = None, None
    try:
        with stage_timer(logger, scan_id=scan_ref, stage="store_original_image"):
            image_path = upload_bytes(
                settings.supabase_bucket_scan_images,
                f"{image_hash}/{safe_filename}",
                raw_bytes,
                content_type=file.content_type or "image/jpeg",
            )
            image_url = create_signed_url(settings.supabase_bucket_scan_images, f"{image_hash}/{safe_filename}")
    except Exception as exc:  # noqa: BLE001
        logger.error("scan_ref=%s stage=store_original_image status=failed error=%s", scan_ref, repr(exc))

    # 5. Preprocess image
    with stage_timer(logger, scan_id=scan_ref, stage="preprocess"):
        processed_image = image_preprocessing.preprocess_for_models(image_bgr)

    # 6. Run OCR
    with stage_timer(logger, scan_id=scan_ref, stage="ocr"):
        ocr_result = ocr_service.run_ocr(processed_image)
    logger.info("scan_ref=%s stage=ocr result_status=%s", scan_ref, ocr_result.status)

    # 6b. If no manufacturing/use-by date matched on the first pass, retry on a
    # zoomed top-strip crop - small printed dates are often missed at full-image scale.
    combined_text = ocr_result.combined_text
    if ocr_result.status == "success" and not any(token in combined_text.lower() for token in ("mfg", "pkd", "use by", "best before")):
        try:
            with stage_timer(logger, scan_id=scan_ref, stage="ocr_date_zoom_retry"):
                crop = image_preprocessing.top_strip(processed_image)
                enhanced = image_preprocessing.enhance_region_for_ocr(crop)
                zoom_result = ocr_service.run_ocr(enhanced)
                if zoom_result.status == "success" and zoom_result.combined_text:
                    combined_text = combined_text + "\n" + zoom_result.combined_text
        except Exception as exc:  # noqa: BLE001
            logger.warning("scan_ref=%s stage=ocr_date_zoom_retry status=failed error=%s", scan_ref, repr(exc))

    # 7. Run barcode decoder
    barcode_result = _safe(
        scan_ref,
        "barcode",
        lambda: barcode_service.run_barcode_scan(processed_image),
        BarcodeResult(found=False, error_message="barcode stage failed"),
    )

    # 8. Run tampering analysis
    tampering_result = _safe(
        scan_ref,
        "tampering",
        lambda: tampering_service.run_tampering_check(processed_image),
        TamperingResult(status="failed", message="Tampering stage failed unexpectedly."),
    )

    # 9. Extract structured fields
    with stage_timer(logger, scan_id=scan_ref, stage="field_extraction"):
        raw_fields = field_extractor.extract_raw_fields(combined_text)
        brand_guess, product_guess = field_extractor.guess_brand_and_product(combined_text, reference_service.known_brands())
        extracted_fields = normalizer.build_extracted_fields(raw_fields, brand_guess, product_guess, barcode_result.value)

    # 10-11. Identify product / load reference if known
    product_match, reference_product = _safe(
        scan_ref,
        "product_matching",
        lambda: product_matcher.match_product(barcode_value=barcode_result.value, ocr_text=combined_text, brand_guess=brand_guess),
        (ProductMatch(reference_found=False), None),
    )

    # 12. Compare fields if reference exists
    reference_comparison = _safe(
        scan_ref,
        "reference_comparison",
        lambda: product_matcher.compare_with_reference(extracted_fields, reference_product),
        ReferenceComparison(available=False, fields={}),
    )

    # 13-14. Load rules + run compliance engine
    with stage_timer(logger, scan_id=scan_ref, stage="compliance_engine"):
        compliance_result = compliance_engine.evaluate_compliance(
            fields=extracted_fields,
            tampering=tampering_result,
            reference_comparison=reference_comparison,
            reference_found=product_match.reference_found,
            ocr_succeeded=(ocr_result.status == "success"),
        )

    product_name = (
        reference_product.product_name
        if reference_product
        else (extracted_fields.product_name.value if extracted_fields.product_name.found else None)
    )
    product_brand = (
        reference_product.brand if reference_product else (extracted_fields.brand.value if extracted_fields.brand.found else None)
    )

    # 15. Persist all results. scan_records is written FIRST (with everything already
    # computed above) so its auto-generated bigint id can be used as scan_id for the
    # four detail tables below.
    scan_id_int: int | None = None
    with stage_timer(logger, scan_id=scan_ref, stage="persist_results"):
        try:
            scan_id_int = scans_repo.create_scan_record(
                image_path=image_path,
                image_url=image_url,
                detected_barcode=barcode_result.value,
                detected_product_name=product_name,
                detected_brand=product_brand,
                reference_product_id=product_match.product_id,
                ocr_confidence=ocr_result.average_confidence,
                tampering_score=tampering_result.tampering_score,
                status=compliance_result.overall_status,
            )
            if scan_id_int is not None:
                results_repo.save_ocr_result(
                    scan_id_int,
                    raw_text=ocr_result.combined_text,
                    confidence=ocr_result.average_confidence,
                    structured_data=extracted_fields.model_dump(),
                )
                results_repo.save_barcode_result(
                    scan_id_int,
                    barcode=barcode_result.value,
                    detected=barcode_result.found,
                    confidence=barcode_result.confidence,
                )
                results_repo.save_tampering_result(
                    scan_id_int,
                    tampering_score=tampering_result.tampering_score,
                    status=tampering_result.status,
                    heatmap_path=tampering_result.heatmap_path,
                )
                compliance_payload = compliance_result.model_dump()
                compliance_payload.pop("warnings", None)  # not a DB column - API-response-only
                results_repo.save_compliance_result(scan_id_int, compliance_payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("scan_ref=%s stage=persist_results status=failed error=%s", scan_ref, repr(exc))

    # 16. Return a single structured JSON response
    return result_aggregator.aggregate_scan_response(
        scan_id=str(scan_id_int) if scan_id_int is not None else scan_ref,
        mode=mode,
        ocr=ocr_result,
        barcode=barcode_result,
        tampering=tampering_result,
        fields=extracted_fields,
        product_match=product_match,
        reference_comparison=reference_comparison,
        compliance=compliance_result,
        reference_brand=product_brand,
        reference_name=product_name,
    )


@router.get("/scans/{scan_id}")
def get_scan_result(scan_id: str):
    try:
        numeric_id = int(scan_id)
    except ValueError as exc:
        raise NotFoundError(f"Scan {scan_id} not found.", scan_id=scan_id) from exc

    row = scans_repo.get_scan(numeric_id)
    if row is None:
        raise NotFoundError(f"Scan {scan_id} not found.", scan_id=scan_id)
    return row
