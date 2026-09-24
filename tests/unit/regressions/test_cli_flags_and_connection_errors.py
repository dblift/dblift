"""Regression tests: CLI flag overrides, connection-error classification, schema_name fallback.

Each test keeps its scope local to the surface being changed and avoids
network/database dependencies.
"""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# PG matview composite row-type must not surface as CREATE TYPE
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# --recursive / --no-recursive CLI override
# ---------------------------------------------------------------------------
class TestRecursiveOverride(unittest.TestCase):
    def _make_parser(self) -> argparse.ArgumentParser:
        from dblift.cli._parser_setup import create_parser

        return create_parser()

    def test_parser_exposes_recursive_flags(self) -> None:
        parser = self._make_parser()
        args = parser.parse_args(["--no-recursive", "migrate"])
        self.assertEqual(getattr(args, "recursive_flag", "missing"), False)
        args = parser.parse_args(["--recursive", "migrate"])
        self.assertEqual(getattr(args, "recursive_flag", "missing"), True)
        args = parser.parse_args(["migrate"])
        self.assertIsNone(getattr(args, "recursive_flag", "missing"))

    def test_parser_rejects_both_flags_together(self) -> None:
        parser = self._make_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--recursive", "--no-recursive", "migrate"])

    def test_config_helper_honors_no_recursive(self) -> None:
        from dblift.cli._config_helpers import _resolve_scripts_directories

        args = MagicMock()
        args.command = "migrate"
        args.config = None
        args.scripts_list = [str(Path.cwd())]
        args.recursive_flag = False

        config = MagicMock()
        config.migrations.recursive = True
        config.migrations.directory = ""

        parser = argparse.ArgumentParser()
        _, _, recursive, dir_map = _resolve_scripts_directories(args, config, parser, ["migrate"])
        self.assertFalse(recursive)
        self.assertFalse(config.migrations.recursive)
        # Primary path is flagged as non-recursive in the per-dir map.
        self.assertTrue(any(v is False for v in dir_map.values()))

    def test_config_helper_honors_recursive_flag(self) -> None:
        from dblift.cli._config_helpers import _resolve_scripts_directories

        args = MagicMock()
        args.command = "migrate"
        args.config = None
        args.scripts_list = [str(Path.cwd())]
        args.recursive_flag = True

        config = MagicMock()
        config.migrations.recursive = False
        config.migrations.directory = ""

        parser = argparse.ArgumentParser()
        _, _, recursive, dir_map = _resolve_scripts_directories(args, config, parser, ["migrate"])
        self.assertTrue(recursive)
        self.assertTrue(config.migrations.recursive)
        self.assertTrue(all(v is True for v in dir_map.values()))


# ---------------------------------------------------------------------------
# from_sqlalchemy requires engine= or connection= and raises ConfigurationError
# (not NotImplemented) for a missing engine.
# ---------------------------------------------------------------------------
class TestFromSqlalchemyRaisesConfigurationError(unittest.TestCase):
    def test_from_sqlalchemy_no_args_raises_configuration(self) -> None:
        from dblift.api.client import DBLiftClient
        from dblift.config.errors import ConfigurationError

        with self.assertRaises(ConfigurationError):
            DBLiftClient.from_sqlalchemy()  # type: ignore[call-arg]

    def test_from_sqlalchemy_none_engine_raises_configuration(self) -> None:
        from dblift.api.client import DBLiftClient
        from dblift.config.errors import ConfigurationError

        with self.assertRaises(ConfigurationError):
            DBLiftClient.from_sqlalchemy(None)

    def test_from_sqlalchemy_none_engine_and_migrations_raises_configuration(self) -> None:
        from dblift.api.client import DBLiftClient
        from dblift.config.errors import ConfigurationError

        with self.assertRaises(ConfigurationError):
            DBLiftClient.from_sqlalchemy(None, "/tmp/migrations")


