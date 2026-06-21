from __future__ import annotations

import os
import platform
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from man_db.db.backup_utils import (
    DEFAULT_TRUSTED_EXECUTABLE_DIRS,
    build_pg_dump_command,
    build_pg_restore_command,
    find_executable,
    pgpass_env,
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
        with tempfile.TemporaryDirectory() as temp_dir:
            output_file = Path(temp_dir) / "app.dump"
            command = build_pg_dump_command(
                pg_dump_executable="pg_dump",
                db=self.database,
                output_file=output_file,
                compression_level=6,
                include_owner_and_privileges=False,
            )

        self.assertIn("--no-owner", command)
        self.assertIn("--no-privileges", command)
        self.assertIn(str(output_file), command)

    def test_build_pg_restore_command_supports_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_file = Path(temp_dir) / "app.dump"
            command = build_pg_restore_command(
                pg_restore_executable="pg_restore",
                db=self.database,
                archive_file=archive_file,
                create_database_first=True,
                parallel_jobs=4,
                include_owner_and_privileges=True,
            )

        self.assertIn("-C", command)
        self.assertEqual(command[-2:], ["postgres", str(archive_file)])
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

    @unittest.skipIf(
        platform.system() == "Windows",
        "POSIX execute bits not applicable on Windows",
    )
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

    @unittest.skipIf(
        platform.system() == "Windows",
        "POSIX execute bits not applicable on Windows",
    )
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

    @unittest.skipIf(
        platform.system() == "Windows",
        "POSIX execute bits not applicable on Windows",
    )
    def test_find_executable_accepts_absolute_executable_env_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "pg_dump"
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

            with patch.dict(os.environ, {"PG_DUMP_PATH": str(executable)}, clear=False):
                resolved = find_executable("PG_DUMP_PATH", "pg_dump")

        self.assertEqual(resolved, str(executable.resolve()))

    @unittest.skipIf(
        platform.system() == "Windows",
        "POSIX execute bits not applicable on Windows",
    )
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

    @unittest.skipIf(
        platform.system() == "Windows",
        "POSIX execute bits not applicable on Windows",
    )
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

    def test_find_executable_accepts_windows_style_executable_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "pg_dump.exe"
            executable.write_bytes(b"")

            with (
                patch(
                    "man_db.db.backup_utils.platform.system",
                    return_value="Windows",
                ),
                patch.dict(
                    os.environ,
                    {
                        "PATHEXT": ".EXE;.CMD;.BAT;.COM",
                        "PG_DUMP_PATH": str(executable),
                    },
                    clear=False,
                ),
            ):
                resolved = find_executable("PG_DUMP_PATH", "pg_dump")

        self.assertEqual(resolved, str(executable.resolve()))

    def test_find_executable_rejects_windows_style_non_executable_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "pg_dump.txt"
            executable.write_bytes(b"")

            with (
                patch(
                    "man_db.db.backup_utils.platform.system",
                    return_value="Windows",
                ),
                patch.dict(
                    os.environ,
                    {
                        "PATHEXT": ".EXE;.CMD;.BAT;.COM",
                        "PG_DUMP_PATH": str(executable),
                    },
                    clear=False,
                ),
            ):
                with self.assertRaisesMessage(
                    CommandError,
                    "PG_DUMP_PATH must point to an executable file.",
                ):
                    find_executable("PG_DUMP_PATH", "pg_dump")

    def test_find_executable_accepts_windows_style_trusted_path_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            executable = Path(temp_dir) / "pg_dump.exe"
            executable.write_bytes(b"")

            with (
                patch(
                    "man_db.db.backup_utils.platform.system",
                    return_value="Windows",
                ),
                self.settings(MAN_DB_TRUSTED_EXECUTABLE_DIRS=[temp_dir]),
                patch.dict(
                    os.environ,
                    {"PATHEXT": ".EXE;.CMD;.BAT;.COM"},
                    clear=False,
                ),
                patch(
                    "man_db.db.backup_utils.shutil.which",
                    return_value=str(executable),
                ),
            ):
                resolved = find_executable("PG_DUMP_PATH", "pg_dump")

        self.assertEqual(resolved, str(executable.resolve()))

    def test_pgpass_env_creates_and_removes_temporary_pgpass_file(self) -> None:
        pgpass_path: Path | None = None

        with pgpass_env(self.database, {"PATH": "/usr/bin"}) as env:
            pgpass_path = Path(env["PGPASSFILE"])
            self.assertTrue(pgpass_path.exists())
            self.assertEqual(
                pgpass_path.read_text(encoding="utf-8"),
                "db.example:5432:*:app_user:secret\n",
            )
            self.assertNotIn("PGPASSWORD", env)

        self.assertIsNotNone(pgpass_path)
        self.assertFalse(pgpass_path.exists())

    def test_pgpass_env_returns_original_env_when_password_missing(self) -> None:
        database = DatabaseConfig(
            alias="default",
            engine="django.db.backends.postgresql",
            name="app_db",
            user="app_user",
            password="",
            host="db.example",
            port=5432,
        )
        base_env = {"PATH": "/usr/bin"}

        with pgpass_env(database, base_env) as env:
            self.assertIs(env, base_env)
            self.assertNotIn("PGPASSFILE", env)

    def test_default_trusted_dirs_include_postgresql_wrapper_path(self) -> None:
        expected_paths: tuple[Path, ...]
        if platform.system() == "Windows":
            expected_paths = (
                Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                Path(r"C:\Program Files\PostgreSQL"),
            )
        else:
            expected_paths = (
                Path("/usr/share/postgresql-common"),
                Path("/usr/local/lib/postgresql"),
                Path("/opt/homebrew/bin"),
                Path("/opt/local/bin"),
            )

        for expected_path in expected_paths:
            with self.subTest(expected_path=expected_path):
                self.assertIn(expected_path, DEFAULT_TRUSTED_EXECUTABLE_DIRS)
