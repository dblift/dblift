"""Delegation tests for JsonFormatter.format_result() decomposition (Story 25-10)."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from core.logger.formatters.jsonformatter import JsonFormatter
from core.logger.results import CleanResult, DiffResult, MigrateResult, OperationResult


def _make_result(success=True, error_message=None):
    """Build a minimal OperationResult mock."""
    result = Mock(spec=OperationResult)
    result.success = success
    result.error_message = error_message
    result.execution_time.return_value = 42.0
    result.start_time = datetime(2024, 1, 1, 10, 0, 0)
    result.end_time = datetime(2024, 1, 1, 10, 0, 1)
    return result


@pytest.mark.unit
class TestGetVersionInfo:
    """Tests for _get_version_info()."""

    def test_returns_log_format_version_key(self):
        formatter = JsonFormatter()
        info = formatter._get_version_info()
        assert "log_format_version" in info
        assert info["log_format_version"] == "1.0"

    def test_returns_dblift_version_key(self):
        formatter = JsonFormatter()
        info = formatter._get_version_info()
        assert "dblift_version" in info

    def test_version_is_string_or_none(self):
        formatter = JsonFormatter()
        info = formatter._get_version_info()
        assert info["dblift_version"] is None or isinstance(info["dblift_version"], str)


@pytest.mark.unit
class TestBuildTimeMetadata:
    """Tests for _build_time_metadata()."""

    def test_returns_timestamp(self):
        formatter = JsonFormatter()
        result = _make_result()
        meta = formatter._build_time_metadata(result)
        assert "timestamp" in meta

    def test_single_command_uses_result_start_end(self):
        formatter = JsonFormatter()
        result = _make_result()
        meta = formatter._build_time_metadata(result)
        assert meta["start_time"] == "2024-01-01 10:00:00"
        assert meta["end_time"] == "2024-01-01 10:00:01"

    def test_multi_command_uses_first_command_start(self):
        formatter = JsonFormatter()
        formatter.using_multi_command = True
        first_result = Mock()
        first_result.start_time = datetime(2024, 1, 1, 9, 0, 0)
        formatter.command_results = [{"result": first_result}]

        current = _make_result()
        current.end_time = datetime(2024, 1, 1, 11, 0, 0)

        meta = formatter._build_time_metadata(current)
        assert meta["start_time"] == "2024-01-01 09:00:00"
        assert meta["end_time"] == "2024-01-01 11:00:00"

    def test_missing_start_end_returns_none(self):
        formatter = JsonFormatter()
        result = Mock(spec=OperationResult)
        result.success = True
        result.error_message = None
        result.execution_time.return_value = 0.0
        # No start_time / end_time attributes
        del result.start_time
        del result.end_time
        meta = formatter._build_time_metadata(result)
        assert meta["start_time"] is None
        assert meta["end_time"] is None


@pytest.mark.unit
class TestBuildBaseMetadata:
    """Tests for _build_base_metadata()."""

    def test_success_status(self):
        formatter = JsonFormatter()
        result = _make_result(success=True)
        meta = formatter._build_base_metadata(result, "public", "mydb")
        assert meta["status"] == "SUCCESS"

    def test_failed_status(self):
        formatter = JsonFormatter()
        result = _make_result(success=False, error_message="boom")
        meta = formatter._build_base_metadata(result, "public", "mydb")
        assert meta["status"] == "FAILED"
        assert meta["error"] == "boom"

    def test_schema_and_database(self):
        formatter = JsonFormatter()
        result = _make_result()
        meta = formatter._build_base_metadata(result, "myschema", "mydb")
        assert meta["schema"] == "myschema"
        assert meta["database"] == "mydb"

    def test_empty_schema_and_database_fallback(self):
        formatter = JsonFormatter()
        result = _make_result()
        meta = formatter._build_base_metadata(result, None, None)
        assert meta["schema"] == ""
        assert meta["database"] == ""

    def test_warnings_empty_list_when_none(self):
        formatter = JsonFormatter()
        result = _make_result()
        del result.warnings  # ensure attribute absent
        meta = formatter._build_base_metadata(result, "s", "d")
        assert meta["warnings"] == []

    def test_db_connection_fields_included(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.db_version = "PostgreSQL 15"
        result.native_driver = "org.postgresql.Driver"
        result.database_url_masked = "postgresql+psycopg://host/db"
        result.server_name = "myserver"
        meta = formatter._build_base_metadata(result, "s", "d")
        assert meta["db_version"] == "PostgreSQL 15"
        assert meta["native_driver"] == "org.postgresql.Driver"
        assert meta["database_url_masked"] == "postgresql+psycopg://host/db"
        assert meta["server_name"] == "myserver"


@pytest.mark.unit
class TestFormatMigrateMetadata:
    """Tests for _format_migrate_metadata()."""

    def test_empty_for_non_migrate_without_init_version(self):
        formatter = JsonFormatter()
        result = _make_result()
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal
        meta = formatter._format_migrate_metadata(result, "INFO")
        assert meta == {}

    def test_version_range_for_migrate_command(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.from_version = "1"
        result.to_version = "5"
        del result.init_version
        del result.journal
        meta = formatter._format_migrate_metadata(result, "MIGRATE")
        assert meta["from_version"] == "1"
        assert meta["to_version"] == "5"

    def test_no_version_range_for_non_migrate(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.from_version = "1"
        result.to_version = "5"
        del result.init_version
        del result.journal
        meta = formatter._format_migrate_metadata(result, "INFO")
        assert "from_version" not in meta

    def test_baseline_version_fields(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.init_version = "1.0"
        result.description = "My baseline"
        del result.journal
        meta = formatter._format_migrate_metadata(result, "BASELINE")
        assert meta["version"] == "1.0"
        assert meta["baseline_description"] == "My baseline"

    def test_performance_summary_included_when_journal_present(self):
        formatter = JsonFormatter()
        result = _make_result()
        del result.init_version

        migration = Mock()
        migration.script_name = "V1__init.sql"
        result.migrations = [migration]
        result.journal = Mock()
        result.journal.get_migration_performance_summary.return_value = {
            "total_statements": 10,
            "total_execution_time": 500,
            "avg_statement_time": 50,
            "min_statement_time": 5,
            "max_statement_time": 200,
            "slowest_statement": "CREATE TABLE foo",
        }
        result.journal.get_performance_stats_by_object_type.return_value = {}

        meta = formatter._format_migrate_metadata(result, "MIGRATE")
        assert "performance_summary" in meta
        assert meta["performance_summary"]["total_statements"] == 10


@pytest.mark.unit
class TestFormatCleanMetadata:
    """Tests for _format_clean_metadata()."""

    def test_empty_for_non_clean_command(self):
        formatter = JsonFormatter()
        result = _make_result()
        meta = formatter._format_clean_metadata(result, "MIGRATE")
        assert meta == {}

    def test_objects_dropped_for_clean_result(self):
        formatter = JsonFormatter()
        result = Mock(spec=CleanResult)
        result.success = True
        result.error_message = None
        result.get_objects_by_type.return_value = {"TABLE": {"foo", "bar"}, "VIEW": set()}
        meta = formatter._format_clean_metadata(result, "CLEAN")
        assert "objects_dropped" in meta
        assert set(meta["objects_dropped"]["TABLE"]) == {"foo", "bar"}
        assert "VIEW" not in meta["objects_dropped"]  # empty sets excluded

    def test_objects_dropped_empty_when_no_get_objects_by_type(self):
        formatter = JsonFormatter()
        result = Mock(spec=CleanResult)
        result.success = True
        result.error_message = None
        del result.get_objects_by_type
        meta = formatter._format_clean_metadata(result, "CLEAN")
        assert meta["objects_dropped"] == {}


@pytest.mark.unit
class TestFormatDiffMetadata:
    """Tests for _format_diff_metadata()."""

    def test_empty_for_non_diff_command(self):
        formatter = JsonFormatter()
        result = _make_result()
        meta = formatter._format_diff_metadata(result, "MIGRATE")
        assert meta == {}

    def test_comparison_block_present(self):
        formatter = JsonFormatter()
        result = Mock(spec=DiffResult)
        result.success = True
        result.error_message = None
        result.source_type = "snapshot"
        result.target_type = "live"
        result.total_differences = 3
        result.error_count = 1
        result.warning_count = 1
        result.info_count = 1
        result.missing_tables = ["t1"]
        result.extra_tables = []
        result.modified_tables = []
        result.missing_user_defined_types = []
        result.extra_user_defined_types = []
        result.schema_diff = Mock()
        result.schema_diff.modified_tables = []
        result.schema_diff.modified_user_defined_types = []

        meta = formatter._format_diff_metadata(result, "DIFF")
        assert "comparison" in meta
        assert meta["comparison"]["source_type"] == "snapshot"
        assert meta["comparison"]["total_differences"] == 3

    def test_summary_block_counts(self):
        formatter = JsonFormatter()
        result = Mock(spec=DiffResult)
        result.success = True
        result.error_message = None
        result.source_type = "s"
        result.target_type = "t"
        result.total_differences = 0
        result.error_count = 0
        result.warning_count = 0
        result.info_count = 0
        result.missing_tables = ["t1", "t2"]
        result.extra_tables = ["t3"]
        result.modified_tables = []
        result.missing_user_defined_types = []
        result.extra_user_defined_types = []
        result.schema_diff = Mock()
        result.schema_diff.modified_tables = []
        result.schema_diff.modified_user_defined_types = []

        meta = formatter._format_diff_metadata(result, "DIFF")
        assert meta["summary"]["missing_tables"] == 2
        assert meta["summary"]["extra_tables"] == 1

    def test_modified_tables_empty_list_when_none(self):
        formatter = JsonFormatter()
        result = Mock(spec=DiffResult)
        result.success = True
        result.error_message = None
        result.source_type = "s"
        result.target_type = "t"
        result.total_differences = 0
        result.error_count = 0
        result.warning_count = 0
        result.info_count = 0
        result.missing_tables = []
        result.extra_tables = []
        result.modified_tables = []
        result.missing_user_defined_types = []
        result.extra_user_defined_types = []
        result.schema_diff = None

        meta = formatter._format_diff_metadata(result, "DIFF")
        assert meta["modified_tables"] == []
        assert meta["modified_user_defined_types"] == []


@pytest.mark.unit
class TestFormatMultiCommandMetadata:
    """Tests for _format_multi_command_metadata()."""

    def test_single_command_returns_multi_command_false(self):
        formatter = JsonFormatter()
        result = _make_result()
        total_time, meta = formatter._format_multi_command_metadata(result, "s", "d", 42.0)
        assert meta["multi_command"] is False
        assert total_time == 42.0

    def test_multi_command_sets_commands_array(self):
        formatter = JsonFormatter()
        formatter.using_multi_command = True

        cmd_result = _make_result(success=True)
        cmd_result.warnings = []
        formatter.command_results = [
            {
                "command_type": "MIGRATE",
                "result": cmd_result,
                "execution_time": 10.0,
            }
        ]

        result = _make_result()
        total_time, meta = formatter._format_multi_command_metadata(result, "s", "d", 99.0)

        # `multi_command` mirrors presence of `commands` array — must be True
        # whenever the array is set, even for single-command-via-multi-command.
        assert meta["multi_command"] is True
        assert "commands" in meta
        assert len(meta["commands"]) == 1
        assert meta["command_count"] == 1

    def test_multi_command_accumulates_execution_time(self):
        formatter = JsonFormatter()
        formatter.using_multi_command = True

        r1 = _make_result()
        r1.warnings = []
        r2 = _make_result()
        r2.warnings = []
        formatter.command_results = [
            {"command_type": "MIGRATE", "result": r1, "execution_time": 30.0},
            {"command_type": "INFO", "result": r2, "execution_time": 20.0},
        ]

        result = _make_result()
        total_time, meta = formatter._format_multi_command_metadata(result, "s", "d", 0.0)
        assert total_time == 50.0

    def test_multi_command_overall_failed_if_any_fails(self):
        formatter = JsonFormatter()
        formatter.using_multi_command = True

        r1 = _make_result(success=True)
        r1.warnings = []
        r2 = _make_result(success=False)
        r2.warnings = []
        formatter.command_results = [
            {"command_type": "MIGRATE", "result": r1, "execution_time": 5.0},
            {"command_type": "INFO", "result": r2, "execution_time": 5.0},
        ]

        result = _make_result()
        _total, meta = formatter._format_multi_command_metadata(result, "s", "d", 0.0)
        assert meta["status"] == "FAILED"

    def test_multi_command_flag_mirrors_commands_key_presence(self):
        """Invariant: `multi_command=True` iff `commands` array is set.

        Consumers parse the `commands` array based on the flag; the two must
        agree for any number of commands captured (1, 2, N) in multi-command mode.
        """
        for cmd_count in (1, 2, 5):
            formatter = JsonFormatter()
            formatter.using_multi_command = True
            formatter.command_results = []
            for i in range(cmd_count):
                cmd_result = _make_result(success=True)
                cmd_result.warnings = []
                formatter.command_results.append(
                    {
                        "command_type": "MIGRATE",
                        "result": cmd_result,
                        "execution_time": 1.0,
                    }
                )

            result = _make_result()
            _total, meta = formatter._format_multi_command_metadata(result, "s", "d", 0.0)

            assert meta["multi_command"] is True, f"flag must be True for {cmd_count} cmds"
            assert "commands" in meta, f"commands key must be present for {cmd_count} cmds"
            assert meta["command_count"] == cmd_count


@pytest.mark.unit
class TestSerializeAndWrite:
    """Tests for _serialize_and_write()."""

    def test_returns_valid_json_string(self):
        formatter = JsonFormatter()
        data = {"key": "value", "number": 42}
        json_str = formatter._serialize_and_write(data, "s", "d", None)
        parsed = json.loads(json_str)
        assert parsed["key"] == "value"

    def test_writes_to_file_when_output_file_given(self, tmp_path):
        formatter = JsonFormatter()
        data = {"hello": "world"}
        out = tmp_path / "output.json"
        formatter._serialize_and_write(data, "s", "d", out)
        assert out.exists()
        assert json.loads(out.read_text())["hello"] == "world"

    def test_fallback_on_serialization_error(self):
        formatter = JsonFormatter()

        class Unserializable:
            pass

        data = {"bad": Unserializable()}
        # _json_default converts unknown objects via __dict__ or str(), so
        # the only way to force the fallback is to raise during dumps.
        # We simulate that by patching json.dumps to raise on first call.
        call_count = {"n": 0}
        original_dumps = json.dumps

        def patched_dumps(obj, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise TypeError("not serializable")
            return original_dumps(obj, **kwargs)

        import core.logger.formatters.jsonformatter as mod

        with patch.object(mod.json, "dumps", side_effect=patched_dumps):
            result = formatter._serialize_and_write(data, "myschema", "mydb", None)

        parsed = json.loads(result)
        assert parsed["status"] == "FAILED"
        assert "Failed to serialize JSON log" in parsed["error"]


@pytest.mark.unit
class TestFormatResultDelegation:
    """Integration tests verifying format_result() delegates to private methods."""

    def test_format_result_calls_get_version_info(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        with patch.object(formatter, "_get_version_info", wraps=formatter._get_version_info) as spy:
            formatter.format_result(result, "public", "mydb", "INFO")
            spy.assert_called_once()

    def test_format_result_calls_build_time_metadata(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        with patch.object(
            formatter, "_build_time_metadata", wraps=formatter._build_time_metadata
        ) as spy:
            formatter.format_result(result, "public", "mydb", "INFO")
            spy.assert_called_once_with(result)

    def test_format_result_calls_build_base_metadata(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        with patch.object(
            formatter, "_build_base_metadata", wraps=formatter._build_base_metadata
        ) as spy:
            formatter.format_result(result, "public", "mydb", "INFO")
            spy.assert_called_once_with(result, "public", "mydb")

    def test_format_result_calls_format_migrate_metadata(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        with patch.object(
            formatter, "_format_migrate_metadata", wraps=formatter._format_migrate_metadata
        ) as spy:
            formatter.format_result(result, "public", "mydb", "MIGRATE")
            spy.assert_called_once_with(result, "MIGRATE")

    def test_format_result_calls_format_clean_metadata(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        with patch.object(
            formatter, "_format_clean_metadata", wraps=formatter._format_clean_metadata
        ) as spy:
            formatter.format_result(result, "public", "mydb", "INFO")
            spy.assert_called_once_with(result, "INFO")

    def test_format_result_calls_format_diff_metadata(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        with patch.object(
            formatter, "_format_diff_metadata", wraps=formatter._format_diff_metadata
        ) as spy:
            formatter.format_result(result, "public", "mydb", "INFO")
            spy.assert_called_once_with(result, "INFO")

    def test_format_result_calls_format_multi_command_metadata(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        with patch.object(
            formatter,
            "_format_multi_command_metadata",
            wraps=formatter._format_multi_command_metadata,
        ) as spy:
            formatter.format_result(result, "public", "mydb", "INFO")
            spy.assert_called_once()

    def test_format_result_calls_serialize_and_write(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        with patch.object(
            formatter, "_serialize_and_write", wraps=formatter._serialize_and_write
        ) as spy:
            formatter.format_result(result, "public", "mydb", "INFO")
            spy.assert_called_once()

    def test_format_result_produces_valid_json(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        json_str = formatter.format_result(result, "public", "mydb", "INFO")
        parsed = json.loads(json_str)
        assert parsed["status"] == "SUCCESS"
        assert parsed["schema"] == "public"
        assert parsed["database"] == "mydb"
        assert parsed["log_format_version"] == "1.0"
        assert parsed["multi_command"] is False
        assert "execution_time_ms" in parsed

    def test_format_result_execution_time_present(self):
        formatter = JsonFormatter()
        result = _make_result()
        result.execution_time.return_value = 123.45
        result.warnings = []
        del result.init_version
        del result.from_version
        del result.to_version
        del result.journal

        json_str = formatter.format_result(result, "s", "d", "INFO")
        parsed = json.loads(json_str)
        assert parsed["execution_time_ms"] == 123.45
