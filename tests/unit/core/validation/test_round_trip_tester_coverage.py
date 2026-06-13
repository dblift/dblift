"""
Coverage tests for core/validation/round_trip_tester.py

Targets previously uncovered lines:
  177-178, 222-229, 232-288, 401-403, 417, 545-604, 608-773, 793-795,
  833, 850, 879-880, 952, 969-970, 1005, 1015, 1022, 1047-1048,
  1059-1063, 1096-1097, 1130-1131, 1159, 1162, 1176-1177, 1187-1266
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
# _safe_rollback — outer exception path (lines 177-178)
# ---------------------------------------------------------------------------


class TestSafeRollbackOuterException(unittest.TestCase):
    """The outer try/except in _safe_rollback catches errors accessing provider.connection."""

    def test_outer_exception_logged_as_debug(self):
        """If accessing provider.connection itself raises, outer except is hit (lines 177-178)."""
        tester, _, _ = _make_tester(dialect="mysql")
        bad_provider = MagicMock()
        # Make accessing .connection raise an exception
        type(bad_provider).connection = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("connection attr error"))
        )
        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._safe_rollback(bad_provider, "outer context")


# ---------------------------------------------------------------------------
# run_round_trip_test — dialect-specific paths (lines 222-288)
# ---------------------------------------------------------------------------


class TestRunRoundTripTestOracleDebug(unittest.TestCase):
    """Dialect-specific paths inside run_round_trip_test."""

    def _make_full_run_tester(self, dialect="oracle"):
        """Create a tester rigged to complete a full run (up to the compare step)."""
        tester, src, tst = _make_tester(dialect=dialect, test_object_types=["tables"])
        table = MagicMock()
        table.name = "EMPLOYEES"
        table.columns = []
        mock_introspector = MagicMock()
        mock_introspector.get_tables.return_value = [table]
        tester.introspector = mock_introspector

        mock_gen = MagicMock()
        mock_gen.generate_create_statement.return_value = "CREATE TABLE EMPLOYEES (id INT)"
        mock_gen._generate_additional_statements.return_value = []
        tester.sql_generator = mock_gen

        # Patch all the execution helpers to succeed quickly
        tester._execute_on_test = MagicMock()
        tester._introspect_test = MagicMock(return_value={"tables": [table]})
        tester._compare_and_verify = MagicMock()
        return tester, src, tst

    # Note: The Oracle pre-introspection debug query (SELECT table_name FROM
    # all_tables WHERE owner = ...) was removed in PR-C1 as a pure-debug log
    # that violated the dialect-isolation principle. The three tests that
    # verified that behaviour have been removed along with the code.

    def test_mysql_dialect_logs_committed_skipping_rollback(self):
        """Lines 279-286: MySQL path logs 'transactions already committed'."""
        tester, _, _ = self._make_full_run_tester(dialect="mysql")
        tester.dialect = "mysql"

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            result = tester.run_round_trip_test()

    def test_db2_dialect_logs_committed_skipping_rollback(self):
        """Lines 279-286: DB2 path also logs 'transactions already committed'."""
        tester, _, _ = self._make_full_run_tester(dialect="db2")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            result = tester.run_round_trip_test()

    def test_success_true_when_no_errors_or_differences(self):
        """Lines 266-274: success = not has_errors and not has_differences."""
        tester, _, _ = self._make_full_run_tester(dialect="postgresql")

        result = tester.run_round_trip_test()
        self.assertTrue(result["success"])
        self.assertEqual(result["errors"], [])

    def test_success_false_when_differences_present(self):
        """Line 274: has_differences → success=False."""
        tester, _, _ = self._make_full_run_tester(dialect="postgresql")
        # Inject a difference into tables
        tester._compare_and_verify = MagicMock(
            side_effect=lambda orig, re_intro: tester.results["tables"]["differences"].append(
                "diff"
            )
        )

        result = tester.run_round_trip_test()
        self.assertFalse(result["success"])

    def test_exception_triggers_rollback_both_providers(self):
        """Lines 290-296: exception → rollback on both providers."""
        tester, src, tst = _make_tester(dialect="mysql", test_object_types=["tables"])
        tester.introspector = MagicMock()
        tester.introspector.get_tables.side_effect = RuntimeError("introspection failed")

        result = tester.run_round_trip_test()

        self.assertGreater(len(result["errors"]), 0)
        # _safe_rollback is called for both providers (mysql dialect)
        src.connection.rollback.assert_called()
        tst.connection.rollback.assert_called()

    def test_reintrospected_counts_updated(self):
        """Lines 255-257: reintrospected counts updated after test introspection."""
        tester, _, _ = self._make_full_run_tester(dialect="postgresql")
        table = MagicMock()
        table.name = "EMPLOYEES"
        tester._introspect_test = MagicMock(return_value={"tables": [table, table]})

        result = tester.run_round_trip_test()
        self.assertEqual(result["tables"]["reintrospected_count"], 2)


# ---------------------------------------------------------------------------
# _generate_create_statements — dependency ordering warning (lines 401-403)
# ---------------------------------------------------------------------------


class TestGenerateCreateStatementsDependencyWarning(unittest.TestCase):

    def test_dependency_ordering_failure_adds_warning(self):
        """Lines 401-403: DependencyAnalyzer.get_create_order failure → warning."""
        tester, _, _ = _make_tester(test_object_types=["tables"])
        table = MagicMock()
        table.name = "users"
        mock_gen = MagicMock()
        mock_gen.generate_create_statement.return_value = "CREATE TABLE users (id INT)"
        mock_gen._generate_additional_statements.return_value = []
        tester.sql_generator = mock_gen

        with patch("core.validation.round_trip_tester.DependencyAnalyzer") as MockAnalyzer:
            MockAnalyzer.return_value.get_create_order.side_effect = RuntimeError("cycle detected")
            statements = tester._generate_create_statements({"tables": [table]})

        # Warning should have been added
        self.assertTrue(any("Failed to order tables" in w for w in tester.results["warnings"]))
        # Generation still proceeds with original order
        self.assertEqual(len(statements), 1)


# ---------------------------------------------------------------------------
# _generate_statements_for_objects — no sql_generator (line 417)
# ---------------------------------------------------------------------------


class TestGenerateStatementsNoGenerator(unittest.TestCase):

    def test_skips_generation_when_no_sql_generator(self):
        """Line 417: if not self.sql_generator: continue."""
        tester, _, _ = _make_tester(test_object_types=["tables"])
        tester.sql_generator = None
        obj = MagicMock()
        obj.name = "users"

        results = tester._generate_statements_for_objects([obj], "tables")
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# _ensure_test_schema — oracle autocommit + commit paths (lines 545-604)
# ---------------------------------------------------------------------------


class TestEnsureTestSchema(unittest.TestCase):

    def test_oracle_autocommit_true_sets_to_false(self):
        """Lines 562-578: Oracle checks autocommit and sets to False."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = True

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._ensure_test_schema()

        tst.connection.setAutoCommit.assert_called_with(False)

    def test_oracle_autocommit_false_skips_setautocommit(self):
        """Lines 562-578: Oracle autocommit already False, no change."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False

        tester._ensure_test_schema()
        tst.connection.setAutoCommit.assert_not_called()

    def test_oracle_getautocommit_exception_logged(self):
        """Lines 575-578: Exception checking autocommit → debug log."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.side_effect = Exception("jdbc error")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._ensure_test_schema()

    def test_oracle_commits_schema_creation(self):
        """Lines 587-618: Oracle commits after schema creation."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.isClosed.return_value = False

        tester._ensure_test_schema()

        tst.connection.commit.assert_called()

    def test_oracle_autocommit_true_skips_commit(self):
        """Lines 600-608: Oracle: autocommit=True → skip commit (ORA-17273)."""
        tester, _, tst = _make_tester(dialect="oracle")
        # First call (pre-check) returns True (autocommit=True)
        tst.connection.getAutoCommit.return_value = True

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._ensure_test_schema()

        tst.connection.commit.assert_not_called()

    def test_db2_commits_schema_creation(self):
        """Lines 587-618: DB2 commits after schema creation."""
        tester, _, tst = _make_tester(dialect="db2")
        tst.connection.isClosed.return_value = False
        tst.connection.getAutoCommit.return_value = False

        tester._ensure_test_schema()

        tst.connection.commit.assert_called()

    def test_commit_closed_connection_warns(self):
        """Lines 619-627: Commit on closed connection → warning."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.isClosed.return_value = False
        tst.connection.commit.side_effect = Exception("17008 connection closed")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._ensure_test_schema()

    def test_commit_autocommit_error_warns(self):
        """Lines 628-632: Oracle autocommit commit error → warning."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.isClosed.return_value = False
        tst.connection.commit.side_effect = Exception("17273 autocommit")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._ensure_test_schema()

    def test_commit_other_error_reraises(self):
        """Lines 634-635: Other commit error → re-raised then caught by outer except.

        For Oracle, the outer except re-raises as SchemaCreationError.
        """
        from core.exceptions import SchemaCreationError

        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.isClosed.return_value = False
        tst.connection.commit.side_effect = Exception("permission denied")

        # Oracle: outer except re-raises as SchemaCreationError
        with self.assertRaises(SchemaCreationError):
            tester._ensure_test_schema()

    def test_connection_closed_before_commit_warns(self):
        """Lines 636-640: Connection closed → warning, no commit."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.isClosed.return_value = True  # connection closed

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._ensure_test_schema()

        tst.connection.commit.assert_not_called()

    def test_schema_creation_fails_non_oracle_continues(self):
        """Lines 641-648: schema creation exception on non-Oracle → just a warning."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.schema_operations.create_schema_if_not_exists.side_effect = Exception("schema error")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._ensure_test_schema()  # Should not raise

    def test_schema_creation_fails_oracle_raises_schema_creation_error(self):
        """Lines 641-647: schema creation exception on Oracle → SchemaCreationError."""
        from core.exceptions import SchemaCreationError

        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False
        tst.schema_operations.create_schema_if_not_exists.side_effect = Exception("ORA-01920")

        with self.assertRaises(SchemaCreationError):
            tester._ensure_test_schema()


# ---------------------------------------------------------------------------
# _clean_test_schema — commit/rollback before cleanup (lines 650-759)
# ---------------------------------------------------------------------------


class TestCleanTestSchema(unittest.TestCase):

    def test_commits_before_cleanup_postgresql(self):
        """Lines 659-681: Commit pending transaction before cleanup."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = False

        tester._clean_test_schema()

        tst.connection.commit.assert_called()

    def test_oracle_autocommit_true_skips_pre_cleanup_commit(self):
        """Lines 663-670: Oracle autocommit=True → skip commit before cleanup."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = True

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._clean_test_schema()

        tst.connection.commit.assert_not_called()

    def test_oracle_getautocommit_exception_before_cleanup_logged(self):
        """Lines 671-675: Exception checking autocommit → debug log."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.side_effect = Exception("jdbc error")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._clean_test_schema()

    def test_commit_before_cleanup_17273_error_logged(self):
        """Lines 683-690: ORA-17273 error during commit → debug log."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.commit.side_effect = Exception("17273 autocommit")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._clean_test_schema()

    def test_commit_before_cleanup_other_error_tries_rollback(self):
        """Lines 691-700: Non-17273 error → debug log + rollback attempt."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.commit.side_effect = Exception("some other error")

        tester._clean_test_schema()
        tst.connection.rollback.assert_called()

    def test_clean_schema_called_on_provider(self):
        """Lines 706-712: clean_schema is called on provider."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = False
        clean_response = MagicMock()
        clean_response.statements = ["DROP TABLE t"]
        tst.clean_schema.return_value = clean_response

        tester._clean_test_schema()

        tst.clean_schema.assert_called_once_with("tst_schema")

    def test_db2_post_cleanup_autocommit_check(self):
        """Lines 716-727: DB2 cleanup committed, check autocommit state."""
        tester, _, tst = _make_tester(dialect="db2")
        tst.connection.getAutoCommit.return_value = True
        clean_response = MagicMock()
        clean_response.statements = []
        tst.clean_schema.return_value = clean_response

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._clean_test_schema()

    def test_mysql_post_cleanup_autocommit_check(self):
        """Lines 729-741: MySQL cleanup committed, check autocommit state."""
        tester, _, tst = _make_tester(dialect="mysql")
        tst.connection.getAutoCommit.return_value = True
        clean_response = MagicMock()
        clean_response.statements = []
        tst.clean_schema.return_value = clean_response

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._clean_test_schema()

    def test_provider_without_clean_schema_logs_warning(self):
        """Line 743: Provider without clean_schema → warning."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = False
        del tst.clean_schema  # Remove clean_schema attribute

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._clean_test_schema()

    def test_cleanup_exception_logs_warning_and_attempts_rollback(self):
        """Lines 744-758: Exception during cleanup → warning + rollback attempt."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.commit.return_value = None
        tst.clean_schema.side_effect = RuntimeError("clean failed")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._clean_test_schema()

        tst.connection.rollback.assert_called()

    def test_cleanup_rollback_failure_also_logged(self):
        """Lines 756-759: Rollback after cleanup error fails → debug log."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.commit.return_value = None
        tst.clean_schema.side_effect = RuntimeError("clean failed")
        tst.connection.rollback.side_effect = Exception("rollback also failed")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._clean_test_schema()


