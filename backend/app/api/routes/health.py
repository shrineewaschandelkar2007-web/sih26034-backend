from fastapi import APIRouter, Depends

from app.api.deps import settings_dep
from app.core.config import Settings
from app.db.supabase_client import get_client
from app.models.barcode_model import decoder_load_error, get_decoder
from app.models.ocr_model import get_ocr_reader, ocr_load_error
from app.schemas.common import HealthComponent, HealthResponse

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(settings_dep)):
    return HealthResponse(status="ok", version=settings.app_version)


@router.get("/health/models", response_model=HealthResponse)
def health_models(settings: Settings = Depends(settings_dep)):
    ocr_status = "ok" if get_ocr_reader() is not None else f"unavailable: {ocr_load_error()}"
    barcode_status = "ok" if get_decoder() is not None else f"unavailable: {decoder_load_error()}"
    tampering_status = "ok" if settings.tampering_service_mode != "disabled" else "disabled"

    return HealthResponse(
        status="ok",
        version=settings.app_version,
        components=HealthComponent(ocr=ocr_status, barcode=barcode_status, tampering=tampering_status),
    )


@router.get("/health/storage", response_model=HealthResponse)
def health_storage(settings: Settings = Depends(settings_dep)):
    status_str = "ok" if settings.supabase_configured else "local_fallback"
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        components=HealthComponent(supabase=status_str),
    )


@router.get("/health/database", response_model=HealthResponse)
def health_database(settings: Settings = Depends(settings_dep)):
    client = get_client()
    status_str = "ok" if client is not None else "unavailable"
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        components=HealthComponent(supabase=status_str),
    )
