"""Regression tests for the Batch 5 bug fixes (B5-BUG-01..B5-BUG-07).

Each test keeps its scope local to the surface being changed and avoids
network/database dependencies. They are grouped by bug number so that an
intentional behavioral change to any one fix is easy to locate.
"""

from __future__ import annotations

import argparse
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# B5-BUG-01: PG matview composite row-type must not surface as CREATE TYPE
# ---------------------------------------------------------------------------
class TestBug01PgMatviewCompositeFiltered(unittest.TestCase):
    def test_user_defined_types_query_excludes_relation_composites(self) -> None:
        from db.plugins.postgresql.introspection.postgresql_queries import (
            PostgreSQLMetadataQueries,
        )

        sql, _ = PostgreSQLMetadataQueries().get_user_defined_types_query("public")
        # Only standalone composite types have relkind='c' in pg_class.
        # Table/view/matview implicit row types have relkind='r'/'v'/'m' and
        # must be excluded to avoid duplicate DDL on re-import.
        self.assertIn("t.typtype <> 'c' OR c.relkind = 'c'", sql)


# ---------------------------------------------------------------------------
# B5-BUG-02: --recursive / --no-recursive CLI override
# ---------------------------------------------------------------------------
class TestBug02RecursiveOverride(unittest.TestCase):
    def _make_parser(self) -> argparse.ArgumentParser:
        from cli._parser_setup import create_parser

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
        from cli._config_helpers import _resolve_scripts_directories

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
        from cli._config_helpers import _resolve_scripts_directories

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
# B5-BUG-03 (updated for python-native restore): from_sqlalchemy now requires
# engine= or connection= and raises ConfigurationError (not NotImplemented)
# for missing engine. The original "BUG-03" was that the stub raised TypeError
# for some call shapes before the NotImpl message; we keep the test class to
# guard the new error surface.
# ---------------------------------------------------------------------------
class TestBug03FromSqlalchemyRaisesConfigurationError(unittest.TestCase):
    def test_from_sqlalchemy_no_args_raises_configuration(self) -> None:
        from api.client import DBLiftClient
        from config.errors import ConfigurationError

        with self.assertRaises(ConfigurationError):
            DBLiftClient.from_sqlalchemy()  # type: ignore[call-arg]

    def test_from_sqlalchemy_none_engine_raises_configuration(self) -> None:
        from api.client import DBLiftClient
        from config.errors import ConfigurationError

        with self.assertRaises(ConfigurationError):
            DBLiftClient.from_sqlalchemy(None)

    def test_from_sqlalchemy_none_engine_and_migrations_raises_configuration(self) -> None:
        from api.client import DBLiftClient
        from config.errors import ConfigurationError

        with self.assertRaises(ConfigurationError):
            DBLiftClient.from_sqlalchemy(None, "/tmp/migrations")


# ---------------------------------------------------------------------------
# B5-BUG-04: clean --dry-run must enumerate matviews + program objects
# ---------------------------------------------------------------------------
class TestBug04CleanDryRunCoversAllObjectTypes(unittest.TestCase):
    def test_clean_command_fallback_iterates_extra_getters(self) -> None:
        import core.migration.commands.clean_command as mod

        src = Path(mod.__file__).read_text()
        # The Oracle-shaped gap was matview, procedure, package, synonym. All
        # four getters must be driven by the fallback loop now.
        for getter in (
            "get_materialized_views",
            "get_procedures",
            "get_packages",
            "get_synonyms",
        ):
            self.assertIn(getter, src, f"missing fallback call to {getter}")
        # And the user-facing labels exist so the dry-run output is readable.
        for label in (
            "Would drop materialized view:",
            "Would drop procedure:",
            "Would drop package:",
            "Would drop synonym:",
        ):
            self.assertIn(label, src, f"missing dry-run label {label!r}")


