"""
FastAPI entrypoint.

Run with:

    uvicorn app.main:app --reload
    uvicorn app.main:app --host 0.0.0.0 --port 8000

Swagger:
    http://127.0.0.1:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, health, history, products, scan
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger


# =========================================================
# SETTINGS
# =========================================================

settings = get_settings()

configure_logging()

logger = get_logger(__name__)


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "AI-powered verification of packaged commodity labels against the "
        "Legal Metrology (Packaged Commodities) Rules, 2011. OCR + barcode + "
        "tampering evidence feed a deterministic, rule-based compliance engine."
    ),
)


# =========================================================
# CORS
# =========================================================

# Origins allowed for local frontend development.
# This supports VS Code Live Server and common local frontend ports.

local_frontend_origins = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",

    "http://localhost:5501",
    "http://127.0.0.1:5501",

    "http://localhost:5173",
    "http://127.0.0.1:5173",

    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


# =========================================================
# VERCEL FRONTEND
# =========================================================

# Production frontend deployed on Vercel.
vercel_frontend_origins = [
    "https://sih26034-backend-frontend-p9tphk8ui.vercel.app",
]


# =========================================================
# COMBINE ALLOWED ORIGINS
# =========================================================

# Combine:
# 1. Origins configured through .env/settings
# 2. Local development origins
# 3. Production Vercel frontend origin

configured_origins = list(
    settings.cors_origins_list
)

allowed_origins = list(
    dict.fromkeys(
        configured_origins
        + local_frontend_origins
        + vercel_frontend_origins
    )
)


app.add_middleware(
    CORSMiddleware,

    allow_origins=allowed_origins,

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],
)


# =========================================================
# ERROR HANDLERS
# =========================================================

register_error_handlers(app)


# =========================================================
# ROUTERS
# =========================================================

app.include_router(health.router)

app.include_router(scan.router)

app.include_router(products.router)

app.include_router(history.router)

app.include_router(auth.router)


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
def on_startup():

    logger.info(
        "%s v%s starting | environment=%s | "
        "supabase_configured=%s | tampering_mode=%s",
        settings.app_name,
        settings.app_version,
        settings.environment,
        settings.supabase_configured,
        settings.tampering_service_mode,
    )

    logger.info(
        "CORS allowed origins: %s",
        allowed_origins,
    )

    if not settings.supabase_configured:

        logger.warning(
            "Supabase is not configured - running with local-disk "
            "storage fallback and in-memory/JSON reference data. "
            "Fine for local development, not for the real demo."
        )