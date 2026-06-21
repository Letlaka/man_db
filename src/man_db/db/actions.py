from __future__ import annotations

import os
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from django.core.management.base import CommandError

from man_db.config import get_reset_app_allowlist
from man_db.db.backup_utils import (
    build_pg_dump_command,
    build_pg_restore_command,
    ensure_directory,
    find_executable,
    pgpass_env,
    run_subprocess,
    timestamped_filename,
)
from man_db.db.db_utils import (
    create_database,
    delete_migrations_and_force_delete_db,
    force_delete_database,
    server_ping,
)
from man_db.db.settings import get_database_config
from man_db.event_codes import EventCode, LogName
from man_db.logging_utils import get_logger, log_event

logger = get_logger(__name__)


class StyleProtocol(Protocol):
    def SUCCESS(self, text: str) -> str: ...


class StdoutProtocol(Protocol):
    def write(self, text: str) -> None: ...


Options = dict[str, Any]


def _database_alias(options: Options) -> str:
    return str(options.get("database") or "default")


def _compression_level(options: Options) -> int:
    level = int(options["compression"])
    if not 0 <= level <= 9:
        raise CommandError("Compression level must be between 0 and 9.")
    return level


def _restore_jobs(options: Options) -> int:
    jobs = int(options["jobs"])
    max_jobs = max(1, os.cpu_count() or 1)
    if not 1 <= jobs <= max_jobs:
        raise CommandError(f"Restore jobs must be between 1 and {max_jobs}.")
    return jobs


def _handle_create(
    options: Options, stdout: StdoutProtocol, style: StyleProtocol
) -> None:
    alias = _database_alias(options)
    log_event(
        logger,
        log_name=LogName.APPLICATION,
        event_code=EventCode.APPLICATION_DB_CREATE_REQUESTED,
        event="Create action requested.",
        database_alias=alias,
    )
    create_database(alias)
    stdout.write(style.SUCCESS("Database creation complete."))


def _handle_drop(
    options: Options, stdout: StdoutProtocol, style: StyleProtocol
) -> None:
    if not options["yes"]:
        raise CommandError("'drop' is destructive. Re-run with --yes to confirm.")

    alias = _database_alias(options)
    log_event(
        logger,
        log_name=LogName.APPLICATION,
        event_code=EventCode.APPLICATION_DB_DROP_REQUESTED,
        event="Drop action requested.",
        database_alias=alias,
    )
    force_delete_database(alias, confirmed=True)
    stdout.write(style.SUCCESS("Database dropped."))


def _reset_app_labels(options: Options) -> list[str]:
    selected_apps = [str(app) for app in options.get("apps") or []]
    if selected_apps:
        return selected_apps

    configured_apps = get_reset_app_allowlist()
    if configured_apps:
        return configured_apps

    raise CommandError(
        "'reset' requires --apps or MAN_DB_RESET_APP_ALLOWLIST to scope migration deletion."
    )


def _handle_reset(
    options: Options, stdout: StdoutProtocol, style: StyleProtocol
) -> None:
    if not options["yes"]:
        raise CommandError("'reset' is destructive. Re-run with --yes to confirm.")

    alias = _database_alias(options)
    delete_migrations_and_force_delete_db(
        alias,
        force=True,
        confirmed=True,
        app_labels=_reset_app_labels(options),
    )
    stdout.write(style.SUCCESS("Migrations cleared and database dropped."))


def _handle_ping(
    options: Options, stdout: StdoutProtocol, style: StyleProtocol
) -> None:
    alias = _database_alias(options)
    if not server_ping(alias):
        raise CommandError(
            "PostgreSQL not reachable. Check host, port, user, and password."
        )
    stdout.write(style.SUCCESS("PostgreSQL reachable."))


