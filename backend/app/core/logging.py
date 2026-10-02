"""
Structured logging. Every log line can carry request_id / scan_id / stage
so a broken demo can be traced quickly:

    scan_id=abc123 stage=ocr duration_ms=1842 status=success
"""

import logging
import sys
import time
from contextlib import contextmanager

LOG_FORMAT = "%(asctime)s level=%(levelname)s %(message)s"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def stage_timer(logger: logging.Logger, *, scan_id: str, stage: str):
    """
    Usage:
        with stage_timer(logger, scan_id=scan_id, stage="ocr"):
            run_ocr(...)

    Logs duration and success/failure automatically, in the
    'scan_id=... stage=... duration_ms=... status=...' shape the spec asks for.
    """
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - we want to log and re-raise
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "scan_id=%s stage=%s duration_ms=%s status=failed error=%s",
            scan_id,
            stage,
            duration_ms,
            repr(exc),
        )
        raise
    else:
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "scan_id=%s stage=%s duration_ms=%s status=success",
            scan_id,
            stage,
            duration_ms,
        )
