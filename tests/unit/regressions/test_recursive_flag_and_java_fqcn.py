"""Regression tests: --recursive/--no-recursive global-arg classification, Java
exception FQCN stripping in log messages.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# --recursive / --no-recursive must be classified as GLOBAL args
# ---------------------------------------------------------------------------
class TestRecursiveIsGlobal(unittest.TestCase):
    """Both ``--recursive`` and ``--no-recursive`` live on the top-level
    parser's mutually-exclusive group. They must be extracted as global
    arguments, otherwise argparse on the subparser rejects them as
    "unrecognized arguments"."""

    def _extract(self, argv):
        from dblift.cli._command_handlers import _AVAILABLE_COMMANDS
        from dblift.cli._config_helpers import _extract_commands_from_argv

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
        from dblift.cli._config_helpers import _GLOBAL_BOOLEAN_FLAGS

        self.assertIn("--recursive", _GLOBAL_BOOLEAN_FLAGS)
        self.assertIn("--no-recursive", _GLOBAL_BOOLEAN_FLAGS)


# ---------------------------------------------------------------------------
# SQLite export-schema must ignore --db-schema and use "main"
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# DBLiftClient reuses provider across snapshot / export_schema
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# error_with_exception must strip FQCNs beyond com.*
# ---------------------------------------------------------------------------
class TestJavaFqcnStrip(unittest.TestCase):
    def _capture(self, exc):
        from dblift.core.logger.log import AbstractLog

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
# --min-confidence gating
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
