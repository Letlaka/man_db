from __future__ import annotations

import sys
from pathlib import Path
from typing import IO

import psycopg
from django.apps import apps as django_apps
from django.core.management.base import CommandError
from psycopg import sql

from man_db.config import get_base_dir
from man_db.db.settings import DatabaseConfig, get_database_config
from man_db.event_codes import EventCode, LogName
from man_db.logging_utils import get_logger, log_event

logger = get_logger(__name__)


def _connect_as_admin(
    target_database_name: str,
    config: DatabaseConfig,
) -> psycopg.Connection:
    log_event(
        logger,
        log_name=LogName.SYSTEM,
        event_code=EventCode.SYSTEM_CONNECTED,
        event="Connecting to PostgreSQL.",
        host=config.host,
        port=config.port,
        user=config.user or "<empty-user>",
        target_database=target_database_name,
    )
    connection = psycopg.connect(
        dbname=target_database_name,
        user=config.user,
        password=config.password,
        host=config.host,
        port=config.port,
        connect_timeout=10,
    )
    connection.autocommit = True
    return connection


def _database_exists(connection: psycopg.Connection, database_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s;", (database_name,)
        )
        return cursor.fetchone() is not None


def server_ping(alias: str = "default") -> bool:
    config = get_database_config(alias)
    try:
        with (
            _connect_as_admin("postgres", config) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT 1;")
            cursor.fetchone()
    except psycopg.Error as error:
        log_event(
            logger,
            log_name=LogName.SYSTEM,
            event_code=EventCode.SYSTEM_ERROR,
            event="PostgreSQL ping failed.",
            database_alias=alias,
            error=str(error),
        )
        return False

    log_event(
        logger,
        log_name=LogName.SYSTEM,
        event_code=EventCode.SYSTEM_CONNECTED,
        event="PostgreSQL is reachable.",
        database_alias=alias,
    )
    return True


def create_database(alias: str = "default") -> None:
    config = get_database_config(alias)
    if not config.name:
        raise CommandError(f"Database alias '{alias}' has an empty NAME setting.")

    try:
        with _connect_as_admin("postgres", config) as connection:
            if _database_exists(connection, config.name):
                log_event(
                    logger,
                    log_name=LogName.APPLICATION,
                    event_code=EventCode.APPLICATION_DB_ALREADY_EXISTS,
                    event="Database already exists.",
                    database_alias=alias,
                    database_name=config.name,
                )
                return

            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(config.name))
                )
    except psycopg.Error as error:
        log_event(
            logger,
            log_name=LogName.SYSTEM,
            event_code=EventCode.SYSTEM_ERROR,
            event="Create database failed.",
            database_alias=alias,
            database_name=config.name,
            error=str(error),
        )
        raise CommandError(
            f"Failed to create database '{config.name}': {error}"
        ) from error

    log_event(
        logger,
        log_name=LogName.APPLICATION,
        event_code=EventCode.APPLICATION_DB_CREATED,
        event="Database created successfully.",
        database_alias=alias,
        database_name=config.name,
    )


