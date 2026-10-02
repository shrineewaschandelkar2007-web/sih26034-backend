"""
Lazy Supabase client singleton. Uses the service-role key for
server-side writes (this key must NEVER be sent to the frontend -
see .env.example and README security notes). If Supabase isn't
configured, get_client() returns None and callers must degrade
gracefully (log + skip persistence) rather than crash the request -
persistence is important but must not block the demo pipeline.
"""

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client = None
_attempted = False


def get_client():
    global _client, _attempted
    if _client is not None or _attempted:
        return _client

    _attempted = True
    settings = get_settings()
    if not settings.supabase_configured:
        logger.warning("Supabase not configured (SUPABASE_URL/keys missing) - persistence will be skipped.")
        return None

    try:
        from supabase import create_client

        key = settings.supabase_service_role_key or settings.supabase_anon_key
        _client = create_client(settings.supabase_url, key)
        logger.info("Supabase client initialized.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to initialize Supabase client: %s", exc)
        _client = None

    return _client