def _handle_backup(
    options: Options, stdout: StdoutProtocol, style: StyleProtocol
) -> None:
    alias = _database_alias(options)
    db = get_database_config(alias)
    if not db.name:
        raise CommandError(f"Database alias '{alias}' has an empty NAME setting.")

    output_dir = Path(str(options["output_dir"])).expanduser().resolve()
    filename_prefix = str(options["prefix"])
    compression_level = _compression_level(options)
    include_owner_and_privileges = bool(options["include_owner"])

    backup_name = timestamped_filename(
        database_name=db.name,
        prefix=filename_prefix,
        extension="dump",
    )
    backup_path = (output_dir / backup_name).resolve()
    if not backup_path.is_relative_to(output_dir):
        raise CommandError(
            "Backup path must stay within the requested output directory."
        )

    pg_dump_executable = find_executable("PG_DUMP_PATH", "pg_dump")
    ensure_directory(backup_path)

    command = build_pg_dump_command(
        pg_dump_executable=pg_dump_executable,
        db=db,
        output_file=backup_path,
        compression_level=compression_level,
        include_owner_and_privileges=include_owner_and_privileges,
    )
    command_line = " ".join(shlex.quote(part) for part in command)
    stdout.write(f"Running: {command_line}")

    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_BACKUP_STARTED,
        event="Running pg_dump.",
        database_alias=alias,
        database_name=db.name,
        backup_path=str(backup_path),
    )
    with pgpass_env(db, os.environ.copy()) as env:
        run_subprocess(command, env)
    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_BACKUP_COMPLETED,
        event="pg_dump completed successfully.",
        database_alias=alias,
        database_name=db.name,
        backup_path=str(backup_path),
    )
    stdout.write(style.SUCCESS(f"Backup complete: {backup_path}"))


def _handle_restore(
    options: Options, stdout: StdoutProtocol, style: StyleProtocol
) -> None:
    if not options["i_understand"]:
        raise CommandError(
            "Refusing to run without --i-understand. This will DROP and recreate objects."
        )

    alias = _database_alias(options)
    db = get_database_config(alias)
    backup_value = options.get("backup") or ""
    if not backup_value:
        raise CommandError("--backup is required for the restore action.")
    archive_path = Path(str(backup_value)).expanduser().resolve()
    if not archive_path.exists():
        raise CommandError(f"Backup file not found: {archive_path}")

    if not db.name and not bool(options["create_db"]):
        raise CommandError(f"Database alias '{alias}' has an empty NAME setting.")

    parallel_jobs = _restore_jobs(options)

    pg_restore_executable = find_executable("PG_RESTORE_PATH", "pg_restore")
    command = build_pg_restore_command(
        pg_restore_executable=pg_restore_executable,
        db=db,
        archive_file=archive_path,
        create_database_first=bool(options["create_db"]),
        parallel_jobs=parallel_jobs,
        include_owner_and_privileges=bool(options["include_owner"]),
    )
    command_line = " ".join(shlex.quote(part) for part in command)
    stdout.write(f"Running: {command_line}")

    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_RESTORE_STARTED,
        event="Running pg_restore.",
        database_alias=alias,
        archive_path=str(archive_path),
    )
    with pgpass_env(db, os.environ.copy()) as env:
        run_subprocess(command, env)
    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_RESTORE_COMPLETED,
        event="pg_restore completed successfully.",
        database_alias=alias,
        archive_path=str(archive_path),
    )
    stdout.write(style.SUCCESS("Restore complete."))


def perform_action(
    action: str,
    options: Options,
    stdout: StdoutProtocol,
    style: StyleProtocol,
) -> None:
    handlers: dict[str, Callable[[Options, StdoutProtocol, StyleProtocol], None]] = {
        "create": _handle_create,
        "drop": _handle_drop,
        "reset": _handle_reset,
        "ping": _handle_ping,
        "backup": _handle_backup,
        "restore": _handle_restore,
    }

    try:
        handler = handlers[action]
    except KeyError as exc:
        raise CommandError(f"Unknown action: {action}") from exc

    handler(options, stdout, style)
