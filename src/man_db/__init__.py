from __future__ import annotations

import logging
import os
from importlib.metadata import PackageNotFoundError, version

import structlog

_logger = logging.getLogger(__name__)

try:
    __version__ = version("django-postgres-man-db")
except PackageNotFoundError:
    __version__ = "unknown"

try:
    structlog.contextvars.bind_contextvars(
        service=os.getenv("SERVICE_NAME", "man_db"),
        environment=os.getenv("ENVIRONMENT", "local"),
    )
except Exception:
    _logger.debug(
        "structlog context binding unavailable at import time",
        exc_info=True,
    )
