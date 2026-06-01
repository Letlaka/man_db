from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django
from django.core.management.base import CommandError
from django.test import SimpleTestCase

django.setup()

from man_db.db.backup_utils import (
    build_pg_dump_command,
    build_pg_restore_command,
    find_executable,
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

    def test_find_executable_rejects_non_executable_env_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "pg_dump"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(stat.S_IRUSR | stat.S_IWUSR)

            with patch.dict(os.environ, {"PG_DUMP_PATH": str(executable)}, clear=False):
                with self.assertRaisesMessage(
                    CommandError,
                    "PG_DUMP_PATH must point to an executable file.",
                ):
                    find_executable("PG_DUMP_PATH", "pg_dump")

    def test_find_executable_rejects_relative_env_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_cwd = Path.cwd()
            os.chdir(temp_dir)
            try:
                executable = Path("pg_dump")
                executable.write_text("#!/bin/sh\nexit 0\n")
                executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

                with patch.dict(os.environ, {"PG_DUMP_PATH": "pg_dump"}, clear=False):
                    with self.assertRaisesMessage(
                        CommandError,
                        "PG_DUMP_PATH must be an absolute path.",
                    ):
                        find_executable("PG_DUMP_PATH", "pg_dump")
            finally:
                os.chdir(original_cwd)

    def test_find_executable_accepts_absolute_executable_env_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "pg_dump"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

            with patch.dict(os.environ, {"PG_DUMP_PATH": str(executable)}, clear=False):
                resolved = find_executable("PG_DUMP_PATH", "pg_dump")

        self.assertEqual(resolved, str(executable.resolve()))

    def test_find_executable_rejects_path_result_outside_trusted_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "pg_dump"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

            with self.settings(MAN_DB_TRUSTED_EXECUTABLE_DIRS=["/usr/bin"]):
                with (
                    patch.dict(os.environ, {}, clear=False),
                    patch(
                        "man_db.db.backup_utils.shutil.which",
                        return_value=str(executable),
                    ),
                ):
                    with self.assertRaisesMessage(
                        CommandError,
                        "Resolved 'pg_dump' is outside trusted executable directories.",
                    ):
                        find_executable("PG_DUMP_PATH", "pg_dump")

    def test_find_executable_accepts_trusted_path_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "pg_dump"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

            with self.settings(MAN_DB_TRUSTED_EXECUTABLE_DIRS=[temp_dir]):
                with (
                    patch.dict(os.environ, {}, clear=False),
                    patch(
                        "man_db.db.backup_utils.shutil.which",
                        return_value=str(executable),
                    ),
                ):
                    resolved = find_executable("PG_DUMP_PATH", "pg_dump")

        self.assertEqual(resolved, str(executable.resolve()))