# ---------------------------------------------------------------------------
# clean --dry-run must delegate complete enumeration to provider
# ---------------------------------------------------------------------------
class TestCleanDryRunCoversAllObjectTypes(unittest.TestCase):
    def test_clean_command_uses_provider_droppable_object_contract(self) -> None:
        import dblift.core.migration.commands.clean_command as mod

        src = Path(mod.__file__).read_text()
        self.assertIn("list_droppable_objects", src)
        self.assertNotIn("SchemaIntrospector", src)
        self.assertNotIn("get_materialized_views", src)


# ---------------------------------------------------------------------------
# SQL Server indexed view must emit CREATE VIEW, not MATERIALIZED
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# schema_name must mirror target_schema when not explicitly set
# ---------------------------------------------------------------------------
class TestSchemaNameMirrorsTargetSchema(unittest.TestCase):
    def test_info_result_schema_name_falls_back_to_target_schema(self) -> None:
        from dblift.core.logger.results import InfoResult

        result = InfoResult()
        result.target_schema = "dblift_test"
        self.assertEqual(result.schema_name, "dblift_test")

    def test_baseline_repair_undo_result_schema_name_fallback(self) -> None:
        from dblift.core.logger.results import BaselineResult, RepairResult, UndoResult

        for cls in (BaselineResult, RepairResult, UndoResult):
            result = cls()
            result.target_schema = "app"
            self.assertEqual(
                result.schema_name,
                "app",
                msg=f"{cls.__name__}.schema_name did not fall back to target_schema",
            )

    def test_explicit_schema_name_overrides_target_schema(self) -> None:
        from dblift.core.logger.results import CleanResult

        result = CleanResult()
        result.target_schema = "target"
        result.schema_name = "override"
        self.assertEqual(result.schema_name, "override")

    def test_empty_result_still_reads_empty(self) -> None:
        from dblift.core.logger.results import InfoResult

        result = InfoResult()
        self.assertEqual(result.schema_name, "")


# ---------------------------------------------------------------------------
# connection error classifier must use SQLState, not locale text
# ---------------------------------------------------------------------------
class TestConnectionErrorUsesSqlState(unittest.TestCase):
    def _make_jdbc_error(self, sqlstate: str, message: str) -> Exception:
        exc: Any = Exception(message)
        exc.getSQLState = MagicMock(return_value=sqlstate)  # type: ignore[attr-defined]
        return exc

    def test_french_locale_08006_returns_english_host_unreachable(self) -> None:
        from dblift.cli.db_utils import _format_connection_error

        msg = "org.postgresql.util.PSQLException: La tentative de connexion a échoué."
        err = self._make_jdbc_error("08006", msg)
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: host unreachable or connection timed out")

    def test_auth_sqlstate_28p01_returns_invalid_credentials(self) -> None:
        from dblift.cli.db_utils import _format_connection_error

        err = self._make_jdbc_error("28P01", "Le mot de passe est invalide.")
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: invalid credentials")

    def test_sqlserver_08001_login_failure_returns_invalid_credentials(self) -> None:
        from dblift.cli.db_utils import _format_connection_error

        err = self._make_jdbc_error(
            "08001",
            "com.microsoft.sqlserver.jdbc.SQLServerException: "
            "Login failed for user 'dblift_test'. ClientConnectionId: abc",
        )
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: invalid credentials")

    def test_invalid_database_sqlstate_3d000_returns_database_not_found(self) -> None:
        from dblift.cli.db_utils import _format_connection_error

        err = self._make_jdbc_error("3D000", "Base de données introuvable.")
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: database not found or connection rejected")

    def test_english_substring_fallback_still_works(self) -> None:
        """Non-JDBC exceptions still go through the substring classifier."""
        from dblift.cli.db_utils import _format_connection_error

        out = _format_connection_error(Exception("java.net.ConnectException: Connection refused"))
        self.assertEqual(out, "Connection failed: host unreachable")

    def test_unknown_sqlstate_falls_back_to_substring(self) -> None:
        from dblift.cli.db_utils import _format_connection_error

        err = self._make_jdbc_error("99999", "Connection refused")
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: host unreachable")


if __name__ == "__main__":
    unittest.main()
