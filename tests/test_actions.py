from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from man_db.db.actions import perform_action
from man_db.db.settings import DatabaseConfig


class DummyStyle:
    @staticmethod
    def SUCCESS(text: str) -> str:
        return text


class DummyStdout:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def write(self, text: str) -> None:
        self.messages.append(text)


class ActionTests(SimpleTestCase):
    def setUp(self) -> None:
        self.stdout = DummyStdout()
        self.style = DummyStyle()
        self.database = DatabaseConfig(
            alias="default",
            engine="django.db.backends.postgresql",
            name="app_db",
            user="app_user",
            password="secret",
            host="db.example",
            port=5432,
        )

    def test_drop_requires_confirmation(self) -> None:
        with self.assertRaisesMessage(
            CommandError,
            "'drop' is destructive. Re-run with --yes to confirm.",
        ):
            perform_action("drop", {"yes": False}, self.stdout, self.style)

    def test_ping_uses_requested_database_alias(self) -> None:
        with patch("man_db.db.actions.server_ping", return_value=True) as server_ping:
            perform_action("ping", {"database": "analytics"}, self.stdout, self.style)

        server_ping.assert_called_once_with("analytics")
        self.assertEqual(self.stdout.messages[-1], "PostgreSQL reachable.")

    def test_reset_passes_force_flag_and_alias(self) -> None:
        with patch(
            "man_db.db.actions.delete_migrations_and_force_delete_db"
        ) as delete_migrations:
            perform_action(
                "reset",
                {"yes": True, "database": "analytics", "apps": ["man_db"]},
                self.stdout,
                self.style,
            )

        delete_migrations.assert_called_once_with(
            "analytics",
            force=True,
            confirmed=True,
            app_labels=["man_db"],
        )
        self.assertEqual(
            self.stdout.messages[-1], "Migrations cleared and database dropped."
        )

    def test_reset_requires_explicit_app_scope(self) -> None:
        with patch(
            "man_db.db.actions.delete_migrations_and_force_delete_db"
        ) as delete_migrations:
            with self.assertRaisesMessage(
                CommandError,
                "'reset' requires --apps or MAN_DB_RESET_APP_ALLOWLIST to scope migration deletion.",
            ):
                perform_action(
                    "reset",
                    {"yes": True, "database": "analytics", "apps": []},
                    self.stdout,
                    self.style,
                )

        delete_migrations.assert_not_called()

    def test_reset_uses_configured_app_allowlist(self) -> None:
        with self.settings(MAN_DB_RESET_APP_ALLOWLIST=["man_db"]):
            with patch(
                "man_db.db.actions.delete_migrations_and_force_delete_db"
            ) as delete_migrations:
                perform_action(
                    "reset",
                    {"yes": True, "database": "analytics", "apps": []},
                    self.stdout,
                    self.style,
                )

        delete_migrations.assert_called_once_with(
            "analytics",
            force=True,
            confirmed=True,
            app_labels=["man_db"],
        )

    def test_drop_passes_confirmed_flag_to_force_delete_database(self) -> None:
        with patch("man_db.db.actions.force_delete_database") as force_delete_database:
            perform_action("drop", {"yes": True}, self.stdout, self.style)

        force_delete_database.assert_called_once_with("default", confirmed=True)
        self.assertEqual(self.stdout.messages[-1], "Database dropped.")

    def test_backup_uses_pgpassfile_instead_of_pgpassword(self) -> None:
        captured_env: dict[str, str] = {}
        captured_content = ""
        pgpass_path: Path | None = None

        def fake_run_subprocess(command: list[str], env: dict[str, str]) -> None:
            nonlocal captured_content, pgpass_path
            captured_env.update(env)
            pgpass_path = Path(env["PGPASSFILE"])
            captured_content = pgpass_path.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "man_db.db.actions.get_database_config",
                    return_value=self.database,
                ),
                patch(
                    "man_db.db.actions.find_executable",
                    return_value="pg_dump",
                ),
                patch(
                    "man_db.db.actions.run_subprocess",
                    side_effect=fake_run_subprocess,
                ),
                patch.dict(os.environ, {"PGPASSWORD": "should-not-leak"}, clear=False),
            ):
                perform_action(
                    "backup",
                    {
                        "database": "default",
                        "output_dir": temp_dir,
                        "prefix": "nightly",
                        "compression": 6,
                        "include_owner": False,
                    },
                    self.stdout,
                    self.style,
                )

        self.assertIn("PGPASSFILE", captured_env)
        self.assertNotIn("PGPASSWORD", captured_env)
        self.assertEqual(
            captured_content,
            "db.example:5432:*:app_user:secret\n",
        )
        if pgpass_path is None:
            self.fail("PGPASSFILE path was not captured.")
        self.assertFalse(pgpass_path.exists())

    def test_restore_uses_pgpassfile_instead_of_pgpassword(self) -> None:
        captured_env: dict[str, str] = {}
        captured_content = ""
        pgpass_path: Path | None = None

        def fake_run_subprocess(command: list[str], env: dict[str, str]) -> None:
            nonlocal captured_content, pgpass_path
            captured_env.update(env)
            pgpass_path = Path(env["PGPASSFILE"])
            captured_content = pgpass_path.read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "app.dump"
            archive_path.write_text("dump")

            with (
                patch(
                    "man_db.db.actions.get_database_config",
                    return_value=self.database,
                ),
                patch(
                    "man_db.db.actions.find_executable",
                    return_value="pg_restore",
                ),
                patch(
                    "man_db.db.actions.run_subprocess",
                    side_effect=fake_run_subprocess,
                ),
                patch.dict(os.environ, {"PGPASSWORD": "should-not-leak"}, clear=False),
            ):
                perform_action(
                    "restore",
                    {
                        "database": "default",
                        "backup": str(archive_path),
                        "jobs": 1,
                        "create_db": False,
                        "include_owner": False,
                        "i_understand": True,
                    },
                    self.stdout,
                    self.style,
                )

        self.assertIn("PGPASSFILE", captured_env)
        self.assertNotIn("PGPASSWORD", captured_env)
        self.assertEqual(
            captured_content,
            "db.example:5432:*:app_user:secret\n",
        )
        if pgpass_path is None:
            self.fail("PGPASSFILE path was not captured.")
        self.assertFalse(pgpass_path.exists())

    def test_restore_requires_acknowledgement(self) -> None:
        with self.assertRaisesMessage(
            CommandError,
            "Refusing to run without --i-understand. This will DROP and recreate objects.",
        ):
            perform_action("restore", {"i_understand": False}, self.stdout, self.style)

    def test_restore_requires_backup_argument(self) -> None:
        with self.assertRaisesMessage(
            CommandError,
            "--backup is required for the restore action.",
        ):
            perform_action(
                "restore",
                {"i_understand": True, "backup": ""},
                self.stdout,
                self.style,
            )

    def test_restore_rejects_zero_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "app.dump"
            archive_path.write_text("dump")

            with (
                patch(
                    "man_db.db.actions.get_database_config",
                    return_value=self.database,
                ),
                patch(
                    "man_db.db.actions.os.cpu_count",
                    return_value=4,
                ),
                patch("man_db.db.actions.find_executable") as find_executable,
                patch("man_db.db.actions.run_subprocess") as run_subprocess,
            ):
                with self.assertRaisesMessage(
                    CommandError,
                    "Restore jobs must be between 1 and 4.",
                ):
                    perform_action(
                        "restore",
                        {
                            "database": "default",
                            "backup": str(archive_path),
                            "jobs": 0,
                            "create_db": False,
                            "include_owner": False,
                            "i_understand": True,
                        },
                        self.stdout,
                        self.style,
                    )

            find_executable.assert_not_called()
            run_subprocess.assert_not_called()

    def test_restore_rejects_jobs_above_cpu_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "app.dump"
            archive_path.write_text("dump")

            with (
                patch(
                    "man_db.db.actions.get_database_config",
                    return_value=self.database,
                ),
                patch(
                    "man_db.db.actions.os.cpu_count",
                    return_value=4,
                ),
                patch("man_db.db.actions.find_executable") as find_executable,
                patch("man_db.db.actions.run_subprocess") as run_subprocess,
            ):
                with self.assertRaisesMessage(
                    CommandError,
                    "Restore jobs must be between 1 and 4.",
                ):
                    perform_action(
                        "restore",
                        {
                            "database": "default",
                            "backup": str(archive_path),
                            "jobs": 5,
                            "create_db": False,
                            "include_owner": False,
                            "i_understand": True,
                        },
                        self.stdout,
                        self.style,
                    )

            find_executable.assert_not_called()
            run_subprocess.assert_not_called()

    def test_backup_keeps_dump_inside_requested_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "man_db.db.actions.get_database_config",
                    return_value=self.database,
                ),
                patch(
                    "man_db.db.actions.find_executable",
                    return_value="pg_dump",
                ),
                patch("man_db.db.actions.run_subprocess") as run_subprocess,
            ):
                perform_action(
                    "backup",
                    {
                        "database": "default",
                        "output_dir": temp_dir,
                        "prefix": "nightly",
                        "compression": 6,
                        "include_owner": False,
                    },
                    self.stdout,
                    self.style,
                )

            run_subprocess.assert_called_once()
            command = run_subprocess.call_args[0][0]
            output_path = Path(command[command.index("-f") + 1])
            self.assertTrue(output_path.is_relative_to(Path(temp_dir).resolve()))
            self.assertTrue(output_path.name.startswith("nightly_"))
            self.assertEqual(
                self.stdout.messages[-1], f"Backup complete: {output_path}"
            )

    def test_backup_rejects_prefix_that_escapes_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "man_db.db.actions.get_database_config",
                    return_value=self.database,
                ),
                patch("man_db.db.actions.find_executable") as find_executable,
                patch("man_db.db.actions.run_subprocess") as run_subprocess,
            ):
                with self.assertRaisesMessage(
                    CommandError,
                    "Backup prefix must be a simple filename component, not a path.",
                ):
                    perform_action(
                        "backup",
                        {
                            "database": "default",
                            "output_dir": temp_dir,
                            "prefix": "../escape",
                            "compression": 6,
                            "include_owner": False,
                        },
                        self.stdout,
                        self.style,
                    )

            find_executable.assert_not_called()
            run_subprocess.assert_not_called()
