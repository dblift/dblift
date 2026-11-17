"""Coverage tests for db/plugins/base_history_manager.py.

Targets the uncovered lines: _undo_script_name, record_undo,
create_history_table, _get_default_table_name.

Note: Java/JDBC conversion tests (_convert_java_object_to_python and related)
were removed as the project has moved to Python native drivers (no more JVM/JDBC).
"""

import unittest
from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.db.plugins.base_history_manager import BaseHistoryManager

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------


class ConcreteHistoryManager(BaseHistoryManager):
    """Minimal concrete implementation to allow instantiation."""

    def create_migration_history_table_if_not_exists(
        self, connection, schema, create_schema=False, table_name="dblift_schema_history"
    ):
        pass

    def record_migration(self, connection, schema, migration_info, table_name=None):
        pass

    def get_applied_migrations(self, connection, schema, table_name=None):
        return []

    def create_history_table(self, schema, table_name):
        return f"CREATE TABLE {schema}.{table_name} (...)"


def _make_manager(log=None):
    """Return a ConcreteHistoryManager with mocked dependencies."""
    query_executor = MagicMock()
    schema_operations = MagicMock()
    config = MagicMock()
    return ConcreteHistoryManager(
        query_executor=query_executor,
        schema_operations=schema_operations,
        config=config,
        log=log,
    )


# ===========================================================================
# _get_default_table_name
# ===========================================================================


class TestGetDefaultTableName(unittest.TestCase):
    def test_returns_standard_name(self):
        m = _make_manager()
        assert m._get_default_table_name() == "dblift_schema_history"


# ===========================================================================
# _check_baseline_safety (issue #405)
# ===========================================================================


class TestCheckBaselineSafety(unittest.TestCase):
    def test_empty_history_table_does_not_raise(self):
        m = _make_manager()
        m.query_executor.get_schema_qualified_name.return_value = "public.dblift_schema_history"
        m.query_executor.execute_query.return_value = [{"count": 0}]
        # Should not raise
        m._check_baseline_safety(MagicMock(), "public", "dblift_schema_history")

    def test_non_empty_history_table_raises_with_count(self):
        m = _make_manager()
        m.query_executor.get_schema_qualified_name.return_value = "public.dblift_schema_history"
        m.query_executor.execute_query.return_value = [{"count": 6}]
        with self.assertRaises(RuntimeError) as ctx:
            m._check_baseline_safety(MagicMock(), "public", "dblift_schema_history")
        msg = str(ctx.exception)
        assert "6 migration(s)" in msg
        assert "Baseline cannot be applied" in msg
        assert "public" in msg

    def test_count_query_failure_wraps_with_could_not_verify(self):
        m = _make_manager()
        m.query_executor.get_schema_qualified_name.return_value = "public.dblift_schema_history"
        m.query_executor.execute_query.side_effect = IOError("DB connection lost")
        with self.assertRaises(RuntimeError) as ctx:
            m._check_baseline_safety(MagicMock(), "public", "dblift_schema_history")
        assert "Could not verify if history table is empty" in str(ctx.exception)

    def test_uppercase_count_column_handled(self):
        # Oracle returns uppercase column names; helper handles both.
        m = _make_manager()
        m.query_executor.get_schema_qualified_name.return_value = "MYSCHEMA.DBLIFT_SCHEMA_HISTORY"
        m.query_executor.execute_query.return_value = [{"COUNT": 3}]
        with self.assertRaises(RuntimeError) as ctx:
            m._check_baseline_safety(MagicMock(), "MYSCHEMA", "DBLIFT_SCHEMA_HISTORY")
        assert "3 migration(s)" in str(ctx.exception)

    def test_empty_result_set_does_not_raise(self):
        m = _make_manager()
        m.query_executor.get_schema_qualified_name.return_value = "public.dblift_schema_history"
        m.query_executor.execute_query.return_value = []
        m._check_baseline_safety(MagicMock(), "public", "dblift_schema_history")

    def test_runtime_error_in_query_propagates_unchanged(self):
        # A pre-existing RuntimeError from the query layer (e.g. its own
        # safety check) must propagate as-is, not get re-wrapped.
        m = _make_manager()
        m.query_executor.get_schema_qualified_name.return_value = "public.dblift_schema_history"
        m.query_executor.execute_query.side_effect = RuntimeError("upstream RT error")
        with self.assertRaises(RuntimeError) as ctx:
            m._check_baseline_safety(MagicMock(), "public", "dblift_schema_history")
        assert "upstream RT error" in str(ctx.exception)
        assert "Could not verify" not in str(ctx.exception)


