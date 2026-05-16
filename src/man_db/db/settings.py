from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.management.base import CommandError


@dataclass(frozen=True)
class DatabaseConfig:
    alias: str
    engine: str
    name: str
    user: str
    password: str
    host: str
    port: int


def get_database_config(alias: str = "default") -> DatabaseConfig:
    database_settings: dict[str, Any] = settings.DATABASES.get(alias, {})
    if not database_settings:
        raise CommandError(f"Database alias '{alias}' not found in settings.DATABASES.")

    engine = str(database_settings.get("ENGINE") or "")
    if "django.db.backends.postgresql" not in engine:
        raise CommandError(
            f"Database alias '{alias}' is not configured for PostgreSQL."
        )

    return DatabaseConfig(
        alias=alias,
        engine=engine,
        name=str(database_settings.get("NAME") or ""),
        user=str(database_settings.get("USER") or ""),
        password=str(database_settings.get("PASSWORD") or ""),
        host=str(database_settings.get("HOST") or "127.0.0.1"),
        port=int(database_settings.get("PORT") or 5432),
    )
