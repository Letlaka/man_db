from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def get_base_dir() -> Path:
    base_dir = getattr(settings, "BASE_DIR", None)
    if base_dir is None:
        raise ImproperlyConfigured(
            "man_db requires settings.BASE_DIR to be configured. "
            "Add BASE_DIR = Path(__file__).resolve().parent.parent to your settings, "
            "or pass --apps explicitly to scope the reset operation."
        )
    return Path(base_dir).resolve()


def get_trusted_executable_dirs() -> tuple[Path, ...]:
    from man_db.db.backup_utils import DEFAULT_TRUSTED_EXECUTABLE_DIRS

    configured_dirs = getattr(settings, "MAN_DB_TRUSTED_EXECUTABLE_DIRS", None)
    if configured_dirs is None:
        return DEFAULT_TRUSTED_EXECUTABLE_DIRS
    return tuple(Path(directory).expanduser().resolve() for directory in configured_dirs)


def get_reset_app_allowlist() -> list[str]:
    return [str(app) for app in getattr(settings, "MAN_DB_RESET_APP_ALLOWLIST", ())]


def get_backup_output_dir() -> Path:
    return get_base_dir() / "backups"