# ---------------------------------------------------------------------------
# B5-BUG-05: SQL Server indexed view must emit CREATE VIEW, not MATERIALIZED
# ---------------------------------------------------------------------------
class TestBug05SqlServerIndexedViewEmitsCreateView(unittest.TestCase):
    def test_indexed_view_statement_uses_view_keyword_with_schemabinding(self) -> None:
        from core.sql_model.view import View
        from db.plugins.sqlserver.generator.ddl_generator import SQLServerSqlGenerator

        view = View(
            name="v_dept_employee_count",
            schema="dblift_test",
            query=(
                "SELECT dept_id, COUNT_BIG(*) AS emp_count "
                "FROM dblift_test.employees GROUP BY dept_id"
            ),
            materialized=True,
            dialect="sqlserver",
        )
        view.clustered_index_name = "idx_v_dept_emp"  # type: ignore[attr-defined]
        view.clustered_index_columns = ["dept_id"]  # type: ignore[attr-defined]

        stmt = SQLServerSqlGenerator().generate_ddl([view], target_dialect="sqlserver")
        # The previous output was "CREATE MATERIALIZED VIEW ..." (invalid TSQL).
        self.assertNotIn("MATERIALIZED VIEW", stmt)
        self.assertIn("CREATE VIEW", stmt)
        self.assertIn("WITH SCHEMABINDING", stmt)
        self.assertIn("CREATE UNIQUE CLUSTERED INDEX", stmt)
        self.assertIn("idx_v_dept_emp", stmt)
        self.assertIn("GO", stmt)

    def test_non_indexed_view_still_emits_create_view(self) -> None:
        from core.sql_model.view import View
        from db.plugins.sqlserver.generator.ddl_generator import SQLServerSqlGenerator

        view = View(
            name="v_high_earners",
            schema="dblift_test",
            query="SELECT * FROM employees WHERE salary > 100000",
            materialized=False,
            dialect="sqlserver",
        )
        stmt = SQLServerSqlGenerator()._generate_view_create_statement(view)
        self.assertIn("CREATE VIEW", stmt)
        self.assertNotIn("MATERIALIZED VIEW", stmt)
        self.assertNotIn("WITH SCHEMABINDING", stmt)


# ---------------------------------------------------------------------------
# B5-BUG-06: schema_name must mirror target_schema when not explicitly set
# ---------------------------------------------------------------------------
class TestBug06SchemaNameMirrorsTargetSchema(unittest.TestCase):
    def test_info_result_schema_name_falls_back_to_target_schema(self) -> None:
        from core.logger.results import InfoResult

        result = InfoResult()
        result.target_schema = "dblift_test"
        self.assertEqual(result.schema_name, "dblift_test")

    def test_baseline_repair_undo_result_schema_name_fallback(self) -> None:
        from core.logger.results import BaselineResult, RepairResult, UndoResult

        for cls in (BaselineResult, RepairResult, UndoResult):
            result = cls()
            result.target_schema = "app"
            self.assertEqual(
                result.schema_name,
                "app",
                msg=f"{cls.__name__}.schema_name did not fall back to target_schema",
            )

    def test_explicit_schema_name_overrides_target_schema(self) -> None:
        from core.logger.results import CleanResult

        result = CleanResult()
        result.target_schema = "target"
        result.schema_name = "override"
        self.assertEqual(result.schema_name, "override")

    def test_empty_result_still_reads_empty(self) -> None:
        from core.logger.results import InfoResult

        result = InfoResult()
        self.assertEqual(result.schema_name, "")


# ---------------------------------------------------------------------------
# B5-BUG-07: connection error classifier must use SQLState, not locale text
# ---------------------------------------------------------------------------
class TestBug07ConnectionErrorUsesSqlState(unittest.TestCase):
    def _make_jdbc_error(self, sqlstate: str, message: str) -> Exception:
        exc: Any = Exception(message)
        exc.getSQLState = MagicMock(return_value=sqlstate)  # type: ignore[attr-defined]
        return exc

    def test_french_locale_08006_returns_english_host_unreachable(self) -> None:
        from cli.db_utils import _format_connection_error

        msg = "org.postgresql.util.PSQLException: La tentative de connexion a échoué."
        err = self._make_jdbc_error("08006", msg)
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: host unreachable or connection timed out")

    def test_auth_sqlstate_28p01_returns_invalid_credentials(self) -> None:
        from cli.db_utils import _format_connection_error

        err = self._make_jdbc_error("28P01", "Le mot de passe est invalide.")
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: invalid credentials")

    def test_sqlserver_08001_login_failure_returns_invalid_credentials(self) -> None:
        from cli.db_utils import _format_connection_error

        err = self._make_jdbc_error(
            "08001",
            "com.microsoft.sqlserver.jdbc.SQLServerException: "
            "Login failed for user 'dblift_test'. ClientConnectionId: abc",
        )
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: invalid credentials")

    def test_invalid_database_sqlstate_3d000_returns_database_not_found(self) -> None:
        from cli.db_utils import _format_connection_error

        err = self._make_jdbc_error("3D000", "Base de données introuvable.")
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: database not found or connection rejected")

    def test_english_substring_fallback_still_works(self) -> None:
        """Non-JDBC exceptions still go through the substring classifier."""
        from cli.db_utils import _format_connection_error

        out = _format_connection_error(Exception("java.net.ConnectException: Connection refused"))
        self.assertEqual(out, "Connection failed: host unreachable")

    def test_unknown_sqlstate_falls_back_to_substring(self) -> None:
        from cli.db_utils import _format_connection_error

        err = self._make_jdbc_error("99999", "Connection refused")
        out = _format_connection_error(err)
        self.assertEqual(out, "Connection failed: host unreachable")


if __name__ == "__main__":
    unittest.main()