# ===========================================================================
# _undo_script_name  (lines 427-429)
# ===========================================================================


class TestUndoScriptName(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_no_script_name_uses_version(self):
        result = self._m()._undo_script_name("1.2.3")
        assert result == "UNDO_1.2.3.sql"

    def test_script_name_with_extension(self):
        result = self._m()._undo_script_name("1.0", "U1__undo.sql")
        assert result == "U1__undo.sql"

    def test_script_name_without_extension_gets_sql(self):
        result = self._m()._undo_script_name("1.0", "U1__undo")
        assert result == "U1__undo.sql"


# ===========================================================================
# record_undo  (lines 421-423)
# ===========================================================================


class TestRecordUndo(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_record_undo_returns_true_on_success(self):
        m = self._m()
        conn = MagicMock()
        result = m.record_undo(conn, "myschema", "1.0")
        assert result is True

    def test_record_undo_calls_record_migration(self):
        m = self._m()
        conn = MagicMock()
        m.record_migration = MagicMock()
        m.record_undo(conn, "myschema", "2.0")
        m.record_migration.assert_called_once()
        call_args = m.record_migration.call_args
        undo_info = call_args[0][2]
        assert undo_info["type"] == "UNDO_SQL"
        assert undo_info["version"] == "2.0"
        assert undo_info["success"] is True

    def test_record_undo_uses_script_name_when_given(self):
        m = self._m()
        m.record_migration = MagicMock()
        m.record_undo(MagicMock(), "s", "1.0", script_name="U1__undo.sql")
        info = m.record_migration.call_args[0][2]
        assert info["script"] == "U1__undo.sql"

    def test_record_undo_generates_script_name_when_none(self):
        m = self._m()
        m.record_migration = MagicMock()
        m.record_undo(MagicMock(), "s", "3.0")
        info = m.record_migration.call_args[0][2]
        assert info["script"] == "UNDO_3.0.sql"

    def test_record_undo_uses_custom_table_name(self):
        m = self._m()
        m.record_migration = MagicMock()
        m.record_undo(MagicMock(), "s", "1.0", table_name="custom_history")
        call_args = m.record_migration.call_args
        assert call_args[0][3] == "custom_history"

    def test_record_undo_returns_false_on_exception(self):
        m = self._m()
        m.record_migration = MagicMock(side_effect=RuntimeError("fail"))
        result = m.record_undo(MagicMock(), "s", "1.0")
        assert result is False

    def test_record_undo_logs_error_on_exception(self):
        log = MagicMock()
        m = _make_manager(log=log)
        m.record_migration = MagicMock(side_effect=RuntimeError("fail"))
        m.record_undo(MagicMock(), "s", "1.0")
        log.error.assert_called_once()

    def test_record_undo_logs_debug_on_success(self):
        log = MagicMock()
        m = _make_manager(log=log)
        m.record_migration = MagicMock()
        m.record_undo(MagicMock(), "s", "1.0")
        log.debug.assert_called_once()


# ===========================================================================
# create_history_table (concrete implementation)
# ===========================================================================


class TestCreateHistoryTable(unittest.TestCase):
    def test_returns_string(self):
        m = _make_manager()
        result = m.create_history_table("myschema", "dblift_schema_history")
        assert isinstance(result, str)
        assert "myschema" in result

    def test_uses_table_name(self):
        m = _make_manager()
        result = m.create_history_table("s", "custom_history")
        assert "custom_history" in result


# ===========================================================================
# NullLog default (line 34)
# ===========================================================================


class TestNullLogDefault(unittest.TestCase):
    def test_none_log_uses_nulllog(self):
        m = ConcreteHistoryManager(
            query_executor=MagicMock(),
            schema_operations=MagicMock(),
            config=MagicMock(),
            log=None,
        )
        assert isinstance(m.log, NullLog)

    def test_provided_log_used(self):
        log = MagicMock()
        m = ConcreteHistoryManager(
            query_executor=MagicMock(),
            schema_operations=MagicMock(),
            config=MagicMock(),
            log=log,
        )
        assert m.log is log
