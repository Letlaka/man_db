from __future__ import annotations

from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class CommandTests(SimpleTestCase):
    def test_man_db_command_dispatches_to_action_handler(self) -> None:
        with patch(
            "man_db.management.commands.man_db.perform_action"
        ) as perform_action:
            call_command("man_db", "ping", database="analytics")

        perform_action.assert_called_once()
        action, options, *_ = perform_action.call_args.args
        self.assertEqual(action, "ping")
        self.assertEqual(options["database"], "analytics")

    def test_mandb_alias_uses_same_command(self) -> None:
        with patch(
            "man_db.management.commands.man_db.perform_action"
        ) as perform_action:
            call_command("mandb", "ping")

        perform_action.assert_called_once()
        action, *_ = perform_action.call_args.args
        self.assertEqual(action, "ping")

    def test_reset_command_passes_explicit_app_scope(self) -> None:
        with patch(
            "man_db.management.commands.man_db.perform_action"
        ) as perform_action:
            call_command("man_db", "reset", yes=True, apps=["man_db"])

        perform_action.assert_called_once()
        action, options, *_ = perform_action.call_args.args
        self.assertEqual(action, "reset")
        self.assertEqual(options["apps"], ["man_db"])