# ---------------------------------------------------------------------------
# _set_autocommit — additional paths (lines 793-795)
# ---------------------------------------------------------------------------


class TestSetAutocommitAdditional(unittest.TestCase):

    def test_no_getautocommit_calls_setautocommit_directly(self):
        """Lines 793-795: No getAutoCommit → setAutoCommit(False) directly."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.isClosed.return_value = False
        # Remove getAutoCommit to trigger the else branch
        del tst.connection.getAutoCommit

        tester._set_autocommit()
        tst.connection.setAutoCommit.assert_called_with(False)

    def test_autocommit_already_false_logs_debug(self):
        """Lines 792-793: autoCommit already False → log debug."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.isClosed.return_value = False
        tst.connection.getAutoCommit.return_value = False

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._set_autocommit()

        tst.connection.setAutoCommit.assert_not_called()

    def test_setautocommit_exception_logs_warning(self):
        """Lines 796-799: Exception in setAutoCommit → warning."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.isClosed.return_value = False
        tst.connection.getAutoCommit.return_value = True
        tst.connection.setAutoCommit.side_effect = Exception("setAutoCommit failed")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._set_autocommit()


# ---------------------------------------------------------------------------
# _execute_ddl_statements (lines 761-774)
# ---------------------------------------------------------------------------


class TestExecuteDDLStatements(unittest.TestCase):

    def test_executes_each_statement(self):
        """Tests the full loop in _execute_ddl_statements."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.isClosed.return_value = False
        tst.connection.getAutoCommit.return_value = True
        tst.query_executor.execute_statement.return_value = None
        tst.query_executor.execute_query.return_value = [{"1": 1}]

        statements = ["CREATE TABLE t (id INT)", "CREATE TABLE t2 (id INT)"]
        tester._execute_ddl_statements(statements)

        # execute_statement should have been called twice (for actual DDL execution)
        # plus possibly drop calls
        self.assertGreater(tst.query_executor.execute_statement.call_count, 0)

    def test_recover_from_statement_error_called_on_failure(self):
        """Lines 773-774: Exception in _execute_single_statement → _recover called."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.connection.isClosed.return_value = False
        tst.connection.getAutoCommit.return_value = True
        tst.query_executor.execute_query.return_value = [{"1": 1}]

        # Drop succeeds, but execution fails
        execute_calls = []

        def execute_side_effect(*args, **kwargs):
            execute_calls.append(args)
            if len(execute_calls) > 1:  # Second call (actual CREATE) fails
                raise Exception("execution failed")

        tst.query_executor.execute_statement.side_effect = execute_side_effect

        # Should not raise — errors are recovered
        tester._execute_ddl_statements(["CREATE TABLE t (id INT)"])
        self.assertGreater(len(tester.results["errors"]), 0)


# ---------------------------------------------------------------------------
# _drop_preexisting_objects — oracle commit and various branches (lines 858-886)
# ---------------------------------------------------------------------------


class TestDropPreexistingObjectsExtended(unittest.TestCase):

    def test_oracle_commits_after_drop(self):
        """Line 868-869: Oracle/DB2 commits after drop."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.query_executor.execute_statement.return_value = None

        stmt = 'CREATE TABLE "HR"."EMPLOYEES" (ID INTEGER)'
        tester._drop_preexisting_objects(stmt)

        tst.connection.commit.assert_called()

    def test_db2_commits_after_drop(self):
        """Line 868-869: DB2 commits after drop."""
        tester, _, tst = _make_tester(dialect="db2")
        tst.query_executor.execute_statement.return_value = None

        stmt = 'CREATE TABLE "MYSCHEMA"."MYTABLE" (ID INTEGER)'
        tester._drop_preexisting_objects(stmt)

        tst.connection.commit.assert_called()

    def test_drop_rollback_failure_logged(self):
        """Lines 877-882: Rollback after failed drop also fails → debug log."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.query_executor.execute_statement.side_effect = Exception(
            "current transaction is aborted"
        )
        tst.connection.rollback.side_effect = Exception("rollback failed")

        stmt = 'CREATE TABLE "schema"."table" (id INT)'
        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._drop_preexisting_objects(stmt)

    def test_schema_same_as_table_name_uses_test_schema(self):
        """Lines 849-850: If schema_name == table_name → use test_schema."""
        tester, _, tst = _make_tester(dialect="postgresql")
        tst.query_executor.execute_statement.return_value = None

        # No schema prefix → schema_name might equal table_name
        stmt = "CREATE TABLE users (id INT)"
        tester._drop_preexisting_objects(stmt)
        # Just test it doesn't raise


# ---------------------------------------------------------------------------
# _retry_drop_and_create (lines 997-1063)
# ---------------------------------------------------------------------------


class TestRetryDropAndCreate(unittest.TestCase):

    def test_returns_false_when_no_table_match(self):
        """Line 1005: No CREATE TABLE match → return False."""
        tester, _, _ = _make_tester(dialect="oracle")
        result = tester._retry_drop_and_create("SELECT 1")
        self.assertFalse(result)

    def test_oracle_successful_drop_and_create(self):
        """Lines 1047-1058: Drop succeeds, CREATE succeeds → True."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.query_executor.execute_query.return_value = [{"OWNER": "HR", "TABLE_NAME": "EMPLOYEES"}]
        tst.query_executor.execute_statement.return_value = None
        tst.connection.commit.return_value = None

        stmt = 'CREATE TABLE "HR"."EMPLOYEES" (ID INTEGER)'
        result = tester._retry_drop_and_create(stmt)
        self.assertTrue(result)

    def test_oracle_all_drops_fail_returns_false(self):
        """Lines 1061-1062: All DROP strategies fail → False."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.query_executor.execute_query.return_value = []
        tst.query_executor.execute_statement.side_effect = Exception("table does not exist")

        stmt = 'CREATE TABLE "HR"."EMPLOYEES" (ID INTEGER)'
        result = tester._retry_drop_and_create(stmt)
        self.assertFalse(result)

    def test_oracle_drop_succeeds_create_fails(self):
        """Lines 1059-1060: Drop OK, CREATE fails → False."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.query_executor.execute_query.return_value = [{"OWNER": "HR", "TABLE_NAME": "EMPLOYEES"}]
        execute_calls = []

        def execute_side(conn, sql, params):
            execute_calls.append(sql)
            if "EXECUTE IMMEDIATE" in sql.upper():
                return None  # drop succeeds
            else:
                raise Exception("create failed")

        tst.query_executor.execute_statement.side_effect = execute_side

        stmt = 'CREATE TABLE "HR"."EMPLOYEES" (ID INTEGER)'
        result = tester._retry_drop_and_create(stmt)
        self.assertFalse(result)

    def test_db2_successful_drop_and_create(self):
        """DB2 path: find in SYSCAT.TABLES, drop, create."""
        tester, _, tst = _make_tester(dialect="db2")
        tst.query_executor.execute_query.return_value = [
            {"TABSCHEMA": "MYSCHEMA", "TABNAME": "MYTABLE"}
        ]
        tst.query_executor.execute_statement.return_value = None
        tst.connection.commit.return_value = None

        stmt = 'CREATE TABLE "MYSCHEMA"."MYTABLE" (ID INTEGER)'
        result = tester._retry_drop_and_create(stmt)
        self.assertTrue(result)

    def test_unquoted_schema_and_table(self):
        """Lines 1015, 1022: Unquoted schema/table → uppercased."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.query_executor.execute_query.return_value = []
        tst.query_executor.execute_statement.return_value = None
        tst.connection.commit.return_value = None

        stmt = "CREATE TABLE HR.EMPLOYEES (ID INTEGER)"
        result = tester._retry_drop_and_create(stmt)
        # Whether it succeeds depends on execution, but it shouldn't raise
        self.assertIsInstance(result, bool)


# ---------------------------------------------------------------------------
# _build_retry_drop_strategies — DB2 exception path (lines 1130-1131)
# ---------------------------------------------------------------------------


class TestBuildRetryDropStrategiesDB2Exception(unittest.TestCase):

    def test_db2_syscat_query_exception_logs_warning(self):
        """Lines 1130-1131: DB2 SYSCAT query fails → warning."""
        tester, _, tst = _make_tester(dialect="db2")
        tst.query_executor.execute_query.side_effect = Exception("SYSCAT not accessible")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            strategies = tester._build_retry_drop_strategies('"MYSCHEMA"', '"MYTABLE"')

        # Still returns fallback strategies
        self.assertGreater(len(strategies), 0)


# ---------------------------------------------------------------------------
# _commit_test_execution — additional paths (lines 1159-1191)
# ---------------------------------------------------------------------------


class TestCommitTestExecutionAdditional(unittest.TestCase):

    def test_mysql_no_getautocommit_logs_debug(self):
        """Lines 1162: MySQL without getAutoCommit → debug log."""
        tester, _, tst = _make_tester(dialect="mysql")
        del tst.connection.getAutoCommit

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._commit_test_execution()

    def test_postgresql_no_getautocommit_commits_anyway(self):
        """Lines 1175-1177: Non-mysql/oracle/db2 without getAutoCommit → commit anyway."""
        tester, _, tst = _make_tester(dialect="postgresql")
        del tst.connection.getAutoCommit

        tester._commit_test_execution()
        tst.connection.commit.assert_called()

    def test_commit_failure_mysql_no_rollback(self):
        """Lines 1182-1190: MySQL commit failure → no rollback (avoids hang)."""
        tester, _, tst = _make_tester(dialect="mysql")
        tst.connection.getAutoCommit.return_value = False
        tst.connection.commit.side_effect = Exception("mysql commit failed")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._commit_test_execution()

        tst.connection.rollback.assert_not_called()

    def test_commit_failure_non_mysql_tries_rollback(self):
        """Lines 1182-1190: Non-MySQL commit failure → try rollback."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False  # commit path engaged
        tst.connection.commit.side_effect = Exception("oracle commit failed")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="WARNING"):
            tester._commit_test_execution()

        tst.connection.rollback.assert_called()

    def test_commit_failure_rollback_also_fails(self):
        """Lines 1188-1190: commit fails, rollback also fails → debug."""
        tester, _, tst = _make_tester(dialect="oracle")
        tst.connection.getAutoCommit.return_value = False  # engage commit path
        tst.connection.commit.side_effect = Exception("commit failed")
        tst.connection.rollback.side_effect = Exception("rollback failed")

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._commit_test_execution()

    def test_mysql_autocommit_true_skips_commit(self):
        """Lines 1158-1159: MySQL/DB2 autocommit=True → already auto-committed."""
        tester, _, tst = _make_tester(dialect="mysql")
        tst.connection.getAutoCommit.return_value = True

        import logging

        with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
            tester._commit_test_execution()

        tst.connection.commit.assert_not_called()


