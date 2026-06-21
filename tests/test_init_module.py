from __future__ import annotations

import importlib
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

import man_db


class InitModuleTests(SimpleTestCase):
    def test_import_logs_debug_when_structlog_binding_fails(self) -> None:
        mock_logger = Mock()

        try:
            with (
                patch(
                    "structlog.contextvars.bind_contextvars",
                    side_effect=RuntimeError("boom"),
                ),
                patch("logging.getLogger", return_value=mock_logger),
            ):
                importlib.reload(man_db)
        finally:
            importlib.reload(man_db)

        mock_logger.debug.assert_called_once_with(
            "structlog context binding unavailable at import time",
            exc_info=True,
        )
