"""
Optional authentication layer. The spec (section 3, Auth bullet) lists
Supabase Auth as available "if authentication is enabled for the
prototype" - it is NOT required for the first SIH demo, so no route
in this backend enforces login by default.

This module exposes:
  - GET /api/v1/auth/status - tells the frontend whether auth is
    currently enforced, so the UI can decide whether to show a login
    screen.
  - `get_current_user_optional`, a FastAPI dependency other routes can
    opt into later (e.g. to distinguish inspector vs. consumer mode by
    verified identity instead of a client-supplied query param).
"""

from fastapi import APIRouter, Header

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.supabase_client import get_client

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/status")
def auth_status():
    settings = get_settings()
    return {"auth_enforced": False, "supabase_auth_available": settings.supabase_configured}


def get_current_user_optional(authorization: str | None = Header(default=None)) -> dict | None:
    """
    Verifies a Supabase JWT if one is supplied, but never raises if it
    is missing - callers decide whether the route requires a user.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    client = get_client()
    if client is None:
        return None

    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_response = client.auth.get_user(token)
        return user_response.user.model_dump() if user_response and user_response.user else None
    except Exception as exc:  # noqa: BLE001
        logger.info("Auth token verification failed (non-fatal, auth optional): %s", exc)
        return None