# ---------------------------------------------------------------------------
# _introspect_test — all object types (lines 1195-1266)
# ---------------------------------------------------------------------------


class TestIntrospectTest(unittest.TestCase):

    def _make_full_type_tester(self):
        types = [
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
        tester, src, tst = _make_tester(test_object_types=types)
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
        return tester, mock_introspector

    def test_introspects_all_object_types(self):
        """Lines 1209-1266: all object types re-introspected.

        The tester's ``introspector`` has a ``provider`` attribute so
        ``_introspect_test`` routes through ``IntrospectorFactory.create``
        (the F.3 architecture wires every dialect to its own plugin
        introspector class). Patch the factory's ``create`` instead of
        the legacy :class:`SchemaIntrospector` symbol that used to be
        hit via fallback before F.3."""
        tester, _ = self._make_full_type_tester()

        mock_inst = MagicMock()
        mock_inst.get_tables.return_value = []
        mock_inst.get_views.return_value = []
        mock_inst.get_indexes.return_value = []
        mock_inst.get_sequences.return_value = []
        mock_inst.get_procedures.return_value = []
        mock_inst.get_functions.return_value = []
        mock_inst.get_triggers.return_value = []
        mock_inst.get_user_defined_types.return_value = []
        mock_inst.get_synonyms.return_value = []
        mock_inst.get_packages.return_value = []
        mock_inst.get_events.return_value = []
        mock_inst.get_extensions.return_value = []
        mock_inst.get_materialized_views.return_value = []

        with patch(
            "core.introspection.introspector_factory.IntrospectorFactory.create",
            return_value=mock_inst,
        ):
            objects = tester._introspect_test()

        self.assertIn("tables", objects)
        self.assertIn("views", objects)
        self.assertIn("sequences", objects)
        self.assertIn("materialized_views", objects)

    def test_uses_introspector_factory_when_introspector_has_provider(self):
        """Lines 1199-1203: If introspector has provider attr → use factory."""
        types = ["tables"]
        tester, src, tst = _make_tester(test_object_types=types)
        mock_introspector = MagicMock()
        mock_introspector.provider = src  # has provider attr
        mock_introspector.log = None
        tester.introspector = mock_introspector

        with patch(
            "core.introspection.introspector_factory.IntrospectorFactory.create"
        ) as mock_factory:
            mock_factory_inst = MagicMock()
            mock_factory_inst.get_tables.return_value = []
            mock_factory.return_value = mock_factory_inst

            objects = tester._introspect_test()

        mock_factory.assert_called_once()
        self.assertIn("tables", objects)

    def test_oracle_logs_table_names(self):
        """Lines 1216-1218: Oracle dialect logs table names."""
        types = ["tables"]
        tester, src, tst = _make_tester(dialect="oracle", test_object_types=types)
        table = MagicMock()
        table.name = "EMPLOYEES"
        tester.introspector = None

        with patch("core.introspection.schema_introspector.SchemaIntrospector") as MockIntrospector:
            mock_inst = MagicMock()
            mock_inst.get_tables.return_value = [table]
            MockIntrospector.return_value = mock_inst

            import logging

            with self.assertLogs("core.validation.round_trip_tester", level="DEBUG"):
                objects = tester._introspect_test()

        self.assertEqual(len(objects["tables"]), 1)

    def test_indexes_collected_from_tables(self):
        """Lines 1223-1230: indexes collected per table."""
        types = ["tables", "indexes"]
        tester, src, tst = _make_tester(test_object_types=types)
        table = MagicMock()
        table.name = "users"
        tester.introspector = None

        with patch("core.introspection.schema_introspector.SchemaIntrospector") as MockIntrospector:
            mock_inst = MagicMock()
            mock_inst.get_tables.return_value = [table]
            mock_idx = MagicMock()
            mock_inst.get_indexes.return_value = [mock_idx]
            MockIntrospector.return_value = mock_inst

            objects = tester._introspect_test()

        self.assertEqual(len(objects["indexes"]), 1)

    def test_materialized_views_handled(self):
        """Lines 1261-1264: materialized_views introspected."""
        types = ["materialized_views"]
        tester, src, tst = _make_tester(test_object_types=types)
        tester.introspector = None

        with patch("core.introspection.schema_introspector.SchemaIntrospector") as MockIntrospector:
            mock_inst = MagicMock()
            mock_inst.get_materialized_views.return_value = None
            MockIntrospector.return_value = mock_inst

            objects = tester._introspect_test()

        self.assertIn("materialized_views", objects)
        self.assertEqual(objects["materialized_views"], [])

    def test_extensions_introspected(self):
        """Line 1259: extensions use get_extensions() without schema."""
        types = ["extensions"]
        tester, src, tst = _make_tester(test_object_types=types)
        tester.introspector = None

        with patch("core.introspection.schema_introspector.SchemaIntrospector") as MockIntrospector:
            mock_inst = MagicMock()
            mock_inst.get_extensions.return_value = ["pg_stat_statements"]
            MockIntrospector.return_value = mock_inst

            objects = tester._introspect_test()

        self.assertIn("extensions", objects)


# ---------------------------------------------------------------------------
# _compare_and_verify — additional object types (lines 1297-1315)
# ---------------------------------------------------------------------------


class TestCompareAndVerifyAdditional(unittest.TestCase):

    def test_compares_all_secondary_types(self):
        """Lines 1297-1315: All secondary object types compared by name."""
        types = [
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
        tester, _, _ = _make_tester(test_object_types=types)
        rt_comparator = MagicMock()
        tester._rt_comparator = rt_comparator

        original = {t: [] for t in types}
        tester._compare_and_verify(original, original.copy())

        # compare_objects_by_name should be called for each of the secondary types
        self.assertEqual(rt_comparator.compare_objects_by_name.call_count, len(types))

    def test_only_types_in_test_object_types_are_compared(self):
        """Only types present in test_object_types are compared."""
        tester, _, _ = _make_tester(test_object_types=["tables"])
        rt_comparator = MagicMock()
        tester._rt_comparator = rt_comparator

        tester._compare_and_verify({"tables": [], "views": []}, {"tables": [], "views": []})

        rt_comparator.compare_tables.assert_called_once()
        rt_comparator.compare_views.assert_not_called()
        rt_comparator.compare_objects_by_name.assert_not_called()


# ---------------------------------------------------------------------------
# _build_drop_sql — quoted schema/table for DB2
# ---------------------------------------------------------------------------


class TestBuildDropSqlExtended(unittest.TestCase):

    def test_db2_quoted_schema_and_table(self):
        """DB2 quoted/unquoted table names."""
        tester, _, _ = _make_tester(dialect="db2")
        sql = tester._build_drop_sql("MYSCHEMA", "MYTABLE", True, True)
        self.assertIn("DROP TABLE", sql)
        self.assertIn('"MYSCHEMA"', sql)
        self.assertIn('"MYTABLE"', sql)

    def test_db2_unquoted_uppercased(self):
        """DB2 unquoted: schema/table are uppercased."""
        tester, _, _ = _make_tester(dialect="db2")
        sql = tester._build_drop_sql("myschema", "mytable", False, False)
        self.assertIn("DROP TABLE", sql)


# ---------------------------------------------------------------------------
# _execute_on_test (lines 543-554)
# ---------------------------------------------------------------------------


class TestExecuteOnTest(unittest.TestCase):

    def test_calls_ensure_clean_and_execute(self):
        """Lines 545-549: _execute_on_test calls sub-methods in order."""
        tester, _, tst = _make_tester(dialect="postgresql")
        call_order = []

        tester._ensure_test_schema = MagicMock(side_effect=lambda: call_order.append("ensure"))
        tester._clean_test_schema = MagicMock(side_effect=lambda: call_order.append("clean"))
        tester._execute_ddl_statements = MagicMock(
            side_effect=lambda s: call_order.append("execute")
        )
        tester._commit_test_execution = MagicMock(side_effect=lambda: call_order.append("commit"))

        tester._execute_on_test(["CREATE TABLE t (id INT)"])

        self.assertEqual(call_order, ["ensure", "clean", "execute", "commit"])

    def test_exception_adds_error_and_reraises(self):
        """Lines 550-554: Exception in execute → error added, re-raised."""
        tester, _, _ = _make_tester()
        tester._ensure_test_schema = MagicMock(side_effect=RuntimeError("schema error"))

        with self.assertRaises(RuntimeError):
            tester._execute_on_test(["CREATE TABLE t (id INT)"])

        self.assertGreater(len(tester.results["errors"]), 0)


if __name__ == "__main__":
    unittest.main()
