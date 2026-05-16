from __future__ import annotations

import contextlib
import os

import structlog

__version__ = "0.1.0"

with contextlib.suppress(Exception):
    structlog.contextvars.bind_contextvars(
        service=os.getenv("SERVICE_NAME", "man_db"),
        environment=os.getenv("ENVIRONMENT", "local"),
    )
