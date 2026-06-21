from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest
from django.test import SimpleTestCase, override_settings

from man_db.db.actions import perform_action
from man_db.db.backup_utils import find_executable
from man_db.db.db_utils import create_database, force_delete_database

pytestmark = pytest.mark.integration


def _integration_database_settings() -> dict[str, dict[str, object]]:
    return {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "man_db_integration_test",
            "USER": os.environ.get("DB_USER", "test_user"),
            "PASSWORD": os.environ.get("DB_PASSWORD", "test_password"),
            "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
            "PORT": int(os.environ.get("DB_PORT", 5432)),
        }
    }


class DummyStyle:
    @staticmethod
    def SUCCESS(text: str) -> str:
        return text


class DummyStdout:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def write(self, text: str) -> None:
        self.messages.append(text)


@override_settings(DATABASES=_integration_database_settings())
class IntegrationTests(SimpleTestCase):
    def setUp(self) -> None:
        self.stdout = DummyStdout()
        self.style = DummyStyle()

    def tearDown(self) -> None:
        force_delete_database("default", confirmed=True)

    def _database_details(self) -> tuple[str, str, str, str, int]:
        database_settings = _integration_database_settings()["default"]
        return (
            str(database_settings["NAME"]),
            str(database_settings["USER"]),
            str(database_settings["PASSWORD"]),
            str(database_settings["HOST"]),
            int(str(database_settings["PORT"])),
        )

    def _connect_to_managed_database(self) -> psycopg.Connection:
        (
            database_name,
            database_user,
            database_password,
            database_host,
            database_port,
        ) = self._database_details()
        return psycopg.connect(
            dbname=database_name,
            user=database_user,
            password=database_password,
            host=database_host,
            port=database_port,
            connect_timeout=10,
        )

    def test_ping_returns_true_for_reachable_server(self) -> None:
        from man_db.db.db_utils import server_ping

        self.assertTrue(server_ping("default"))

    def test_expected_server_and_client_major_versions(self) -> None:
        expected_value = os.environ.get("POSTGRES_VERSION")
        if expected_value is None:
            self.skipTest("POSTGRES_VERSION is only required for version-matrix runs.")
        expected_major = int(expected_value)

        create_database("default")
        with self._connect_to_managed_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SHOW server_version_num;")
                row = cursor.fetchone()

        if row is None:
            self.fail("Expected PostgreSQL to return server_version_num.")
        server_major = int(str(row[0])) // 10_000
        self.assertEqual(server_major, expected_major)

        executables = (
            find_executable("PG_DUMP_PATH", "pg_dump"),
            find_executable("PG_RESTORE_PATH", "pg_restore"),
        )
        for executable in executables:
            with self.subTest(executable=executable):
                result = subprocess.run(
                    [executable, "--version"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                match = re.search(r"PostgreSQL\) (\d+)", result.stdout)
                self.assertIsNotNone(match, result.stdout)
                assert match is not None
                self.assertEqual(int(match.group(1)), expected_major)

    def test_create_and_drop_database_roundtrip(self) -> None:
        create_database("default")
        force_delete_database("default", confirmed=True)
        create_database("default")

        with self._connect_to_managed_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                row = cursor.fetchone()

        self.assertEqual(row, (1,))

    def test_create_is_idempotent(self) -> None:
        create_database("default")
        create_database("default")

        with self._connect_to_managed_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database();")
                row = cursor.fetchone()

        if row is None:
            self.fail("Expected current_database() to return a row.")
        self.assertEqual(row[0], self._database_details()[0])

    def test_backup_and_restore_round_trip_with_pgpass(self) -> None:
        (
            database_name,
            _database_user,
            _database_password,
            _database_host,
            _database_port,
        ) = self._database_details()

        create_database("default")
        with self._connect_to_managed_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "CREATE TABLE integration_sample (id integer primary key, value text not null);"
                )
                cursor.execute(
                    "INSERT INTO integration_sample (id, value) VALUES (1, 'ok');"
                )
            connection.commit()

        with tempfile.TemporaryDirectory() as temp_dir:
            perform_action(
                "backup",
                {
                    "database": "default",
                    "output_dir": temp_dir,
                    "prefix": "integration",
                    "compression": 0,
                    "include_owner": False,
                },
                self.stdout,
                self.style,
            )
            backup_path = Path(
                self.stdout.messages[-1].removeprefix("Backup complete: ")
            )
            self.assertTrue(backup_path.exists())

            force_delete_database("default", confirmed=True)
            perform_action(
                "restore",
                {
                    "database": "default",
                    "backup": str(backup_path),
                    "jobs": 1,
                    "create_db": True,
                    "include_owner": False,
                    "i_understand": True,
                },
                    self.stdout,
                    self.style,
                )

        with self._connect_to_managed_database() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT value FROM integration_sample WHERE id = 1;")
                row = cursor.fetchone()

        self.assertEqual(row, ("ok",))
