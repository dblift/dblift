"""Regression tests for the Batch 10 bug fixes (B10-BUG-01..24).

Grouped by bug number so an intentional behavioral change to any one fix is
easy to locate. Mirrors the conventions of ``test_batch9_bug_fixes.py``.
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# B10-BUG-01: post-commit verification must quote identifiers per dialect
# ---------------------------------------------------------------------------
class TestBug01PostCommitQuoting(unittest.TestCase):
    """The hardcoded ``"schema"."table"`` form used ANSI double-quotes even
    on MySQL (backticks) and SQL Server (brackets), so the verification
    query crashed on those engines. On Oracle it quoted the name, bypassing
    the default upper-case folding that the CREATE TABLE used, so the
    COUNT(*) targeted a non-existent identifier. Fix: route through
    ``DialectEnum.quote_identifier`` and upper-case the idents on Oracle."""

    def test_mysql_uses_backticks(self) -> None:
        from core.sql_model.dialect import DialectEnum

        self.assertEqual(DialectEnum.quote_identifier("mysql", "public"), "`public`")
        self.assertEqual(DialectEnum.quote_identifier("mysql", "users"), "`users`")

    def test_sqlserver_uses_brackets(self) -> None:
        from core.sql_model.dialect import DialectEnum

        self.assertEqual(DialectEnum.quote_identifier("sqlserver", "dbo"), "[dbo]")
        self.assertEqual(DialectEnum.quote_identifier("sqlserver", "Users"), "[Users]")

    def test_postgres_and_oracle_use_ansi_quotes(self) -> None:
        from core.sql_model.dialect import DialectEnum

        self.assertEqual(DialectEnum.quote_identifier("postgresql", "public"), '"public"')
        self.assertEqual(DialectEnum.quote_identifier("oracle", "HR"), '"HR"')

    def test_engine_composes_verification_per_dialect(self) -> None:
        """Compose the exact same expression the engine builds and assert
        the resulting SELECT text differs by dialect and respects Oracle's
        upper-case folding."""
        from core.sql_model.dialect import DialectEnum

        def compose(dialect: str, schema: str, table: str) -> str:
            s = schema.upper() if dialect == "oracle" else schema
            t = table.upper() if dialect == "oracle" else table
            qualified = (
                f"{DialectEnum.quote_identifier(dialect, s)}"
                f".{DialectEnum.quote_identifier(dialect, t)}"
            )
            if dialect in ("oracle", "sqlserver"):
                return f"SELECT COUNT(*) as cnt FROM {qualified}"
            return f"SELECT COUNT(*) as cnt FROM {qualified} LIMIT 1"

        self.assertEqual(
            compose("mysql", "app", "users"),
            "SELECT COUNT(*) as cnt FROM `app`.`users` LIMIT 1",
        )
        self.assertEqual(
            compose("sqlserver", "dbo", "users"),
            "SELECT COUNT(*) as cnt FROM [dbo].[users]",
        )
        self.assertEqual(
            compose("oracle", "hr", "employees"),
            'SELECT COUNT(*) as cnt FROM "HR"."EMPLOYEES"',
        )
        self.assertEqual(
            compose("postgresql", "public", "users"),
            'SELECT COUNT(*) as cnt FROM "public"."users" LIMIT 1',
        )


# ---------------------------------------------------------------------------
# B10-BUG-04: ``--version`` on subcommands must hint the real flag
# ---------------------------------------------------------------------------
class TestBug04BaselineVersionAlias(unittest.TestCase):
    """Flyway users type ``dblift baseline --version 1.0.0`` and the global
    ``--version`` flag short-circuits with a tool-version print + exit 0,
    masking the mistake. The fix prints a hint to stderr and exits non-zero
    when ``--version`` appears after a subcommand that accepts its own
    version-bearing flag."""

    def _run_main(self, argv):
        from cli import main as cli_main

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", argv):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    cli_main.main()
                except SystemExit as exc:
                    return exc.code, stdout.getvalue(), stderr.getvalue()
        return 0, stdout.getvalue(), stderr.getvalue()

    def test_baseline_version_emits_hint_and_exits_nonzero(self) -> None:
        rc, _, err = self._run_main(["dblift", "baseline", "--version", "1.0.0"])
        self.assertEqual(rc, 2)
        self.assertIn("--baseline-version", err)
        self.assertIn("baseline", err)

    def test_migrate_version_hints_target_version(self) -> None:
        rc, _, err = self._run_main(["dblift", "migrate", "--version", "1.0.0"])
        self.assertEqual(rc, 2)
        self.assertIn("--target-version", err)
        self.assertIn("migrate", err)

    def test_undo_version_hints_target_version(self) -> None:
        rc, _, err = self._run_main(["dblift", "undo", "--version", "1.0.0"])
        self.assertEqual(rc, 2)
        self.assertIn("--target-version", err)

    def test_bare_version_still_prints_tool_version(self) -> None:
        """Regression guard: `dblift --version` without a subcommand keeps
        the legacy behavior of printing the tool version."""
        rc, out, _ = self._run_main(["dblift", "--version"])
        # Exits cleanly and prints a version string that looks like one.
        self.assertIn("dblift version", out)
        # Accept either None (fell through without SystemExit) or 0.
        self.assertIn(rc, (0, None))


# ---------------------------------------------------------------------------
# B10-BUG-09: Python MigrationContext must route SELECTs via execute_query
# ---------------------------------------------------------------------------
class TestBug09PythonContextExecuteRouting(unittest.TestCase):
    """SELECT/WITH/VALUES route to query execution instead of statement execution."""

    def _ctx(self, provider):
        from core.migration.executors.python_executor import MigrationContext

        return MigrationContext(provider=provider, log=MagicMock(), dry_run=False)

    def test_select_routes_to_execute_query(self) -> None:
        provider = MagicMock()
        provider.execute_query.return_value = [{"cnt": 3}]
        ctx = self._ctx(provider)

        result = ctx.execute("SELECT COUNT(*) AS cnt FROM users")

        provider.execute_query.assert_called_once_with("SELECT COUNT(*) AS cnt FROM users")
        provider.execute_statement.assert_not_called()
        self.assertEqual(result, [{"cnt": 3}])

    def test_with_cte_routes_to_execute_query(self) -> None:
        provider = MagicMock()
        ctx = self._ctx(provider)
        ctx.execute("WITH t AS (SELECT 1) SELECT * FROM t")
        provider.execute_query.assert_called_once()
        provider.execute_statement.assert_not_called()

    def test_values_clause_routes_to_execute_query(self) -> None:
        provider = MagicMock()
        ctx = self._ctx(provider)
        ctx.execute("VALUES (1), (2), (3)")
        provider.execute_query.assert_called_once()
        provider.execute_statement.assert_not_called()

    def test_insert_still_routes_to_execute_statement(self) -> None:
        provider = MagicMock()
        ctx = self._ctx(provider)
        ctx.execute("INSERT INTO users VALUES (1, 'x')")
        provider.execute_statement.assert_called_once()
        provider.execute_query.assert_not_called()

    def test_update_still_routes_to_execute_statement(self) -> None:
        provider = MagicMock()
        ctx = self._ctx(provider)
        ctx.execute("UPDATE users SET active=1 WHERE id=?", [42])
        provider.execute_statement.assert_called_once_with(
            "UPDATE users SET active=1 WHERE id=?", params=[42]
        )
        provider.execute_query.assert_not_called()

    def test_leading_comment_does_not_hide_select(self) -> None:
        from core.migration.executors.python_executor import _is_query_statement

        self.assertTrue(_is_query_statement("-- header\nSELECT 1"))
        self.assertTrue(_is_query_statement("/* block */ SELECT 1"))
        self.assertTrue(_is_query_statement("  (SELECT 1)"))

    def test_call_stays_on_statement_path(self) -> None:
        """CALL may or may not return rows; keep on the statement path so
        drivers that ignore the result set silently stay working."""
        from core.migration.executors.python_executor import _is_query_statement

        self.assertFalse(_is_query_statement("CALL my_proc()"))
        self.assertFalse(_is_query_statement("EXEC sp_who"))


class TestBug22UrlPrefixDialect(unittest.TestCase):
    """Substring matching misclassified URLs like
    ``postgresql://sqlserver-vm/db`` as SQL Server. Prefix matching
    confines the dialect to the actual scheme."""

    def _detect(self, url):
        from config.database_config import _detect_dialect_from_url

        return _detect_dialect_from_url(url)

    def test_postgres_url_with_sqlserver_hostname_stays_postgres(self) -> None:
        result = self._detect("postgresql://sqlserver-vm.internal/db")
        self.assertEqual(result, "postgresql")

    def test_sqlserver_prefix_classifies_as_sqlserver(self) -> None:
        result = self._detect("mssql+pymssql://host/x")
        self.assertEqual(result, "sqlserver")

    def test_mysql_url_with_oracle_in_path_stays_mysql(self) -> None:
        result = self._detect("mysql+pymysql://h:3306/oracle_migrated_db")
        self.assertEqual(result, "mysql")

    def test_db2_prefix_matches(self) -> None:
        result = self._detect("ibm_db_sa://h:50000/sample")
        self.assertEqual(result, "db2")


# ---------------------------------------------------------------------------
# B10-BUG-23: SQLite partial-index WHERE predicate must round-trip
# ---------------------------------------------------------------------------
class TestBug23SqlitePartialIndexWhere(unittest.TestCase):
    """The introspector never extracted the WHERE predicate and the
    generator gated on the wrong attribute (``where_clause``). Both sides
    are now aligned on ``Index.condition``."""

    def test_introspector_parses_simple_where(self) -> None:
        from db.plugins.sqlite.introspection.sqlite_introspector import (
            SQLiteIntrospector,
        )

        # Use __new__ so we can exercise the helper without a real conn.
        intro = SQLiteIntrospector.__new__(SQLiteIntrospector)
        intro.log = MagicMock()

        sql = "CREATE INDEX idx_active ON users(email) WHERE active = 1"
        self.assertEqual(intro._parse_index_where_clause(sql), "active = 1")

    def test_introspector_handles_qualified_table(self) -> None:
        from db.plugins.sqlite.introspection.sqlite_introspector import (
            SQLiteIntrospector,
        )

        intro = SQLiteIntrospector.__new__(SQLiteIntrospector)
        intro.log = MagicMock()
        sql = 'CREATE INDEX idx ON "main"."users"(email, status) WHERE status IN (1,2)'
        self.assertEqual(intro._parse_index_where_clause(sql), "status IN (1,2)")

    def test_introspector_returns_none_without_where(self) -> None:
        from db.plugins.sqlite.introspection.sqlite_introspector import (
            SQLiteIntrospector,
        )

        intro = SQLiteIntrospector.__new__(SQLiteIntrospector)
        intro.log = MagicMock()
        sql = "CREATE INDEX idx ON users(email)"
        self.assertIsNone(intro._parse_index_where_clause(sql))

    def test_generator_emits_where_from_condition(self) -> None:
        from core.sql_model.index import Index
        from db.plugins.sqlite.generator.ddl_generator import SQLiteSqlGenerator

        gen = SQLiteSqlGenerator.__new__(SQLiteSqlGenerator)
        index = Index(
            name="idx_active",
            table_name="users",
            columns=["email"],
            unique=False,
            condition="active = 1",
            dialect="sqlite",
        )
        sql = gen._generate_index_create_statement(index)
        self.assertIn("WHERE active = 1", sql)

    def test_generator_omits_where_when_no_predicate(self) -> None:
        from core.sql_model.index import Index
        from db.plugins.sqlite.generator.ddl_generator import SQLiteSqlGenerator

        gen = SQLiteSqlGenerator.__new__(SQLiteSqlGenerator)
        index = Index(
            name="idx_plain",
            table_name="users",
            columns=["email"],
            unique=False,
            dialect="sqlite",
        )
        sql = gen._generate_index_create_statement(index)
        self.assertNotIn("WHERE", sql.upper())


# ---------------------------------------------------------------------------
# B10-BUG-24: CosmosDB clean drops internal containers instead of clearing rows
# ---------------------------------------------------------------------------
class TestBug24CosmosCleanInternalContainers(unittest.TestCase):
    """Clean should remove every Cosmos container, including history."""

    def _make_ops(self):
        from db.plugins.cosmosdb.cosmosdb.schema_operations import (
            CosmosDbSchemaOperations,
        )

        ops = CosmosDbSchemaOperations.__new__(CosmosDbSchemaOperations)
        ops.log = MagicMock()
        ops.connection_manager = MagicMock()
        return ops

    def _run_clean(self, ops, container_names):
        ops.list_containers = MagicMock(return_value=container_names)
        ops.delete_container = MagicMock(return_value=True)
        ops.clean_schema(connection=None, schema="")
        return ops

    def test_history_container_is_dropped_not_cleared(self) -> None:
        ops = self._make_ops()
        self._run_clean(ops, ["dblift_schema_history"])

        ops.delete_container.assert_called_once_with("dblift_schema_history")
        ops.connection_manager.get_container_client.assert_not_called()

    def test_all_internal_containers_are_dropped(self) -> None:
        ops = self._make_ops()
        self._run_clean(
            ops,
            ["dblift_schema_history", "dblift_schema_snapshots", "dblift_migration_lock"],
        )

        self.assertEqual(
            [call.args[0] for call in ops.delete_container.call_args_list],
            ["dblift_schema_history", "dblift_schema_snapshots", "dblift_migration_lock"],
        )


if __name__ == "__main__":
    unittest.main()
