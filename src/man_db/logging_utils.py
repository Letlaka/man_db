from __future__ import annotations

import structlog

from .event_codes import EventCode, LogName

LoggerType = structlog.stdlib.BoundLogger


def get_logger(name: str) -> LoggerType:
    return structlog.get_logger(name)


def log_event(
    logger: LoggerType,
    *,
    log_name: LogName,
    event_code: EventCode,
    event: str,
    level: str = "info",
    **extra: object,
) -> None:
    bound_logger = logger.bind(log_name=log_name.value, event_code=int(event_code))
    log_method = getattr(bound_logger, level.lower(), bound_logger.info)
    log_method(event, **extra)