def _terminate_backends(connection: psycopg.Connection, database_name: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s
              AND pid <> pg_backend_pid();
            """,
            (database_name,),
        )


def force_delete_database(
    alias: str = "default",
    *,
    confirmed: bool = False,
) -> None:
    if not confirmed:
        raise RuntimeError(
            "force_delete_database() requires confirmed=True. "
            "This operation is irreversible and cannot be undone."
        )

    config = get_database_config(alias)
    if not config.name:
        raise CommandError(f"Database alias '{alias}' has an empty NAME setting.")

    try:
        with _connect_as_admin("postgres", config) as connection:
            if not _database_exists(connection, config.name):
                log_event(
                    logger,
                    log_name=LogName.APPLICATION,
                    event_code=EventCode.APPLICATION_DB_NOT_FOUND,
                    event="Database does not exist.",
                    database_alias=alias,
                    database_name=config.name,
                )
                return

            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(config.name)
                        )
                    )
            except psycopg.Error:
                _terminate_backends(connection, config.name)
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {}").format(sql.Identifier(config.name))
                    )
    except psycopg.Error as error:
        log_event(
            logger,
            log_name=LogName.SYSTEM,
            event_code=EventCode.SYSTEM_ERROR,
            event="Drop database failed.",
            database_alias=alias,
            database_name=config.name,
            error=str(error),
        )
        raise CommandError(
            f"Failed to drop database '{config.name}': {error}"
        ) from error

    log_event(
        logger,
        log_name=LogName.APPLICATION,
        event_code=EventCode.APPLICATION_DB_DROPPED,
        event="Database dropped.",
        database_alias=alias,
        database_name=config.name,
    )


def _project_root() -> Path:
    return get_base_dir()


def _gather_app_dirs(root: Path, *, app_labels: list[str]) -> list[Path]:
    resolved_root = root.resolve()
    app_dirs: list[Path] = []
    missing_labels: list[str] = []
    for app_label in app_labels:
        try:
            app_config = django_apps.get_app_config(app_label)
        except LookupError:
            missing_labels.append(app_label)
            continue

        app_path = Path(app_config.path).resolve()
        if not app_path.is_relative_to(resolved_root):
            raise CommandError(
                f"App '{app_label}' is outside the project root and cannot be reset."
            )

        if not (app_path / "migrations").is_dir():
            raise CommandError(
                f"App '{app_label}' does not have a migrations directory."
            )

        if app_path not in app_dirs:
            app_dirs.append(app_path)

    if missing_labels:
        labels = ", ".join(sorted(missing_labels))
        raise CommandError(f"Unknown app labels for reset: {labels}.")

    return sorted(app_dirs)


def _remove_migration_files(migrations_path: Path) -> None:
    for py_file in migrations_path.glob("*.py"):
        if py_file.name != "__init__.py":
            py_file.unlink(missing_ok=True)
    for pyc_file in migrations_path.glob("*.pyc"):
        pyc_file.unlink(missing_ok=True)


def _confirm_deletion_prompt(
    app_dirs: list[Path],
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> bool:
    listed_dirs = ", ".join(app_dir.name for app_dir in app_dirs)
    out = stdout or sys.stdout
    inp = stdin or sys.stdin
    out.write(f"Type 'yes' to delete migration files for: {listed_dirs}: ")
    out.flush()
    return inp.readline().strip().lower() == "yes"


def _perform_deletion(app_dirs: list[Path]) -> None:
    for app_dir in app_dirs:
        _remove_migration_files(app_dir / "migrations")

    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_MIGRATION_FILES_DELETED,
        event="Migration files deleted after successful database drop.",
        app_dirs=[str(app_dir) for app_dir in app_dirs],
    )


def delete_migrations_and_force_delete_db(
    alias: str = "default",
    *,
    force: bool = False,
    confirmed: bool = False,
    app_labels: list[str],
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> None:
    project_root = _project_root()
    app_dirs = _gather_app_dirs(project_root, app_labels=app_labels)
    if not app_dirs:
        log_event(
            logger,
            log_name=LogName.AUDIT,
            event_code=EventCode.AUDIT_MIGRATION_FILES_DELETED,
            event="No scoped app migration directories found.",
            project_root=str(project_root),
            app_labels=app_labels,
        )
        return

    if not force and not _confirm_deletion_prompt(
        app_dirs,
        stdin=stdin,
        stdout=stdout,
    ):
        log_event(
            logger,
            log_name=LogName.AUDIT,
            event_code=EventCode.AUDIT_MIGRATION_FILES_DELETED,
            event="Migration deletion aborted by user.",
            project_root=str(project_root),
        )
        return

    force_delete_database(alias, confirmed=confirmed)
    _perform_deletion(app_dirs)
