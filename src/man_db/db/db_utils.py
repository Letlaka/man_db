from __future__ import annotations

from pathlib import Path

import psycopg
from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import CommandError
from psycopg import sql

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
        event_code=EventCode.SYSTEM_STARTUP,
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
        event_code=EventCode.SYSTEM_STARTUP,
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
        raise

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


def force_delete_database(alias: str = "default") -> None:
    config = get_database_config(alias)
    if not config.name:
        raise CommandError(f"Database alias '{alias}' has an empty NAME setting.")

    dropped = False
    try:
        with _connect_as_admin("postgres", config) as connection:
            if not _database_exists(connection, config.name):
                log_event(
                    logger,
                    log_name=LogName.AUDIT,
                    event_code=EventCode.AUDIT_CONFIG_CHANGED,
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
                dropped = True
            except psycopg.Error:
                _terminate_backends(connection, config.name)
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP DATABASE {}").format(sql.Identifier(config.name))
                    )
                dropped = True
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
        raise

    if dropped:
        log_event(
            logger,
            log_name=LogName.AUDIT,
            event_code=EventCode.AUDIT_CONFIG_CHANGED,
            event="Database dropped.",
            database_alias=alias,
            database_name=config.name,
        )


def _find_project_root_candidate() -> Path:
    current = Path(__file__).resolve()
    for parent in [current, *current.parents]:
        if (parent / "manage.py").exists() or (parent / "settings.py").exists():
            return parent
    return Path.cwd()


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


def _confirm_deletion_prompt(app_dirs: list[Path]) -> bool:
    listed_dirs = ", ".join(app_dir.name for app_dir in app_dirs)
    confirm = input(f"Type 'yes' to delete migration files for: {listed_dirs}: ")
    return confirm.strip().lower() == "yes"


def _perform_deletion(
    project_root: Path, *, force: bool, app_labels: list[str]
) -> bool:
    app_dirs = _gather_app_dirs(project_root, app_labels=app_labels)
    if not app_dirs:
        log_event(
            logger,
            log_name=LogName.AUDIT,
            event_code=EventCode.AUDIT_CONFIG_CHANGED,
            event="No scoped app migration directories found.",
            project_root=str(project_root),
            app_labels=app_labels,
        )
        return False

    if not force and not _confirm_deletion_prompt(app_dirs):
        log_event(
            logger,
            log_name=LogName.AUDIT,
            event_code=EventCode.AUDIT_CONFIG_CHANGED,
            event="Migration deletion aborted by user.",
            project_root=str(project_root),
        )
        return False

    for app_dir in app_dirs:
        _remove_migration_files(app_dir / "migrations")

    log_event(
        logger,
        log_name=LogName.AUDIT,
        event_code=EventCode.AUDIT_CONFIG_CHANGED,
        event="Migration files deleted.",
        app_dirs=[str(app_dir) for app_dir in app_dirs],
    )
    return True


def delete_migrations_and_force_delete_db(
    alias: str = "default",
    *,
    force: bool = False,
    app_labels: list[str],
) -> None:
    project_root = Path(getattr(settings, "BASE_DIR", _find_project_root_candidate()))
    deleted = _perform_deletion(project_root, force=force, app_labels=app_labels)
    if deleted:
        force_delete_database(alias)
