from __future__ import annotations

from enum import Enum, IntEnum


class LogName(str, Enum):
    APPLICATION = "Application"
    SYSTEM = "System"
    AUDIT = "Audit"


class EventCode(IntEnum):
    APPLICATION_DB_CREATE_REQUESTED = 1000
    APPLICATION_DB_CREATED = 1001
    APPLICATION_DB_ALREADY_EXISTS = 1002

    SYSTEM_STARTUP = 3000
    SYSTEM_ERROR = 3002

    AUDIT_EXPORT_STARTED = 9000
    AUDIT_EXPORT_COMPLETED = 9001
    AUDIT_CONFIG_CHANGED = 9002
