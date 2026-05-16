from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from django.core.management.base import CommandError

from man_db.db.backup_utils import (
    build_pg_dump_command,
    build_pg_restore_command,
    ensure_directory,
    find_executable,
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

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)


class StyleProtocol(Protocol):
    SUCCESS: Callable[[str], str]


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


def _handle_create(options: Options, stdout: StdoutProtocol, style: StyleProtocol) -> None:
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


def _handle_drop(options: Options, stdout: StdoutProtocol, style: StyleProtocol) -> None:
    if not options["yes"]:
        raise CommandError("'drop' is destructive. Re-run with --yes to confirm.")

    alias = _database_alias(options)
    force_delete_database(alias)
    stdout.write(style.SUCCESS("Database dropped."))


def _handle_reset(options: Options, stdout: StdoutProtocol, style: StyleProtocol) -> None:
    if not options["yes"]:
        raise CommandError("'reset' is destructive. Re-run with --yes to confirm.")

    alias = _database_alias(options)
    delete_migrations_and_force_delete_db(alias, force=True)
    stdout.write(style.SUCCESS("Migrations cleared and database dropped."))


def _handle_ping(options: Options, stdout: StdoutProtocol, style: StyleProtocol) -> None:
    alias = _database_alias(options)
    if not server_ping(alias):
        raise CommandError("PostgreSQL not reachable. Check host, port, user, and password.")
    stdout.write(style.SUCCESS("PostgreSQL reachable."))


def _handle_backup(options: Options, stdout: StdoutProtocol, style: StyleProtocol) -> None:
    alias = _database_alias(options)
    db = get_database_config(alias)
    if not db.name:
        raise CommandError(
            f"Database alias '{alias}' has an empty NAME setting."
        )

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
        raise CommandError("Backup path must stay within the requested output directory.")

    pg_dump_executable = find_executable("PG_DUMP_PATH", "pg_dump")
    ensure_directory(backup_path)

    env = os.environ.copy()
    if db.password:
        env["PGPASSWORD"] = db.password

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
        event_code=EventCode.AUDIT_EXPORT_STARTED,
        event="Running pg_dump.",
        database_alias=alias,
        database_name=db.name,
        backup_path=str(backup_path),
    )
    run_subprocess(command, env)
    stdout.write(style.SUCCESS(f"Backup complete: {backup_path}"))


def _handle_restore(options: Options, stdout: StdoutProtocol, style: StyleProtocol) -> None:
    if not options["i_understand"]:
        raise CommandError(
            "Refusing to run without --i-understand. This will DROP and recreate objects."
        )

    alias = _database_alias(options)
    db = get_database_config(alias)
    archive_path = Path(str(options.get("backup") or "")).expanduser().resolve()
    if not archive_path.exists():
        raise CommandError(f"Backup file not found: {archive_path}")

    if not db.name and not bool(options["create_db"]):
        raise CommandError(
            f"Database alias '{alias}' has an empty NAME setting."
        )

    env = os.environ.copy()
    if db.password:
        env["PGPASSWORD"] = db.password

    pg_restore_executable = find_executable("PG_RESTORE_PATH", "pg_restore")
    command = build_pg_restore_command(
        pg_restore_executable=pg_restore_executable,
        db=db,
        archive_file=archive_path,
        create_database_first=bool(options["create_db"]),
        parallel_jobs=int(options["jobs"]),
        include_owner_and_privileges=bool(options["include_owner"]),
    )
    command_line = " ".join(shlex.quote(part) for part in command)
    stdout.write(f"Running: {command_line}")

    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_EXPORT_STARTED,
        event="Running pg_restore.",
        database_alias=alias,
        archive_path=str(archive_path),
    )
    run_subprocess(command, env)
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
