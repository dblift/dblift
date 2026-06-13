"""Extended unit tests for RoundTripTester.

Targets uncovered paths in:
  core/validation/round_trip_tester.py  (625 stmts, 7%)
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from core.validation.round_trip_tester import RoundTripTester

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(dialect="postgresql"):
    provider = MagicMock()
    provider.config = SimpleNamespace(database=SimpleNamespace(type=dialect))
    provider.connection = MagicMock()
    provider.query_executor = MagicMock()
    return provider


def _make_tester(dialect="postgresql", same_schema=False, test_object_types=None):
    src = _make_provider(dialect)
    tst = _make_provider(dialect)
    source_schema = "src_schema"
    test_schema = "src_schema" if same_schema else "tst_schema"
    tester = RoundTripTester(
        source_provider=src,
        test_provider=tst,
        source_schema=source_schema,
        test_schema=test_schema,
        test_object_types=test_object_types or ["tables"],
    )
    return tester, src, tst


# ---------------------------------------------------------------------------
# __init__ / dialect detection
# ---------------------------------------------------------------------------


class TestInit(unittest.TestCase):

    def test_dialect_from_provider_config(self):
        tester, _, _ = _make_tester(dialect="mysql")
        self.assertEqual(tester.dialect, "mysql")

    def test_dialect_fallback_when_no_config(self):
        src = MagicMock()
        del src.config  # no config attribute
        tst = _make_provider()
        tester = RoundTripTester(
            source_provider=src,
            test_provider=tst,
            source_schema="s",
            test_schema="t",
            test_object_types=["tables"],
        )
        # Wave C (story 26-9): when no config is available the framework
        # no longer assumes PostgreSQL — it falls back to a neutral empty
        # string so the downstream quirks lookup uses the registry default.
        self.assertEqual(tester.dialect, "")

    def test_test_object_types_lowercased(self):
        tester, _, _ = _make_tester(test_object_types=["TABLES", "VIEWS"])
        self.assertIn("tables", tester.test_object_types)
        self.assertIn("views", tester.test_object_types)

    def test_default_object_types_for_postgresql(self):
        # Must pass test_object_types=None explicitly to trigger _get_supported_object_types()
        src = _make_provider("postgresql")
        tst = _make_provider("postgresql")
        tester = RoundTripTester(
            source_provider=src,
            test_provider=tst,
            source_schema="src_schema",
            test_schema="tst_schema",
            test_object_types=None,  # triggers _get_supported_object_types()
        )
        self.assertIn("tables", tester.test_object_types)
        self.assertIn("user_defined_types", tester.test_object_types)

    def test_results_structure_initialized(self):
        tester, _, _ = _make_tester()
        self.assertIn("tables", tester.results)
        self.assertIn("views", tester.results)
        self.assertIn("errors", tester.results)
        self.assertIn("warnings", tester.results)
        self.assertFalse(tester.results["success"])


# ---------------------------------------------------------------------------
# _get_supported_object_types
# ---------------------------------------------------------------------------


class TestGetSupportedObjectTypes(unittest.TestCase):

    def test_postgresql_includes_extensions(self):
        tester, _, _ = _make_tester(dialect="postgresql", test_object_types=None)
        types = tester._get_supported_object_types()
        self.assertIn("extensions", types)
        self.assertIn("user_defined_types", types)
        self.assertIn("materialized_views", types)

    def test_oracle_includes_synonyms_and_packages(self):
        tester, _, _ = _make_tester(dialect="oracle", test_object_types=None)
        types = tester._get_supported_object_types()
        self.assertIn("synonyms", types)
        self.assertIn("packages", types)

    def test_mysql_includes_events(self):
        tester, _, _ = _make_tester(dialect="mysql", test_object_types=None)
        types = tester._get_supported_object_types()
        self.assertIn("events", types)

    def test_sqlserver_includes_synonyms(self):
        tester, _, _ = _make_tester(dialect="sqlserver", test_object_types=None)
        types = tester._get_supported_object_types()
        self.assertIn("synonyms", types)

    def test_db2_includes_packages(self):
        tester, _, _ = _make_tester(dialect="db2", test_object_types=None)
        types = tester._get_supported_object_types()
        self.assertIn("packages", types)

    def test_unknown_dialect_only_base_types(self):
        tester, _, _ = _make_tester(dialect="unknown_db", test_object_types=None)
        types = tester._get_supported_object_types()
        self.assertIn("tables", types)
        self.assertNotIn("extensions", types)
        self.assertNotIn("events", types)


# ---------------------------------------------------------------------------
# _safe_rollback
# ---------------------------------------------------------------------------


class TestSafeRollback(unittest.TestCase):

    def test_noop_for_postgresql(self):
        tester, src, _ = _make_tester(dialect="postgresql")
        tester._safe_rollback(src, "test context")
        src.connection.rollback.assert_not_called()

    def test_rollback_called_for_mysql(self):
        tester, src, _ = _make_tester(dialect="mysql")
        tester._safe_rollback(src, "test context")
        src.connection.rollback.assert_called_once()

    def test_rollback_called_for_db2(self):
        tester, src, _ = _make_tester(dialect="db2")
        tester._safe_rollback(src, "test context")
        src.connection.rollback.assert_called_once()

    def test_swallows_rollback_exception(self):
        tester, src, _ = _make_tester(dialect="mysql")
        src.connection.rollback.side_effect = RuntimeError("rollback failed")
        # Should not raise
        tester._safe_rollback(src, "test context")

    def test_handles_no_connection_attribute(self):
        tester, _, _ = _make_tester(dialect="mysql")
        provider_without_conn = MagicMock(spec=[])  # no connection attribute
        # Should not raise
        tester._safe_rollback(provider_without_conn, "test context")


# ---------------------------------------------------------------------------
# _replace_schema_in_sql
# ---------------------------------------------------------------------------


class TestReplaceSchemaInSql(unittest.TestCase):

    def test_replaces_quoted_schema(self):
        tester, _, _ = _make_tester(dialect="postgresql")
        tester.source_schema = "old_schema"
        tester.test_schema = "new_schema"
        sql = 'CREATE TABLE "old_schema"."users" (id INTEGER)'
        result = tester._replace_schema_in_sql(sql)
        self.assertIn("new_schema", result)
        self.assertNotIn("old_schema", result)

    def test_replaces_unquoted_schema_postgresql(self):
        tester, _, _ = _make_tester(dialect="postgresql")
        tester.source_schema = "old_schema"
        tester.test_schema = "new_schema"
        sql = "CREATE TABLE old_schema.users (id INTEGER)"
        result = tester._replace_schema_in_sql(sql)
        self.assertIn("new_schema", result)

    def test_replaces_bracketed_schema_sqlserver(self):
        tester, _, _ = _make_tester(dialect="sqlserver")
        tester.source_schema = "dbo"
        tester.test_schema = "test_dbo"
        sql = "CREATE TABLE [dbo].[orders] (id INTEGER)"
        result = tester._replace_schema_in_sql(sql)
        self.assertIn("test_dbo", result)

    def test_replaces_oracle_schema_in_references(self):
        tester, _, _ = _make_tester(dialect="oracle")
        tester.source_schema = "HR"
        tester.test_schema = "TEST_HR"
        sql = "REFERENCES HR.employees(id)"
        result = tester._replace_schema_in_sql(sql)
        self.assertIn("TEST_HR", result)

    def test_replaces_db2_from_clause(self):
        tester, _, _ = _make_tester(dialect="db2")
        tester.source_schema = "MYSCHEMA"
        tester.test_schema = "TESTSCHEMA"
        sql = "SELECT * FROM MYSCHEMA.orders"
        result = tester._replace_schema_in_sql(sql)
        self.assertIn("TESTSCHEMA", result)

    def test_no_replace_when_same_schema(self):
        tester, _, _ = _make_tester(dialect="postgresql", same_schema=True)
        sql = 'CREATE TABLE "src_schema"."users" (id INTEGER)'
        result = tester._replace_schema_in_sql(sql)
        # Source and test schema are the same here, but replace still runs
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# _build_drop_sql
# ---------------------------------------------------------------------------


class TestBuildDropSql(unittest.TestCase):

    def test_postgresql_drop(self):
        tester, _, _ = _make_tester(dialect="postgresql")
        sql = tester._build_drop_sql("myschema", "users", False, False)
        self.assertIn("DROP TABLE IF EXISTS", sql)
        self.assertIn("CASCADE", sql)

    def test_mysql_drop(self):
        tester, _, _ = _make_tester(dialect="mysql")
        sql = tester._build_drop_sql("mydb", "orders", False, False)
        self.assertIn("DROP TABLE IF EXISTS", sql)
        self.assertIn("`mydb`", sql)
        self.assertIn("`orders`", sql)

    def test_oracle_drop(self):
        tester, _, _ = _make_tester(dialect="oracle")
        sql = tester._build_drop_sql("HR", "EMPLOYEES", False, False)
        self.assertIn("EXECUTE IMMEDIATE", sql)
        self.assertIn("CASCADE CONSTRAINTS", sql)

    def test_sqlserver_drop(self):
        tester, _, _ = _make_tester(dialect="sqlserver")
        sql = tester._build_drop_sql("dbo", "users", False, False)
        self.assertIn("OBJECT_ID", sql)
        self.assertIn("DROP TABLE", sql)

    def test_db2_drop(self):
        tester, _, _ = _make_tester(dialect="db2")
        sql = tester._build_drop_sql("MYSCHEMA", "MYTABLE", False, False)
        self.assertIn("DROP TABLE", sql)

    def test_default_dialect_drop(self):
        tester, _, _ = _make_tester(dialect="unknown")
        sql = tester._build_drop_sql("schema", "table", False, False)
        self.assertIn("DROP TABLE IF EXISTS", sql)

    def test_oracle_quoted_schema_and_table(self):
        tester, _, _ = _make_tester(dialect="oracle")
        sql = tester._build_drop_sql("HR", "EMPLOYEES", True, True)
        self.assertIn('"HR"', sql)
        self.assertIn('"EMPLOYEES"', sql)


# ---------------------------------------------------------------------------
# _drop_preexisting_objects
# ---------------------------------------------------------------------------


class TestDropPreexistingObjects(unittest.TestCase):

    def test_no_match_returns_early(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tester._drop_preexisting_objects("SELECT 1")
        tst.query_executor.execute_statement.assert_not_called()

    def test_executes_drop_on_create_table(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        stmt = 'CREATE TABLE "myschema"."users" (id INTEGER)'
        tester._drop_preexisting_objects(stmt)
        tst.query_executor.execute_statement.assert_called_once()

    def test_handles_oracle_commit_after_drop(self):
        tester, _, tst = _make_tester(dialect="oracle")
        stmt = 'CREATE TABLE "HR"."EMPLOYEES" (ID INTEGER)'
        tester._drop_preexisting_objects(stmt)
        tst.query_executor.execute_statement.assert_called()

    def test_handles_transaction_aborted_error(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.query_executor.execute_statement.side_effect = Exception(
            "current transaction is aborted"
        )
        stmt = 'CREATE TABLE "myschema"."users" (id INTEGER)'
        # Should not raise; rollback should be attempted
        tester._drop_preexisting_objects(stmt)

    def test_handles_non_existing_table_error(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.query_executor.execute_statement.side_effect = Exception("table does not exist")
        stmt = 'CREATE TABLE "myschema"."users" (id INTEGER)'
        # Non-critical error, should not raise
        tester._drop_preexisting_objects(stmt)


# ---------------------------------------------------------------------------
# _set_autocommit
# ---------------------------------------------------------------------------


class TestSetAutocommit(unittest.TestCase):

    def test_sets_autocommit_false_for_postgresql(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.isClosed.return_value = False
        tst.connection.getAutoCommit.return_value = True

        tester._set_autocommit()

        tst.connection.setAutoCommit.assert_called_with(False)

    def test_skips_autocommit_for_mysql(self):
        tester, _, tst = _make_tester(dialect="mysql")
        tester._set_autocommit()
        tst.connection.setAutoCommit.assert_not_called()

    def test_skips_autocommit_for_db2(self):
        tester, _, tst = _make_tester(dialect="db2")
        tester._set_autocommit()
        tst.connection.setAutoCommit.assert_not_called()

    def test_skips_autocommit_for_oracle(self):
        tester, _, tst = _make_tester(dialect="oracle")
        tester._set_autocommit()
        tst.connection.setAutoCommit.assert_not_called()

    def test_logs_warning_when_connection_closed(self):
        """When connection is closed, a warning is logged (exception is caught internally)."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.isClosed.return_value = True
        # The exception is caught internally; _set_autocommit logs a warning
        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._set_autocommit()


