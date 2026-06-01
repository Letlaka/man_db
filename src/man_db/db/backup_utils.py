from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

from django.conf import settings
from django.core.management.base import CommandError
from django.utils import timezone

from man_db.db.settings import DatabaseConfig
from man_db.event_codes import EventCode, LogName
from man_db.logging_utils import get_logger, log_event

logger = get_logger(__name__)

DEFAULT_TRUSTED_EXECUTABLE_DIRS = (
    Path("/usr/bin"),
    Path("/usr/local/bin"),
    Path("/bin"),
    Path("/usr/sbin"),
    Path("/sbin"),
    Path("/usr/lib/postgresql"),
)


def ensure_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    log_event(
        logger,
        log_name=LogName.SYSTEM,
        event_code=EventCode.SYSTEM_STARTUP,
        event="Ensured backup directory exists.",
        path=str(path.parent),
    )


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _trusted_executable_dirs() -> tuple[Path, ...]:
    configured_dirs = getattr(settings, "MAN_DB_TRUSTED_EXECUTABLE_DIRS", None)
    if configured_dirs is None:
        return DEFAULT_TRUSTED_EXECUTABLE_DIRS
    return tuple(
        Path(directory).expanduser().resolve() for directory in configured_dirs
    )


def _path_is_trusted(path: Path) -> bool:
    resolved_path = path.resolve()
    return any(
        resolved_path.is_relative_to(directory)
        for directory in _trusted_executable_dirs()
    )


def find_executable(preferred_env_var: str, fallback_name: str) -> str:
    explicit_path = os.environ.get(preferred_env_var)
    if explicit_path:
        executable = Path(explicit_path).expanduser()
        if not executable.is_absolute():
            raise CommandError(f"{preferred_env_var} must be an absolute path.")

        executable = executable.resolve()
        if not _is_executable_file(executable):
            raise CommandError(f"{preferred_env_var} must point to an executable file.")

        log_event(
            logger,
            log_name=LogName.AUDIT,
            event_code=EventCode.AUDIT_CONFIG_CHANGED,
            event="Using executable from environment.",
            env_var=preferred_env_var,
            path=str(executable),
        )
        return str(executable)

    resolved = shutil.which(fallback_name)
    if not resolved:
        raise CommandError(
            f"Could not find '{fallback_name}'. Add it to PATH or set "
            f"{preferred_env_var} to the full executable path."
        )

    executable = Path(resolved).resolve()
    if not _is_executable_file(executable):
        raise CommandError(f"Resolved '{fallback_name}' is not an executable file.")

    if not _path_is_trusted(executable):
        raise CommandError(
            f"Resolved '{fallback_name}' is outside trusted executable directories. "
            f"Set {preferred_env_var} to an absolute trusted path or configure "
            "MAN_DB_TRUSTED_EXECUTABLE_DIRS."
        )

    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_CONFIG_CHANGED,
        event="Using executable from PATH.",
        executable=str(executable),
    )
    return str(executable)


def validate_filename_component(
    value: str,
    *,
    label: str,
    allow_empty: bool = False,
) -> str:
    if value == "":
        if allow_empty:
            return value
        raise CommandError(f"{label} cannot be empty.")

    if (
        value in {".", ".."}
        or len(PurePosixPath(value).parts) != 1
        or len(PureWindowsPath(value).parts) != 1
    ):
        raise CommandError(f"{label} must be a simple filename component, not a path.")

    return value


def timestamped_filename(database_name: str, prefix: str, extension: str) -> str:
    stamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    base = validate_filename_component(
        prefix,
        label="Backup prefix",
        allow_empty=True,
    ) or validate_filename_component(
        database_name,
        label="Database name",
    )
    return f"{base}_{stamp}.{extension.lstrip('.')}"


def build_pg_dump_command(
    pg_dump_executable: str,
    db: DatabaseConfig,
    output_file: Path,
    compression_level: int,
    *,
    include_owner_and_privileges: bool,
) -> list[str]:
    command = [
        pg_dump_executable,
        "-h",
        db.host,
        "-p",
        str(db.port),
        "-U",
        db.user,
        "-d",
        db.name,
        "-Fc",
        "-Z",
        str(compression_level),
        "-f",
        str(output_file),
    ]
    if not include_owner_and_privileges:
        command.extend(["--no-owner", "--no-privileges"])
    return command


def build_pg_restore_command(
    pg_restore_executable: str,
    db: DatabaseConfig,
    archive_file: Path,
    *,
    create_database_first: bool,
    parallel_jobs: int,
    include_owner_and_privileges: bool,
) -> list[str]:
    command = [
        pg_restore_executable,
        "-h",
        db.host,
        "-p",
        str(db.port),
        "-U",
        db.user,
        "-j",
        str(parallel_jobs),
        "--clean",
        "--if-exists",
    ]
    if not include_owner_and_privileges:
        command.extend(["--no-owner", "--no-privileges"])

    if create_database_first:
        command.extend(["-C", "-d", "postgres"])
    else:
        command.extend(["-d", db.name])

    command.append(str(archive_file))
    return command


def run_subprocess(command: list[str], env: dict[str, str]) -> None:
    command_line = " ".join(shlex.quote(part) for part in command)
    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_EXPORT_STARTED,
        event="Running subprocess.",
        command=command,
        command_line=command_line,
    )
    try:
        subprocess.run(command, env=env, check=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        log_event(
            logger,
            log_name=LogName.SYSTEM,
            event_code=EventCode.SYSTEM_ERROR,
            event="Subprocess failed.",
            exit_code=exc.returncode,
            command_line=command_line,
        )
        raise CommandError(
            f"Command failed with exit code {exc.returncode}: {command_line}"
        ) from exc

    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_EXPORT_COMPLETED,
        event="Subprocess completed successfully.",
        command_line=command_line,
    )
