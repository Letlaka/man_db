from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING, Any, cast

import structlog
from django.core.management.base import BaseCommand

from man_db.config import get_backup_output_dir
from man_db.db.actions import perform_action

if TYPE_CHECKING:
    from argparse import ArgumentParser

    from man_db.db.actions import StdoutProtocol, StyleProtocol


class Command(BaseCommand):
    help = (
        "Manage your Postgres DB and backups:\n"
        "  create  -> make the DB;\n"
        "  drop    -> terminate and drop the DB;\n"
        "  reset   -> delete local migrations and drop the DB;\n"
        "  ping    -> check Postgres is reachable;\n"
        "  backup  -> create a pg_dump backup;\n"
        "  restore -> restore a pg_dump backup (destructive)"
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "action",
            choices=["create", "drop", "reset", "ping", "backup", "restore"],
            help="create | drop | reset | ping | backup | restore",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="confirm destructive actions (drop, reset)",
        )
        parser.add_argument(
            "--apps",
            nargs="+",
            help="App labels whose migrations may be deleted during reset.",
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Django database alias to use.",
        )
        parser.add_argument(
            "--output-dir",
            default=str(get_backup_output_dir()),
            help="Directory to write the backup file.",
        )
        parser.add_argument(
            "--prefix",
            default="",
            help="Optional filename prefix.",
        )
        parser.add_argument(
            "--compression",
            type=int,
            default=6,
            help="Compression level 0-9 for pg_dump custom format (default: 6).",
        )
        parser.add_argument(
            "--include-owner",
            action="store_true",
            help="Include original object owners and privileges in dump or restore.",
        )
        parser.add_argument(
            "--backup",
            help="Path to the .dump archive to restore.",
        )
        parser.add_argument(
            "--create-db",
            action="store_true",
            help="Create the database from the backup (-C) before restoring.",
        )
        parser.add_argument(
            "--jobs",
            type=int,
            default=2,
            help="Number of parallel jobs for pg_restore (default: 2).",
        )
        parser.add_argument(
            "--i-understand",
            action="store_true",
            help="Acknowledge that restore will DROP and recreate objects.",
        )

    def handle(self, **options: object) -> None:
        action = str(options["action"])
        with contextlib.suppress(Exception):
            structlog.contextvars.bind_contextvars(trace_id=uuid.uuid4().hex)

        perform_action(
            action,
            cast("dict[str, Any]", options),
            cast("StdoutProtocol", self.stdout),
            cast("StyleProtocol", self.style),
        )
