from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django
from django.core.management.base import CommandError
from django.test import SimpleTestCase

django.setup()

from man_db.db.backup_utils import (
    build_pg_dump_command,
    build_pg_restore_command,
    timestamped_filename,
)
from man_db.db.settings import DatabaseConfig


class BackupUtilsTests(SimpleTestCase):
    def setUp(self) -> None:
        self.database = DatabaseConfig(
            alias="default",
            engine="django.db.backends.postgresql",
            name="app_db",
            user="app_user",
            password="secret",
            host="db.example",
            port=5432,
        )

    def test_build_pg_dump_command_omits_owner_flags_by_default(self) -> None:
        command = build_pg_dump_command(
            pg_dump_executable="pg_dump",
            db=self.database,
            output_file=Path("/tmp/app.dump"),
            compression_level=6,
            include_owner_and_privileges=False,
        )

        self.assertIn("--no-owner", command)
        self.assertIn("--no-privileges", command)
        self.assertIn("/tmp/app.dump", command)

    def test_build_pg_restore_command_supports_create_database(self) -> None:
        command = build_pg_restore_command(
            pg_restore_executable="pg_restore",
            db=self.database,
            archive_file=Path("/tmp/app.dump"),
            create_database_first=True,
            parallel_jobs=4,
            include_owner_and_privileges=True,
        )

        self.assertIn("-C", command)
        self.assertEqual(command[-2:], ["postgres", "/tmp/app.dump"])
        self.assertNotIn("--no-owner", command)

    def test_timestamped_filename_uses_prefix_when_provided(self) -> None:
        filename = timestamped_filename("app_db", "nightly", "dump")

        self.assertTrue(filename.startswith("nightly_"))
        self.assertTrue(filename.endswith(".dump"))

    def test_timestamped_filename_rejects_relative_path_prefix(self) -> None:
        with self.assertRaisesMessage(
            CommandError,
            "Backup prefix must be a simple filename component, not a path.",
        ):
            timestamped_filename("app_db", "../nightly", "dump")

    def test_timestamped_filename_rejects_absolute_path_prefix(self) -> None:
        with self.assertRaisesMessage(
            CommandError,
            "Backup prefix must be a simple filename component, not a path.",
        ):
            timestamped_filename("app_db", "/tmp/nightly", "dump")
