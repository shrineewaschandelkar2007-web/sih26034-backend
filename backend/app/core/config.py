"""
Central configuration. All tunables come from environment variables,
loaded via .env in development. Never hard-code secrets or absolute
Windows paths here.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "SIH26034 Compliance Backend"
    app_version: str = "0.1.0"
    environment: str = "development"  # development | production

    # --- CORS ---
    # Comma-separated list of allowed frontend origins, e.g.
    # "http://localhost:5173,http://192.168.1.15:5173"
    cors_allowed_origins: str = "http://localhost:5173"

    # --- Uploads ---
    max_upload_size_mb: int = 12
    allowed_image_types: str = "image/jpeg,image/png,image/webp,image/jpg"

    # --- Supabase ---
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""  # server-side only, NEVER sent to frontend
    supabase_bucket_scan_images: str = "scan-images"
    supabase_bucket_scan_artifacts: str = "scan-artifacts"
    supabase_bucket_reference_products: str = "reference-products"

    # --- Models ---
    ocr_lang: str = "en"
    ocr_enable_mkldnn: bool = False  # oneDNN CPU bug workaround, see README
    tampering_service_mode: str = "heuristic"  # "heuristic" | "mantranet_remote" | "disabled"
    tampering_remote_url: str = ""  # if using an isolated ManTraNet microservice

    # --- Local paths (relative to backend root, never absolute Windows paths) ---
    local_storage_dir: str = "local_storage"  # fallback when Supabase isn't configured

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def allowed_image_types_list(self) -> list[str]:
        return [t.strip() for t in self.allowed_image_types.split(",") if t.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and (self.supabase_anon_key or self.supabase_service_role_key))


@lru_cache
def get_settings() -> Settings:
    return Settings()
