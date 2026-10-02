"""
Explicit error classes + handlers so the frontend always gets a stable,
predictable JSON error shape and never sees a stack trace.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for all domain errors. code is a stable machine-readable string."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str, *, scan_id: str | None = None):
        super().__init__(message)
        self.message = message
        self.scan_id = scan_id


class InvalidImageError(AppError):
    code = "INVALID_IMAGE"
    http_status = 400


class ImageTooLargeError(AppError):
    code = "IMAGE_TOO_LARGE"
    http_status = 413


class OCRProcessingError(AppError):
    code = "OCR_PROCESSING_ERROR"
    http_status = 502


class BarcodeProcessingError(AppError):
    code = "BARCODE_PROCESSING_ERROR"
    http_status = 502


class TamperingProcessingError(AppError):
    code = "TAMPERING_PROCESSING_ERROR"
    http_status = 502


class ReferenceLookupError(AppError):
    code = "REFERENCE_LOOKUP_ERROR"
    http_status = 502


class ComplianceEngineError(AppError):
    code = "COMPLIANCE_ENGINE_ERROR"
    http_status = 500


class StorageError(AppError):
    code = "STORAGE_ERROR"
    http_status = 502


class DatabaseError(AppError):
    code = "DATABASE_ERROR"
    http_status = 502


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404


def _error_payload(err: AppError) -> dict:
    payload = {"error": {"code": err.code, "message": err.message}}
    if err.scan_id:
        payload["error"]["scan_id"] = err.scan_id
    return payload


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.http_status, content=_error_payload(exc))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception):
        # Never leak stack traces / internals to the client.
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "Unexpected server error."}},
        )