# ---------------------------------------------------------------------------
# _recover_from_statement_error
# ---------------------------------------------------------------------------


class TestRecoverFromStatementError(unittest.TestCase):

    def test_rollback_on_transaction_aborted(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        error = Exception("current transaction is aborted")
        tester._recover_from_statement_error(error, "CREATE TABLE t (id INT)")
        tst.connection.rollback.assert_called()

    def test_adds_error_for_regular_failure(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        error = Exception("syntax error near ...")
        tester._recover_from_statement_error(error, "CREATE TABLE t (id INT")
        self.assertGreater(len(tester.results["errors"]), 0)

    def test_adds_error_for_sqlserver_syntax(self):
        tester, _, tst = _make_tester(dialect="sqlserver")
        error = Exception("Incorrect syntax near 'TABLE'")
        tester._recover_from_statement_error(error, "CREATE TABLE t (id INT)")
        self.assertGreater(len(tester.results["errors"]), 0)

    def test_retry_on_already_exists(self):
        tester, _, tst = _make_tester(dialect="oracle")
        error = Exception("ORA-00955: table already exists")
        stmt = 'CREATE TABLE "HR"."EMPLOYEES" (ID INTEGER)'
        tst.query_executor.execute_query.return_value = [{"OWNER": "HR", "TABLE_NAME": "EMPLOYEES"}]
        # execute_statement for drop might fail, then second execute succeeds
        tst.query_executor.execute_statement.return_value = None
        tst.connection.commit.return_value = None

        tester._recover_from_statement_error(error, stmt)
        # Oracle already-exists → retry attempted


# ---------------------------------------------------------------------------
# _execute_single_statement
# ---------------------------------------------------------------------------


class TestExecuteSingleStatement(unittest.TestCase):

    def test_succeeds_when_no_error(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.query_executor.execute_statement.return_value = None
        tester._execute_single_statement("CREATE TABLE t (id INT)", 1)
        tst.query_executor.execute_statement.assert_called_once()

    def test_raises_on_non_view_error(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.query_executor.execute_statement.side_effect = Exception("syntax error")
        with self.assertRaises(Exception):
            tester._execute_single_statement("CREATE TABLE t (id INT)", 1)

    def test_raises_on_view_with_non_dependency_error(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.query_executor.execute_statement.side_effect = Exception("permission denied")
        with self.assertRaises(Exception):
            tester._execute_single_statement("CREATE VIEW v AS SELECT 1", 1)

    def test_raises_on_view_with_dependency_error(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.query_executor.execute_statement.side_effect = Exception('table "users" does not exist')
        with self.assertRaises(Exception):
            tester._execute_single_statement("CREATE VIEW v AS SELECT * FROM users", 1)


# ---------------------------------------------------------------------------
# _build_retry_drop_strategies
# ---------------------------------------------------------------------------


class TestBuildRetryDropStrategies(unittest.TestCase):

    def test_oracle_queries_data_dictionary(self):
        tester, _, tst = _make_tester(dialect="oracle")
        tst.query_executor.execute_query.return_value = [{"OWNER": "HR", "TABLE_NAME": "EMP"}]
        strategies = tester._build_retry_drop_strategies('"HR"', '"EMP"')
        self.assertGreater(len(strategies), 0)
        # First strategy from data dictionary
        self.assertIn("HR", strategies[0])
        self.assertIn("EMP", strategies[0])

    def test_oracle_fallback_without_data_dictionary(self):
        tester, _, tst = _make_tester(dialect="oracle")
        tst.query_executor.execute_query.return_value = []
        strategies = tester._build_retry_drop_strategies('"HR"', '"EMP"')
        self.assertGreater(len(strategies), 0)

    def test_db2_queries_syscat(self):
        tester, _, tst = _make_tester(dialect="db2")
        tst.query_executor.execute_query.return_value = [
            {"TABSCHEMA": "MYSCHEMA", "TABNAME": "MYTABLE"}
        ]
        strategies = tester._build_retry_drop_strategies('"MYSCHEMA"', '"MYTABLE"')
        self.assertGreater(len(strategies), 0)

    def test_db2_fallback_when_not_found(self):
        tester, _, tst = _make_tester(dialect="db2")
        tst.query_executor.execute_query.return_value = []
        strategies = tester._build_retry_drop_strategies('"MYSCHEMA"', '"MYTABLE"')
        self.assertEqual(len(strategies), 1)

    def test_returns_generic_pair_for_non_oracle_non_db2(self):
        # Y-1: BaseQuirks.build_retry_drop_strategies returns two generic
        # candidates (quoted then unquoted). Vendors that never reach the
        # retry path (retry_drop_create_on_error=False) simply ignore them.
        tester, _, _ = _make_tester(dialect="postgresql")
        strategies = tester._build_retry_drop_strategies("schema", "table")
        self.assertEqual(strategies, ['"schema"."table"', "schema.table"])


# ---------------------------------------------------------------------------
# _introspect_source
# ---------------------------------------------------------------------------


class TestIntrospectSource(unittest.TestCase):

    def test_introspects_all_types(self):
        tester, _, _ = _make_tester(
            test_object_types=[
                "tables",
                "views",
                "indexes",
                "sequences",
                "procedures",
                "functions",
                "triggers",
                "user_defined_types",
                "synonyms",
                "packages",
                "events",
                "extensions",
                "materialized_views",
            ]
        )
        mock_introspector = MagicMock()
        mock_introspector.get_tables.return_value = []
        mock_introspector.get_views.return_value = []
        mock_introspector.get_indexes.return_value = []
        mock_introspector.get_sequences.return_value = []
        mock_introspector.get_procedures.return_value = []
        mock_introspector.get_functions.return_value = []
        mock_introspector.get_triggers.return_value = []
        mock_introspector.get_user_defined_types.return_value = []
        mock_introspector.get_synonyms.return_value = []
        mock_introspector.get_packages.return_value = []
        mock_introspector.get_events.return_value = []
        mock_introspector.get_extensions.return_value = []
        mock_introspector.get_materialized_views.return_value = []
        tester.introspector = mock_introspector

        objects = tester._introspect_source()
        self.assertIn("tables", objects)
        self.assertIn("views", objects)
        self.assertIn("sequences", objects)
        self.assertIn("materialized_views", objects)

    def test_creates_introspector_when_none(self):
        tester, src, _ = _make_tester(test_object_types=["tables"])
        tester.introspector = None
        mock_inst = MagicMock()
        mock_inst.get_tables.return_value = []
        # The inline import inside _introspect_source re-imports from core.introspection.schema_introspector
        with patch(
            "core.introspection.schema_introspector.SchemaIntrospector", return_value=mock_inst
        ):
            objects = tester._introspect_source()
        self.assertIn("tables", objects)

    def test_warning_when_indexes_without_tables(self):
        tester, _, _ = _make_tester(test_object_types=["indexes"])
        mock_introspector = MagicMock()
        tester.introspector = mock_introspector
        objects = tester._introspect_source()
        self.assertIn("indexes", objects)
        self.assertEqual(objects["indexes"], [])

    def test_collects_indexes_per_table(self):
        from core.sql_model.index import Index

        tester, _, _ = _make_tester(test_object_types=["tables", "indexes"])
        table = MagicMock()
        table.name = "users"
        mock_idx = MagicMock(spec=Index)
        mock_introspector = MagicMock()
        mock_introspector.get_tables.return_value = [table]
        mock_introspector.get_indexes.return_value = [mock_idx]
        tester.introspector = mock_introspector

        objects = tester._introspect_source()
        self.assertEqual(len(objects["indexes"]), 1)


# ---------------------------------------------------------------------------
# _generate_create_statements
# ---------------------------------------------------------------------------


class TestGenerateCreateStatements(unittest.TestCase):

    def test_returns_empty_when_no_objects(self):
        tester, _, _ = _make_tester()
        statements = tester._generate_create_statements({})
        self.assertEqual(statements, [])

    def test_generates_create_for_tables(self):
        tester, _, _ = _make_tester(test_object_types=["tables"])
        table = MagicMock()
        table.name = "users"
        mock_generator = MagicMock()
        mock_generator.generate_create_statement.return_value = "CREATE TABLE users (id INT)"
        mock_generator._generate_additional_statements.return_value = []
        tester.sql_generator = mock_generator

        statements = tester._generate_create_statements({"tables": [table]})
        self.assertEqual(len(statements), 1)
        self.assertIn("CREATE TABLE", statements[0])

    def test_logs_warning_for_empty_create_statement(self):
        tester, _, _ = _make_tester(test_object_types=["tables"])
        table = MagicMock()
        table.name = "broken"
        mock_generator = MagicMock()
        mock_generator.generate_create_statement.return_value = ""
        tester.sql_generator = mock_generator

        statements = tester._generate_create_statements({"tables": [table]})
        self.assertEqual(statements, [])
        self.assertGreater(len(tester.results["warnings"]), 0)

    def test_handles_exception_in_generate(self):
        tester, _, _ = _make_tester(test_object_types=["tables"])
        table = MagicMock()
        table.name = "error_table"
        mock_generator = MagicMock()
        mock_generator.generate_create_statement.side_effect = RuntimeError("generate failed")
        tester.sql_generator = mock_generator

        statements = tester._generate_create_statements({"tables": [table]})
        self.assertEqual(statements, [])
        self.assertGreater(len(tester.results["warnings"]), 0)

    def test_orders_tables_by_dependencies(self):
        tester, _, _ = _make_tester(test_object_types=["tables"])
        table = MagicMock()
        table.name = "users"
        mock_generator = MagicMock()
        mock_generator.generate_create_statement.return_value = "CREATE TABLE users (id INT)"
        mock_generator._generate_additional_statements.return_value = []
        tester.sql_generator = mock_generator

        with patch("core.validation.round_trip_tester.DependencyAnalyzer") as MockAnalyzer:
            analyzer_inst = MagicMock()
            analyzer_inst.get_create_order.return_value = [table]
            MockAnalyzer.return_value = analyzer_inst

            statements = tester._generate_create_statements({"tables": [table]})

        analyzer_inst.get_create_order.assert_called_once()


# ---------------------------------------------------------------------------
# _generate_statements_for_objects
# ---------------------------------------------------------------------------


class TestGenerateStatementsForObjects(unittest.TestCase):

    def test_replaces_schema_when_different(self):
        tester, _, _ = _make_tester(dialect="postgresql")
        tester.source_schema = "old"
        tester.test_schema = "new"
        obj = MagicMock()
        obj.name = "users"
        mock_gen = MagicMock()
        mock_gen.generate_create_statement.return_value = 'CREATE TABLE "old"."users" (id INT)'
        mock_gen._generate_additional_statements.return_value = []
        tester.sql_generator = mock_gen

        results = tester._generate_statements_for_objects([obj], "tables")
        self.assertIn("new", results[0])
        self.assertNotIn('"old"', results[0])

    def test_includes_additional_statements(self):
        tester, _, _ = _make_tester(test_object_types=["tables"])
        obj = MagicMock()
        obj.name = "t"
        mock_gen = MagicMock()
        mock_gen.generate_create_statement.return_value = "CREATE TABLE t (id INT)"
        mock_gen._generate_additional_statements.return_value = ["ALTER TABLE t ADD CHECK (id > 0)"]
        tester.sql_generator = mock_gen

        results = tester._generate_statements_for_objects([obj], "tables")
        self.assertEqual(len(results), 2)


# ---------------------------------------------------------------------------
# _commit_test_execution
# ---------------------------------------------------------------------------


class TestCommitTestExecution(unittest.TestCase):

    def test_commits_for_oracle(self):
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False  # commit path engaged
        tester._commit_test_execution()
        tst.connection.commit.assert_called_once()

    def test_commits_for_postgresql_when_autocommit_false(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = False
        tester._commit_test_execution()
        tst.connection.commit.assert_called_once()

    def test_skips_commit_for_postgresql_when_autocommit_true(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = True
        tester._commit_test_execution()
        tst.connection.commit.assert_not_called()

    def test_commit_for_mysql_when_autocommit_false(self):
        tester, _, tst = _make_tester(dialect="mysql")
        tst.connection.getAutoCommit.return_value = False
        tester._commit_test_execution()
        tst.connection.commit.assert_called_once()

    def test_handles_commit_failure(self):
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False  # commit path engaged
        tst.connection.commit.side_effect = RuntimeError("commit failed")
        # Should not raise
        tester._commit_test_execution()
        tst.connection.rollback.assert_called()

    def test_mysql_no_rollback_on_commit_failure(self):
        tester, _, tst = _make_tester(dialect="mysql")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.commit.side_effect = RuntimeError("commit failed")
        tester._commit_test_execution()
        # MySQL: no rollback on commit failure
        tst.connection.rollback.assert_not_called()


# ---------------------------------------------------------------------------
# _ensure_clean_transaction_state
# ---------------------------------------------------------------------------


class TestEnsureCleanTransactionState(unittest.TestCase):

    def test_executes_test_query_when_autocommit_false(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = False
        tst.query_executor.execute_query.return_value = [{"1": 1}]
        tester._ensure_clean_transaction_state()
        tst.query_executor.execute_query.assert_called_once()

    def test_skips_when_autocommit_true(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = True
        tester._ensure_clean_transaction_state()
        tst.query_executor.execute_query.assert_not_called()

    def test_rollback_on_transaction_error(self):
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = False
        tst.query_executor.execute_query.side_effect = Exception("transaction aborted")
        tester._ensure_clean_transaction_state()
        tst.connection.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# _compare_and_verify
# ---------------------------------------------------------------------------


class TestCompareAndVerify(unittest.TestCase):

    def test_compares_tables_via_rt_comparator(self):
        tester, _, _ = _make_tester(test_object_types=["tables"])
        rt_comparator = MagicMock()
        tester._rt_comparator = rt_comparator

        original = {"tables": []}
        reintrospected = {"tables": []}
        tester._compare_and_verify(original, reintrospected)

        rt_comparator.compare_tables.assert_called_once_with([], [], tester.results)

    def test_compares_views_via_rt_comparator(self):
        tester, _, _ = _make_tester(test_object_types=["views"])
        rt_comparator = MagicMock()
        tester._rt_comparator = rt_comparator

        tester._compare_and_verify({"views": []}, {"views": []})
        rt_comparator.compare_views.assert_called_once()

    def test_compares_indexes_via_rt_comparator(self):
        tester, _, _ = _make_tester(test_object_types=["indexes"])
        rt_comparator = MagicMock()
        tester._rt_comparator = rt_comparator

        tester._compare_and_verify({"indexes": []}, {"indexes": []})
        rt_comparator.compare_indexes.assert_called_once()

    def test_compares_sequences_by_name(self):
        tester, _, _ = _make_tester(test_object_types=["sequences"])
        rt_comparator = MagicMock()
        tester._rt_comparator = rt_comparator

        tester._compare_and_verify({"sequences": []}, {"sequences": []})
        rt_comparator.compare_objects_by_name.assert_called_once()


# ---------------------------------------------------------------------------
# run_round_trip_test — high-level
# ---------------------------------------------------------------------------


class TestRunRoundTripTest(unittest.TestCase):

    def test_returns_error_when_no_objects(self):
        tester, src, tst = _make_tester(test_object_types=["tables"])
        mock_introspector = MagicMock()
        mock_introspector.get_tables.return_value = []
        tester.introspector = mock_introspector

        result = tester.run_round_trip_test()
        self.assertIn("errors", result)
        self.assertGreater(len(result["errors"]), 0)
        self.assertFalse(result["success"])

    def test_returns_error_when_no_create_statements(self):
        tester, src, tst = _make_tester(test_object_types=["tables"])
        table = MagicMock()
        table.name = "users"
        table.columns = []
        mock_introspector = MagicMock()
        mock_introspector.get_tables.return_value = [table]
        tester.introspector = mock_introspector

        mock_generator = MagicMock()
        mock_generator.generate_create_statement.return_value = ""  # empty → warning
        tester.sql_generator = mock_generator

        result = tester.run_round_trip_test()
        self.assertFalse(result["success"])

    def test_stores_original_counts(self):
        tester, src, tst = _make_tester(test_object_types=["tables"])
        table1 = MagicMock()
        table1.name = "users"
        table2 = MagicMock()
        table2.name = "orders"
        mock_introspector = MagicMock()
        mock_introspector.get_tables.return_value = [table1, table2]
        tester.introspector = mock_introspector

        # Stop early by making generator return empty
        mock_generator = MagicMock()
        mock_generator.generate_create_statement.return_value = ""
        tester.sql_generator = mock_generator

        result = tester.run_round_trip_test()
        self.assertEqual(result["tables"]["original_count"], 2)

    def test_exception_during_run_adds_error(self):
        tester, src, tst = _make_tester(test_object_types=["tables"])
        tester.introspector = MagicMock()
        tester.introspector.get_tables.side_effect = RuntimeError("catastrophic failure")

        result = tester.run_round_trip_test()
        self.assertGreater(len(result["errors"]), 0)
        self.assertFalse(result["success"])


# ---------------------------------------------------------------------------
# get_summary
# ---------------------------------------------------------------------------


class TestGetSummary(unittest.TestCase):

    def test_returns_string(self):
        tester, _, _ = _make_tester(test_object_types=["tables"])
        summary = tester.get_summary()
        self.assertIsInstance(summary, str)


if __name__ == "__main__":
    unittest.main()
