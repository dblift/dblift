"""Coverage tests for db/plugins/base_history_manager.py.

Targets the uncovered lines: _validate_migration_info, _normalize_migration_results,
_to_int, _to_boolean, _convert_timestamp,
_get_first_value, _build_migration_params, _undo_script_name, migration_exists,
get_row_limit_clause, get_current_version, record_undo, create_history_table,
_get_default_table_name.

Note: Java/JDBC conversion tests (_convert_java_object_to_python and related)
were removed as the project has moved to Python native drivers (no more JVM/JDBC).
"""

import datetime
import os
import unittest
from unittest.mock import MagicMock, patch

import pytest

from core.logger import NullLog
from db.plugins.base_history_manager import BaseHistoryManager

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
# _validate_migration_info  (lines 131-135)
# ===========================================================================


class TestValidateMigrationInfo(unittest.TestCase):
    def test_valid_info_does_not_raise(self):
        m = _make_manager()
        m._validate_migration_info(
            {"version": "1", "description": "d", "type": "SQL", "script": "V1.sql"}
        )

    def test_missing_one_field_raises(self):
        m = _make_manager()
        with self.assertRaises(ValueError) as ctx:
            m._validate_migration_info({"version": "1", "description": "d", "type": "SQL"})
        assert "script" in str(ctx.exception)

    def test_all_fields_missing_raises(self):
        m = _make_manager()
        with self.assertRaises(ValueError) as ctx:
            m._validate_migration_info({})
        msg = str(ctx.exception)
        for f in ["version", "description", "type", "script"]:
            assert f in msg

    def test_extra_fields_allowed(self):
        m = _make_manager()
        m._validate_migration_info(
            {
                "version": "1",
                "description": "d",
                "type": "SQL",
                "script": "V1.sql",
                "extra": "value",
            }
        )


# ===========================================================================
# _normalize_migration_results  (lines 149-185)
# ===========================================================================


