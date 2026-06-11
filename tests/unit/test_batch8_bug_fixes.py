"""Regression tests for the Batch 8 bug fixes (B8-BUG-01..B8-BUG-05).

Grouped by bug number so an intentional behavioral change to any one fix is
easy to locate. Mirrors the conventions of ``test_batch7_bug_fixes.py``.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# B8-BUG-01: --recursive / --no-recursive must be classified as GLOBAL args
# ---------------------------------------------------------------------------
class TestBug01RecursiveIsGlobal(unittest.TestCase):
    """Both ``--recursive`` and ``--no-recursive`` live on the top-level
    parser's mutually-exclusive group. They must be extracted as global
    arguments, otherwise argparse on the subparser rejects them as
    "unrecognized arguments"."""

    def _extract(self, argv):
        from cli._command_handlers import _AVAILABLE_COMMANDS
        from cli._config_helpers import _extract_commands_from_argv

        global_only_args = [
            "--version",
            "--log-dir",
            "--log-format",
            "--log-level",
            "--log-file",
            "--db-url",
            "--db-username",
            "--db-password",
            "--db-schema",
            "--config",
            "--scripts",
            "--dry-run",
            "--recursive",
            "--no-recursive",
        ]
        return _extract_commands_from_argv(argv, _AVAILABLE_COMMANDS, global_only_args)

    def test_recursive_routed_as_global(self) -> None:
        commands, global_args, subcmd_args = self._extract(["--recursive", "migrate"])
        self.assertEqual(commands, ["migrate"])
        self.assertIn("--recursive", global_args)
        self.assertNotIn("--recursive", subcmd_args)

    def test_no_recursive_routed_as_global(self) -> None:
        commands, global_args, subcmd_args = self._extract(["--no-recursive", "info"])
        self.assertEqual(commands, ["info"])
        self.assertIn("--no-recursive", global_args)
        self.assertNotIn("--no-recursive", subcmd_args)

    def test_recursive_does_not_swallow_following_command(self) -> None:
        """--recursive is a boolean flag — it must not consume ``migrate``
        as its value."""
        commands, _, _ = self._extract(["--recursive", "migrate"])
        self.assertEqual(commands, ["migrate"])

    def test_no_recursive_in_global_boolean_flags_set(self) -> None:
        from cli._config_helpers import _GLOBAL_BOOLEAN_FLAGS

        self.assertIn("--recursive", _GLOBAL_BOOLEAN_FLAGS)
        self.assertIn("--no-recursive", _GLOBAL_BOOLEAN_FLAGS)


# ---------------------------------------------------------------------------
# B8-BUG-02: SQLite schema operations must ignore --db-schema and use "main"
# ---------------------------------------------------------------------------


class TestBug04JavaFqcnStrip(unittest.TestCase):
    def _capture(self, exc):
        from core.logger.log import AbstractLog

        captured = []

        class _Probe(AbstractLog):
            def _write_log_event(self, event, console_only=False):
                captured.append((event.level, event.message))

        log = _Probe("test")
        log.error_with_exception("Boom", exc)
        return captured

    def test_postgres_fqcn_stripped(self) -> None:
        captured = self._capture(
            Exception("org.postgresql.util.PSQLException: FATAL: password authentication failed")
        )
        msg = "\n".join(m for _, m in captured)
        self.assertNotIn("org.postgresql.util.PSQLException", msg)
        self.assertIn("FATAL: password authentication failed", msg)

    def test_java_sql_fqcn_stripped(self) -> None:
        captured = self._capture(Exception("java.sql.SQLException: timeout waiting for connection"))
        msg = "\n".join(m for _, m in captured)
        self.assertNotIn("java.sql.SQLException", msg)
        self.assertIn("timeout waiting for connection", msg)

    def test_oracle_fqcn_stripped(self) -> None:
        captured = self._capture(
            Exception("oracle.jdbc.OracleDatabaseException: ORA-12541: TNS:no listener")
        )
        msg = "\n".join(m for _, m in captured)
        self.assertNotIn("oracle.jdbc.OracleDatabaseException", msg)
        self.assertIn("ORA-12541", msg)

    def test_plain_python_exception_unchanged(self) -> None:
        captured = self._capture(ValueError("plain old python error"))
        msg = "\n".join(m for _, m in captured)
        self.assertIn("plain old python error", msg)


# ---------------------------------------------------------------------------
# B8-BUG-05: --min-confidence gating
# ---------------------------------------------------------------------------
