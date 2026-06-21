from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import psycopg
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from man_db.db.db_utils import (
    _confirm_deletion_prompt,
    _project_root,
    create_database,
    delete_migrations_and_force_delete_db,
    force_delete_database,
)
from man_db.db.settings import DatabaseConfig


class DbUtilsTests(SimpleTestCase):
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

    def test_force_delete_database_requires_confirmation(self) -> None:
        with patch("man_db.db.db_utils.get_database_config") as get_database_config:
            with self.assertRaisesMessage(
                RuntimeError,
                "force_delete_database() requires confirmed=True. "
                "This operation is irreversible and cannot be undone.",
            ):
                force_delete_database("default")

        get_database_config.assert_not_called()

    def test_create_database_wraps_psycopg_error_as_command_error(self) -> None:
        with (
            patch(
                "man_db.db.db_utils.get_database_config",
                return_value=self.database,
            ),
            patch(
                "man_db.db.db_utils._connect_as_admin",
                side_effect=psycopg.OperationalError("connection refused"),
            ),
        ):
            with self.assertRaisesMessage(
                CommandError,
                "Failed to create database 'app_db': connection refused",
            ):
                create_database("default")

    def test_force_delete_database_wraps_psycopg_error_as_command_error(self) -> None:
        with (
            patch(
                "man_db.db.db_utils.get_database_config",
                return_value=self.database,
            ),
            patch(
                "man_db.db.db_utils._connect_as_admin",
                side_effect=psycopg.OperationalError("connection refused"),
            ),
        ):
            with self.assertRaisesMessage(
                CommandError,
                "Failed to drop database 'app_db': connection refused",
            ):
                force_delete_database("default", confirmed=True)

    def test_project_root_requires_base_dir(self) -> None:
        with self.settings(BASE_DIR=None):
            with self.assertRaisesMessage(
                ImproperlyConfigured,
                "man_db requires settings.BASE_DIR to be configured.",
            ):
                _project_root()

    def test_confirm_deletion_prompt_accepts_yes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "myapp"
            app_dir.mkdir()

            result = _confirm_deletion_prompt(
                [app_dir],
                stdin=io.StringIO("yes\n"),
                stdout=io.StringIO(),
            )

        self.assertTrue(result)

    def test_confirm_deletion_prompt_writes_prompt_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "myapp"
            app_dir.mkdir()
            output = io.StringIO()

            _confirm_deletion_prompt(
                [app_dir],
                stdin=io.StringIO("yes\n"),
                stdout=output,
            )

        self.assertIn("myapp", output.getvalue())

    def test_confirm_deletion_prompt_rejects_non_yes_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "myapp"
            app_dir.mkdir()

            for answer in ["no", "y", "", " "]:
                with self.subTest(answer=answer):
                    result = _confirm_deletion_prompt(
                        [app_dir],
                        stdin=io.StringIO(f"{answer}\n"),
                        stdout=io.StringIO(),
                    )
                    self.assertFalse(result)

    def test_confirm_deletion_prompt_accepts_case_insensitive_yes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir) / "myapp"
            app_dir.mkdir()

            result = _confirm_deletion_prompt(
                [app_dir],
                stdin=io.StringIO("YES\n"),
                stdout=io.StringIO(),
            )

        self.assertTrue(result)

    def test_delete_migrations_passes_confirmation_to_force_delete_database(self) -> None:
        app_dirs = [Path("/fake/app")]
        call_order: list[str] = []

        with (
            patch("man_db.db.db_utils._project_root", return_value=Path("/project")),
            patch("man_db.db.db_utils._gather_app_dirs", return_value=app_dirs),
            patch(
                "man_db.db.db_utils.force_delete_database",
                side_effect=lambda alias, confirmed: call_order.append("drop"),
            ) as force_delete,
            patch(
                "man_db.db.db_utils._perform_deletion",
                side_effect=lambda dirs: call_order.append("delete"),
            ) as perform_deletion,
        ):
            delete_migrations_and_force_delete_db(
                "analytics",
                force=True,
                confirmed=True,
                app_labels=["man_db"],
            )

        force_delete.assert_called_once_with("analytics", confirmed=True)
        perform_deletion.assert_called_once_with(app_dirs)
        self.assertEqual(call_order, ["drop", "delete"])

    def test_reset_does_not_delete_files_if_db_drop_fails(self) -> None:
        app_dirs = [Path("/fake/app")]

        with (
            patch("man_db.db.db_utils._project_root", return_value=Path("/project")),
            patch("man_db.db.db_utils._gather_app_dirs", return_value=app_dirs),
            patch(
                "man_db.db.db_utils.force_delete_database",
                side_effect=CommandError("drop failed"),
            ),
            patch("man_db.db.db_utils._perform_deletion") as perform_deletion,
        ):
            with self.assertRaisesMessage(CommandError, "drop failed"):
                delete_migrations_and_force_delete_db(
                    "default",
                    force=True,
                    confirmed=True,
                    app_labels=["myapp"],
                )

        perform_deletion.assert_not_called()