class TestNormalizeMigrationResults(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_empty_list_returns_empty(self):
        assert self._m()._normalize_migration_results([]) == []

    def test_normalizes_installed_rank_lower(self):
        m = self._m()
        result = m._normalize_migration_results([{"installed_rank": "5"}])
        assert result[0]["installed_rank"] == 5

    def test_normalizes_installedrank_camel(self):
        m = self._m()
        result = m._normalize_migration_results([{"installedRank": "3"}])
        assert result[0]["installed_rank"] == 3

    def test_normalizes_version_to_str(self):
        m = self._m()
        result = m._normalize_migration_results([{"version": 2}])
        assert result[0]["version"] == "2"

    def test_normalizes_version_none(self):
        m = self._m()
        result = m._normalize_migration_results([{"version": None}])
        assert result[0]["version"] is None

    def test_normalizes_description(self):
        m = self._m()
        result = m._normalize_migration_results([{"description": "hello"}])
        assert result[0]["description"] == "hello"

    def test_normalizes_type(self):
        m = self._m()
        result = m._normalize_migration_results([{"type": "SQL"}])
        assert result[0]["type"] == "SQL"

    def test_normalizes_script_name_alias(self):
        m = self._m()
        result = m._normalize_migration_results([{"script_name": "V1.sql"}])
        assert result[0]["script"] == "V1.sql"

    def test_normalizes_scriptname_alias(self):
        m = self._m()
        result = m._normalize_migration_results([{"scriptname": "V1.sql"}])
        assert result[0]["script"] == "V1.sql"

    def test_normalizes_checksum(self):
        m = self._m()
        result = m._normalize_migration_results([{"checksum": 12345}])
        assert result[0]["checksum"] == "12345"

    def test_normalizes_installed_by(self):
        m = self._m()
        result = m._normalize_migration_results([{"installedby": "user1"}])
        assert result[0]["installed_by"] == "user1"

    def test_normalizes_installed_on(self):
        m = self._m()
        dt = datetime.datetime(2024, 1, 1)
        result = m._normalize_migration_results([{"installed_on": dt}])
        assert result[0]["installed_on"] == dt

    def test_normalizes_installedon_alias(self):
        m = self._m()
        dt = datetime.datetime(2024, 1, 1)
        result = m._normalize_migration_results([{"installedon": dt}])
        assert result[0]["installed_on"] == dt

    def test_normalizes_execution_time(self):
        m = self._m()
        result = m._normalize_migration_results([{"execution_time": "42"}])
        assert result[0]["execution_time"] == 42

    def test_normalizes_executiontime_alias(self):
        m = self._m()
        result = m._normalize_migration_results([{"executiontime": "10"}])
        assert result[0]["execution_time"] == 10

    def test_normalizes_success(self):
        m = self._m()
        result = m._normalize_migration_results([{"success": "true"}])
        assert result[0]["success"] is True

    def test_unknown_key_kept_as_is(self):
        m = self._m()
        result = m._normalize_migration_results([{"unknown_col": "x"}])
        assert result[0]["unknown_col"] == "x"

    def test_multiple_rows(self):
        m = self._m()
        result = m._normalize_migration_results(
            [
                {"version": "1"},
                {"version": "2"},
            ]
        )
        assert len(result) == 2
        assert result[0]["version"] == "1"
        assert result[1]["version"] == "2"


# ===========================================================================
# _to_int  (lines 198-222)
# ===========================================================================


class TestToInt(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_none_returns_zero(self):
        assert self._m()._to_int(None) == 0

    def test_integer(self):
        assert self._m()._to_int(5) == 5

    def test_float(self):
        assert self._m()._to_int(3.7) == 3

    def test_string_integer(self):
        assert self._m()._to_int("10") == 10

    def test_string_decimal(self):
        assert self._m()._to_int("7.9") == 7

    def test_empty_string_returns_zero(self):
        assert self._m()._to_int("  ") == 0

    def test_invalid_string_returns_zero(self):
        assert self._m()._to_int("abc") == 0

    def test_int_value_method(self):
        """Simulate JDBC BigDecimal with intValue() method."""
        obj = MagicMock()
        obj.intValue.return_value = 42
        assert self._m()._to_int(obj) == 42

    def test_none_type_error_returns_zero(self):
        """Any conversion error returns 0."""
        assert self._m()._to_int([1, 2]) == 0


# ===========================================================================
# _to_boolean  (lines 235-248)
# ===========================================================================


class TestToBoolean(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_none_returns_false(self):
        assert self._m()._to_boolean(None) is False

    def test_integer_nonzero_is_true(self):
        assert self._m()._to_boolean(1) is True

    def test_integer_zero_is_false(self):
        assert self._m()._to_boolean(0) is False

    def test_float_nonzero_is_true(self):
        assert self._m()._to_boolean(0.5) is True

    def test_int_value_nonzero_is_true(self):
        obj = MagicMock()
        obj.intValue.return_value = 1
        assert self._m()._to_boolean(obj) is True

    def test_int_value_zero_is_false(self):
        obj = MagicMock()
        obj.intValue.return_value = 0
        assert self._m()._to_boolean(obj) is False

    def test_string_true(self):
        for val in ("true", "1", "yes", "on", "t", "y", "TRUE", "YES"):
            assert self._m()._to_boolean(val) is True, f"Expected True for {val!r}"

    def test_string_false(self):
        for val in ("false", "0", "no", "off", "n", "FALSE"):
            assert self._m()._to_boolean(val) is False, f"Expected False for {val!r}"


# ===========================================================================
# _convert_timestamp  (lines 261-286)
# ===========================================================================


class TestConvertTimestamp(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_none_returns_none(self):
        assert self._m()._convert_timestamp(None) is None

    def test_datetime_returned_as_is(self):
        dt = datetime.datetime(2024, 3, 15, 10, 30, 0)
        result = self._m()._convert_timestamp(dt)
        assert result == dt

    def test_jdbc_timestamp_converted(self):
        """Simulate a JDBC Timestamp object with toLocalDateTime."""
        local_dt = MagicMock()
        local_dt.getYear.return_value = 2024
        local_dt.getMonthValue.return_value = 6
        local_dt.getDayOfMonth.return_value = 15
        local_dt.getHour.return_value = 12
        local_dt.getMinute.return_value = 30
        local_dt.getSecond.return_value = 45
        local_dt.getNano.return_value = 500_000

        jdbc_ts = MagicMock()
        jdbc_ts.toLocalDateTime.return_value = local_dt

        result = self._m()._convert_timestamp(jdbc_ts)
        assert isinstance(result, datetime.datetime)
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    def test_jdbc_timestamp_conversion_failure_returns_original(self):
        """If JDBC conversion raises, return original value."""
        jdbc_ts = MagicMock()
        jdbc_ts.toLocalDateTime.side_effect = Exception("boom")

        log = MagicMock()
        m = _make_manager(log=log)
        result = m._convert_timestamp(jdbc_ts)
        assert result is jdbc_ts
        log.debug.assert_called_once()

    def test_non_datetime_value_returned_as_is(self):
        result = self._m()._convert_timestamp("2024-01-01")
        assert result == "2024-01-01"


# ===========================================================================
# _get_first_value  (lines 329-344)
# ===========================================================================


class TestGetFirstValue(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_none_returns_none(self):
        assert self._m()._get_first_value(None) is None

    def test_empty_dict_returns_none(self):
        assert self._m()._get_first_value({}) is None

    def test_dict_returns_first_value(self):
        result = self._m()._get_first_value({"count": 5})
        assert result == 5

    def test_list_of_dicts_returns_first_value(self):
        result = self._m()._get_first_value([{"count": 3}])
        assert result == 3

    def test_list_of_scalars_returns_first(self):
        result = self._m()._get_first_value([42, 99])
        assert result == 42

    def test_empty_list_returns_none(self):
        assert self._m()._get_first_value([]) is None

    def test_list_with_empty_dict_returns_none(self):
        result = self._m()._get_first_value([{}])
        assert result is None

    def test_tuple_of_scalars_returns_first(self):
        result = self._m()._get_first_value((7, 8))
        assert result == 7


# ===========================================================================
# _build_migration_params  (lines 366-375)
# ===========================================================================


class TestBuildMigrationParams(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_returns_list_of_eight(self):
        m = self._m()
        info = {
            "version": "1",
            "description": "init",
            "type": "SQL",
            "script": "V1.sql",
            "checksum": "abc",
            "installed_by": "ci",
            "execution_time": 100,
        }
        params = m._build_migration_params(info, success_value=True)
        assert len(params) == 8

    def test_version_in_position_0(self):
        m = self._m()
        params = m._build_migration_params({"version": "2.0"}, success_value=1)
        assert params[0] == "2.0"

    def test_defaults_for_missing_fields(self):
        m = self._m()
        params = m._build_migration_params({}, success_value=0)
        assert params[1] == ""  # description defaults to ""
        assert params[2] == "SQL"  # type defaults to "SQL"
        assert params[3] == ""  # script defaults to ""
        assert params[4] is None  # checksum defaults to None
        assert params[5] == "unknown"  # installed_by defaults to "unknown"
        assert params[6] == 0  # execution_time defaults to 0
        assert params[7] == 0  # success_value as provided

    def test_success_value_in_position_7(self):
        m = self._m()
        params = m._build_migration_params({}, success_value="true")
        assert params[7] == "true"


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
# migration_exists  (lines 447-465)
# ===========================================================================


class TestMigrationExists(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_returns_false_when_table_does_not_exist(self):
        m = self._m()
        m.query_executor.table_exists.return_value = False
        assert m.migration_exists(MagicMock(), "myschema", "1.0") is False

    def test_returns_true_when_count_positive(self):
        m = self._m()
        m.query_executor.table_exists.return_value = True
        m.query_executor.get_schema_qualified_name.return_value = "myschema.dblift_schema_history"
        m.query_executor.execute_query.return_value = [{"count": 1}]
        assert m.migration_exists(MagicMock(), "myschema", "1.0") is True

    def test_returns_false_when_count_zero(self):
        m = self._m()
        m.query_executor.table_exists.return_value = True
        m.query_executor.get_schema_qualified_name.return_value = "myschema.dblift_schema_history"
        m.query_executor.execute_query.return_value = [{"count": 0}]
        assert m.migration_exists(MagicMock(), "myschema", "1.0") is False

    def test_returns_false_when_no_results(self):
        m = self._m()
        m.query_executor.table_exists.return_value = True
        m.query_executor.get_schema_qualified_name.return_value = "myschema.dblift_schema_history"
        m.query_executor.execute_query.return_value = []
        assert m.migration_exists(MagicMock(), "myschema", "1.0") is False

    def test_uses_custom_table_name(self):
        m = self._m()
        m.query_executor.table_exists.return_value = True
        m.query_executor.get_schema_qualified_name.return_value = "s.custom_table"
        m.query_executor.execute_query.return_value = [{"count": 0}]
        m.migration_exists(MagicMock(), "s", "1.0", table_name="custom_table")
        m.query_executor.table_exists.assert_called_with("s", "custom_table")

    def test_uses_default_table_name_when_none(self):
        m = self._m()
        m.query_executor.table_exists.return_value = False
        m.migration_exists(MagicMock(), "s", "1.0", table_name=None)
        m.query_executor.table_exists.assert_called_with("s", "dblift_schema_history")

    def test_returns_false_on_exception(self):
        m = self._m()
        m.query_executor.table_exists.side_effect = RuntimeError("db error")
        assert m.migration_exists(MagicMock(), "s", "1.0") is False

    def test_logs_error_on_exception(self):
        log = MagicMock()
        m = _make_manager(log=log)
        m.query_executor.table_exists.side_effect = RuntimeError("db error")
        m.migration_exists(MagicMock(), "s", "1.0")
        log.error.assert_called_once()


# ===========================================================================
# get_row_limit_clause  (line 478)
# ===========================================================================


class TestGetRowLimitClause(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_default_limit_1(self):
        assert self._m().get_row_limit_clause(1) == "LIMIT 1"

    def test_limit_10(self):
        assert self._m().get_row_limit_clause(10) == "LIMIT 10"

    def test_default_n_is_1(self):
        assert self._m().get_row_limit_clause() == "LIMIT 1"


# ===========================================================================
# get_current_version  (lines 499-518)
# ===========================================================================


class TestGetCurrentVersion(unittest.TestCase):
    def _m(self):
        return _make_manager()

    def test_returns_none_when_table_missing(self):
        m = self._m()
        m.query_executor.table_exists.return_value = False
        assert m.get_current_version(MagicMock(), "s") is None

    def test_returns_version_string_when_found(self):
        m = self._m()
        m.query_executor.table_exists.return_value = True
        m.query_executor.get_schema_qualified_name.return_value = "s.dblift_schema_history"
        m.query_executor.execute_query.return_value = [{"version": "3.0.0"}]
        result = m.get_current_version(MagicMock(), "s")
        assert result == "3.0.0"

    def test_returns_none_when_no_results(self):
        m = self._m()
        m.query_executor.table_exists.return_value = True
        m.query_executor.get_schema_qualified_name.return_value = "s.dblift_schema_history"
        m.query_executor.execute_query.return_value = []
        assert m.get_current_version(MagicMock(), "s") is None

    def test_uses_custom_table_name(self):
        m = self._m()
        m.query_executor.table_exists.return_value = False
        m.get_current_version(MagicMock(), "s", table_name="custom_table")
        m.query_executor.table_exists.assert_called_with("s", "custom_table")

    def test_uses_default_table_name_when_none(self):
        m = self._m()
        m.query_executor.table_exists.return_value = False
        m.get_current_version(MagicMock(), "s", table_name=None)
        m.query_executor.table_exists.assert_called_with("s", "dblift_schema_history")

    def test_returns_none_on_exception(self):
        m = self._m()
        m.query_executor.table_exists.side_effect = RuntimeError("err")
        assert m.get_current_version(MagicMock(), "s") is None

    def test_logs_error_on_exception(self):
        log = MagicMock()
        m = _make_manager(log=log)
        m.query_executor.table_exists.side_effect = RuntimeError("err")
        m.get_current_version(MagicMock(), "s")
        log.error.assert_called_once()

    def test_version_none_in_result_returns_none(self):
        m = self._m()
        m.query_executor.table_exists.return_value = True
        m.query_executor.get_schema_qualified_name.return_value = "s.dblift_schema_history"
        m.query_executor.execute_query.return_value = [{"version": None}]
        assert m.get_current_version(MagicMock(), "s") is None

    def test_sql_includes_limit_clause(self):
        m = self._m()
        m.query_executor.table_exists.return_value = True
        m.query_executor.get_schema_qualified_name.return_value = "s.dblift_schema_history"
        captured = []

        def capture(sql):
            captured.append(sql)
            return []

        m.query_executor.execute_query = capture
        m.get_current_version(MagicMock(), "s")
        assert len(captured) == 1
        assert "LIMIT 1" in captured[0]


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
