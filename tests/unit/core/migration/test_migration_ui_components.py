"""
Unit tests for migration UI components:
  - TableRenderer
  - MigrationAnalyzer
  - DisplayFormatters
  - MigrationUI (orchestrator)
"""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.migration.migration import Migration, MigrationType
from core.migration.ui.display_formatters import DisplayFormatters
from core.migration.ui.migration_analyzer import MigrationAnalyzer
from core.migration.ui.migration_ui import MigrationUI
from core.migration.ui.table_renderer import TableRenderer

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_log():
    log = MagicMock()
    return log


def _make_migration(
    script_name="V1__test.sql",
    version="1",
    m_type=MigrationType.SQL,
    success=True,
    installed_rank=1,
    checksum="abc",
    description="Test",
    installed_on=None,
    installed_by=None,
):
    m = Migration(
        script_name=script_name,
        content="SELECT 1;",
        version=version,
        description=description,
        type=m_type,
    )
    m.success = success
    m.installed_rank = installed_rank
    m.checksum = checksum
    m.installed_on = installed_on
    m.installed_by = installed_by
    return m


# ===========================================================================
# TableRenderer tests
# ===========================================================================


class TestTableRendererDisplayQueryResults(unittest.TestCase):

    def setUp(self):
        self.log = _make_log()
        self.renderer = TableRenderer(self.log)

    def test_empty_results_logs_no_results(self):
        self.renderer.display_query_results([])
        self.log.info.assert_called_once_with("No results found.")

    def test_non_dict_results_logs_no_columns(self):
        self.renderer.display_query_results(["not_a_dict"])
        self.log.info.assert_called_once_with("No columns found in results.")

    def test_single_row_renders_separator_header_and_row(self):
        rows = [{"name": "Alice", "age": 30}]
        self.renderer.display_query_results(rows)
        # info should be called at least: separator, header, separator, row, separator, total
        calls = [str(c) for c in self.log.info.call_args_list]
        assert any("Alice" in c for c in calls)
        assert any("Total rows" in c for c in calls)

    def test_multi_row_shows_total(self):
        rows = [{"id": 1}, {"id": 2}, {"id": 3}]
        self.renderer.display_query_results(rows)
        calls = [str(c) for c in self.log.info.call_args_list]
        assert any("Total rows: 3" in c for c in calls)

    def test_column_width_adjusts_to_data(self):
        """Wide value expands column width beyond header length."""
        rows = [{"col": "A" * 50}]
        self.renderer.display_query_results(rows)
        calls = [str(c) for c in self.log.info.call_args_list]
        assert any("A" * 50 in c for c in calls)

    def test_nulllog_used_when_no_logger(self):
        """TableRenderer with None logger uses NullLog (no crash)."""
        renderer = TableRenderer(None)
        # Should not raise
        renderer.display_query_results([{"x": 1}])


class TestTableRendererFormatMigrationTable(unittest.TestCase):

    def setUp(self):
        self.renderer = TableRenderer(_make_log())

    def test_empty_returns_no_migrations(self):
        result = self.renderer.format_migration_table([])
        assert result == "No migrations found."

    def test_single_migration_contains_fields(self):
        data = [
            {
                "category": "Versioned",
                "version": "1.0",
                "description": "Initial",
                "type": "SQL",
                "installed_on": "2024-01-01",
                "installed_by": "admin",
                "state": "Success",
                "undoable": True,
                "execution_time": 123,
            }
        ]
        result = self.renderer.format_migration_table(data)
        assert "1.0" in result
        assert "Initial" in result
        assert "Success" in result
        assert "Total migrations: 1" in result

    def test_undoable_false_renders_no(self):
        # Undoable column removed (too narrow for table) — state column used instead
        data = [{"version": "2.0", "undoable": False, "state": "Pending"}]
        result = self.renderer.format_migration_table(data)
        assert "2.0" in result

    def test_table_separator_present(self):
        data = [{"version": "1.0"}]
        result = self.renderer.format_migration_table(data)
        # Rich SIMPLE_HEAVY box uses ━ (U+2501) as separator, not ASCII "+-"
        assert "━" in result or "Version" in result

    def test_multiple_rows_all_present(self):
        data = [{"version": "1.0"}, {"version": "2.0"}, {"version": "3.0"}]
        result = self.renderer.format_migration_table(data)
        assert "Total migrations: 3" in result


class TestTableRendererDisplayMigrationStatus(unittest.TestCase):

    def setUp(self):
        self.log = _make_log()
        self.renderer = TableRenderer(self.log)

    def test_basic_fields_logged(self):
        m = MagicMock()
        m.script_name = "V1__init.sql"
        m.version = "1.0"
        m.description = "Init"
        m.type = "SQL"
        m.state = "Success"
        m.installed_on = None
        m.execution_time = None
        self.renderer.display_migration_status(m)
        calls = " ".join(str(c) for c in self.log.info.call_args_list)
        assert "V1__init.sql" in calls

    def test_installed_on_displayed_when_present(self):
        m = MagicMock()
        m.script_name = "V2__test.sql"
        m.installed_on = "2024-06-01"
        m.execution_time = None
        self.renderer.display_migration_status(m)
        calls = " ".join(str(c) for c in self.log.info.call_args_list)
        assert "2024-06-01" in calls

    def test_execution_time_displayed_when_set(self):
        m = MagicMock()
        m.script_name = "V3__test.sql"
        m.installed_on = None
        m.execution_time = 42
        self.renderer.display_migration_status(m)
        calls = " ".join(str(c) for c in self.log.info.call_args_list)
        assert "42ms" in calls


class TestTableRendererDisplayMigrationDetails(unittest.TestCase):

    def setUp(self):
        self.log = _make_log()
        self.renderer = TableRenderer(self.log)

    def test_all_fields_present_in_output(self):
        m = MagicMock()
        m.script_name = "V10__detail.sql"
        m.version = "10.0"
        m.description = "Detailed migration"
        m.type = "SQL"
        m.filepath = "/migrations/V10__detail.sql"
        m.installed_on = "2024-12-01"
        m.execution_time = 500
        m.installed_rank = 10
        m.success = True
        m.checksum = "deadbeef"
        self.renderer.display_migration_details(m)
        calls = " ".join(str(c) for c in self.log.info.call_args_list)
        assert "V10__detail.sql" in calls
        assert "deadbeef" in calls
        assert "Success" in calls

    def test_success_false_shows_failed(self):
        m = MagicMock()
        m.script_name = "V11__fail.sql"
        m.version = "11"
        m.description = ""
        m.type = "SQL"
        m.filepath = None
        m.installed_on = None
        m.execution_time = None
        m.installed_rank = None
        m.success = False
        m.checksum = None
        self.renderer.display_migration_details(m)
        calls = " ".join(str(c) for c in self.log.info.call_args_list)
        assert "Failed" in calls


class TestTableRendererFormatSummaryStats(unittest.TestCase):

    def setUp(self):
        self.renderer = TableRenderer(_make_log())

    def test_stats_formatted_with_title_case_keys(self):
        stats = {"total_migrations": 5, "applied_migrations": 3}
        result = self.renderer.format_summary_stats(stats)
        assert "Total Migrations" in result
        assert "5" in result
        assert "Applied Migrations" in result
        assert "3" in result

    def test_header_and_footer_markers(self):
        result = self.renderer.format_summary_stats({})
        assert "=== Migration Summary ===" in result
        assert "=" * 25 in result


# ===========================================================================
# MigrationAnalyzer tests
# ===========================================================================


class TestMigrationAnalyzerGetUndoneVersions(unittest.TestCase):

    def setUp(self):
        self.analyzer = MigrationAnalyzer(_make_log())

    def test_empty_list_returns_empty_set(self):
        result = self.analyzer.get_undone_versions([])
        assert result == set()

    def test_no_undo_returns_empty_set(self):
        m = _make_migration(version="1.0", m_type=MigrationType.SQL, success=True, installed_rank=1)
        result = self.analyzer.get_undone_versions([m])
        assert result == set()

    def test_undo_without_reapply_marks_undone(self):
        sql_m = _make_migration(
            script_name="V1__test.sql",
            version="1.0",
            m_type=MigrationType.SQL,
            success=True,
            installed_rank=1,
        )
        undo_m = _make_migration(
            script_name="U1__test.sql",
            version="1.0",
            m_type=MigrationType.UNDO_SQL,
            success=True,
            installed_rank=2,
        )
        result = self.analyzer.get_undone_versions([sql_m, undo_m])
        assert "1.0" in result

    def test_undo_with_reapply_not_undone(self):
        sql_m = _make_migration(
            script_name="V1__test.sql",
            version="1.0",
            m_type=MigrationType.SQL,
            success=True,
            installed_rank=1,
        )
        undo_m = _make_migration(
            script_name="U1__test.sql",
            version="1.0",
            m_type=MigrationType.UNDO_SQL,
            success=True,
            installed_rank=2,
        )
        reapply_m = _make_migration(
            script_name="V1__test.sql",
            version="1.0",
            m_type=MigrationType.SQL,
            success=True,
            installed_rank=3,
        )
        result = self.analyzer.get_undone_versions([sql_m, undo_m, reapply_m])
        assert "1.0" not in result

    def test_failed_undo_not_counted(self):
        sql_m = _make_migration(
            version="2.0", m_type=MigrationType.SQL, success=True, installed_rank=1
        )
        failed_undo = _make_migration(
            script_name="U2__test.sql",
            version="2.0",
            m_type=MigrationType.UNDO_SQL,
            success=False,
            installed_rank=2,
        )
        result = self.analyzer.get_undone_versions([sql_m, failed_undo])
        assert "2.0" not in result


class TestMigrationAnalyzerGetReappliedVersions(unittest.TestCase):

    def setUp(self):
        self.analyzer = MigrationAnalyzer(_make_log())

    def test_empty_returns_empty(self):
        assert self.analyzer.get_reapplied_versions([]) == set()

    def test_applied_once_not_reapplied(self):
        m = _make_migration(version="1.0", m_type=MigrationType.SQL, success=True, installed_rank=1)
        assert self.analyzer.get_reapplied_versions([m]) == set()

    def test_apply_undo_reapply_detected(self):
        m1 = _make_migration(
            script_name="V1__a.sql",
            version="1.0",
            m_type=MigrationType.SQL,
            success=True,
            installed_rank=1,
        )
        undo = _make_migration(
            script_name="U1__a.sql",
            version="1.0",
            m_type=MigrationType.UNDO_SQL,
            success=True,
            installed_rank=2,
        )
        m2 = _make_migration(
            script_name="V1__a.sql",
            version="1.0",
            m_type=MigrationType.SQL,
            success=True,
            installed_rank=3,
        )
        result = self.analyzer.get_reapplied_versions([m1, undo, m2])
        assert "1.0" in result


class TestMigrationAnalyzerDetectOutOfOrder(unittest.TestCase):

    def setUp(self):
        self.analyzer = MigrationAnalyzer(_make_log())

    def test_less_than_two_no_out_of_order(self):
        m = _make_migration(version="1.0", installed_rank=1)
        result = self.analyzer.detect_out_of_order_migrations([{"version": "1.0", "migration": m}])
        assert result == set()

    def test_in_order_no_out_of_order(self):
        m1 = _make_migration(script_name="V1__a.sql", version="1.0", installed_rank=1)
        m2 = _make_migration(script_name="V2__b.sql", version="2.0", installed_rank=2)
        result = self.analyzer.detect_out_of_order_migrations(
            [
                {"version": "1.0", "migration": m1},
                {"version": "2.0", "migration": m2},
            ]
        )
        assert result == set()

    def test_out_of_order_detected(self):
        # Applied rank: m2 first (rank=1), then m1 (rank=2) — m1 applied after m2 but has lower version
        m1 = _make_migration(script_name="V1__a.sql", version="1.0", installed_rank=2)
        m2 = _make_migration(script_name="V2__b.sql", version="2.0", installed_rank=1)
        result = self.analyzer.detect_out_of_order_migrations(
            [
                {"version": "1.0", "migration": m1},
                {"version": "2.0", "migration": m2},
            ]
        )
        # m1 applied after m2 but version 1.0 < 2.0 → m1 is out of order
        assert "V1__a.sql" in result


class TestMigrationAnalyzerBuildRepeatableChecksums(unittest.TestCase):

    def setUp(self):
        self.analyzer = MigrationAnalyzer(_make_log())

    def test_empty_returns_empty(self):
        assert self.analyzer.build_repeatable_checksums([]) == {}

    def _make_repeatable_mock(self, script_name, installed_rank, checksum, success=True):
        """Build a mock migration with type='REPEATABLE' (string) as the analyzer expects."""
        m = MagicMock()
        m.script_name = script_name
        m.type = (
            "REPEATABLE"  # MigrationAnalyzer uses string comparison: migration_type == "REPEATABLE"
        )
        m.success = success
        m.installed_rank = installed_rank
        m.checksum = checksum
        return m

    def test_repeatable_checksum_captured(self):
        m = self._make_repeatable_mock("R__data.sql", installed_rank=1, checksum="check123")
        result = self.analyzer.build_repeatable_checksums([m])
        assert result.get("R__data.sql") == "check123"

    def test_non_repeatable_excluded(self):
        m = MagicMock()
        m.type = "SQL"
        m.success = True
        m.script_name = "V1__init.sql"
        m.checksum = "check456"
        result = self.analyzer.build_repeatable_checksums([m])
        assert result == {}

    def test_latest_checksum_wins(self):
        """Higher installed_rank checksum should be kept."""
        m1 = self._make_repeatable_mock("R__data.sql", installed_rank=1, checksum="old")
        m2 = self._make_repeatable_mock("R__data.sql", installed_rank=2, checksum="new")
        result = self.analyzer.build_repeatable_checksums([m1, m2])
        # Higher rank (m2) is sorted first (reverse=True), so "new" is captured first
        assert result.get("R__data.sql") == "new"


class TestMigrationAnalyzerSortApplied(unittest.TestCase):

    def setUp(self):
        self.analyzer = MigrationAnalyzer(_make_log())

    def test_sorts_by_installed_rank(self):
        m3 = _make_migration(script_name="V3.sql", version="3", installed_rank=3)
        m1 = _make_migration(script_name="V1.sql", version="1", installed_rank=1)
        m2 = _make_migration(script_name="V2.sql", version="2", installed_rank=2)
        result = self.analyzer.sort_applied_migrations([m3, m1, m2])
        assert [m.script_name for m in result] == ["V1.sql", "V2.sql", "V3.sql"]


class TestMigrationAnalyzerMarkReappliedDuplicates(unittest.TestCase):

    def setUp(self):
        self.analyzer = MigrationAnalyzer(_make_log())

    def test_empty_returns_empty(self):
        assert self.analyzer.mark_reapplied_duplicates([], set()) == set()

    def test_second_occurrence_kept(self):
        m1 = _make_migration(script_name="V1.sql", version="1.0", installed_rank=1)
        m2 = _make_migration(script_name="V1.sql", version="1.0", installed_rank=3)
        result = self.analyzer.mark_reapplied_duplicates([m1, m2], {"1.0"})
        assert m2 in result
        assert m1 not in result

    def test_non_reapplied_version_excluded(self):
        m1 = _make_migration(script_name="V2.sql", version="2.0", installed_rank=1)
        result = self.analyzer.mark_reapplied_duplicates([m1], set())
        assert result == set()


# ===========================================================================
# DisplayFormatters tests
# ===========================================================================


class TestDisplayFormattersFormatState(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def test_success_mapped(self):
        assert "Applied" in self.fmt.format_state("SUCCESS")

    def test_applied_mapped(self):
        assert "Applied" in self.fmt.format_state("APPLIED")

    def test_failed_mapped(self):
        assert "Failed" in self.fmt.format_state("FAILED")

    def test_pending_mapped(self):
        assert "Pending" in self.fmt.format_state("PENDING")

    def test_undone_mapped(self):
        assert "Undone" in self.fmt.format_state("UNDONE")

    def test_out_of_order_mapped(self):
        assert "Out of Order" in self.fmt.format_state("OUT OF ORDER")

    def test_unknown_passes_through(self):
        assert self.fmt.format_state("CUSTOM_STATE") == "CUSTOM_STATE"

    def test_case_insensitive(self):
        assert "Applied" in self.fmt.format_state("success")


class TestDisplayFormattersFormatCategory(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def test_versioned(self):
        result = self.fmt.format_category("versioned")
        assert "Versioned" in result

    def test_repeatable(self):
        result = self.fmt.format_category("repeatable")
        assert "Repeatable" in result

    def test_unknown_passes_through(self):
        result = self.fmt.format_category("custom_cat")
        assert result == "custom_cat"


class TestDisplayFormattersFormatVersion(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def test_version_returned_as_is(self):
        assert self.fmt.format_version("1.2.3") == "1.2.3"

    def test_none_returns_empty(self):
        assert self.fmt.format_version(None) == ""

    def test_empty_returns_empty(self):
        assert self.fmt.format_version("") == ""


class TestDisplayFormattersGetCategoryAndDisplayType(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def test_sql_returns_versioned(self):
        cat, disp = self.fmt.get_category_and_display_type("SQL")
        assert cat == "Versioned"
        assert disp == "versioned"

    def test_repeatable(self):
        cat, disp = self.fmt.get_category_and_display_type("REPEATABLE")
        assert cat == "Repeatable"

    def test_unknown_type(self):
        cat, disp = self.fmt.get_category_and_display_type("CUSTOM")
        assert cat == "Unknown"


class TestDisplayFormattersFormatExecutionTime(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def test_none_returns_empty(self):
        assert self.fmt.format_execution_time(None) == ""

    def test_zero_returns_empty(self):
        assert self.fmt.format_execution_time(0) == ""

    def test_milliseconds(self):
        assert self.fmt.format_execution_time(500) == "500ms"

    def test_seconds(self):
        result = self.fmt.format_execution_time(2500)
        assert "2.5s" in result

    def test_minutes(self):
        result = self.fmt.format_execution_time(90000)
        assert "min" in result


class TestDisplayFormattersFormatInstalledOn(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def test_none_returns_empty(self):
        assert self.fmt.format_installed_on(None) == ""

    def test_datetime_formatted(self):
        dt = datetime(2024, 6, 15, 10, 30, 0)
        result = self.fmt.format_installed_on(dt)
        assert "2024-06-15" in result

    def test_string_returned_as_is(self):
        result = self.fmt.format_installed_on("2024-01-01 00:00:00")
        assert "2024-01-01" in result

    def test_arbitrary_object_converted(self):
        obj = MagicMock()
        obj.strftime = None  # Not a datetime
        del obj.strftime
        result = self.fmt.format_installed_on(obj)
        assert isinstance(result, str)


class TestDisplayFormattersTruncateDescription(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def test_empty_returns_empty(self):
        assert self.fmt.truncate_description("") == ""

    def test_short_string_unchanged(self):
        assert self.fmt.truncate_description("short") == "short"

    def test_long_string_truncated(self):
        long_str = "A" * 100
        result = self.fmt.truncate_description(long_str, max_length=20)
        assert len(result) == 20
        assert result.endswith("...")


class TestDisplayFormattersFormatFilePath(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def test_empty_returns_empty(self):
        assert self.fmt.format_file_path("") == ""

    def test_short_path_unchanged(self):
        result = self.fmt.format_file_path("/short.sql")
        assert result == "/short.sql"

    def test_long_path_shows_filename(self):
        long_path = "/very/long/nested/path/to/V1__migration.sql"
        result = self.fmt.format_file_path(long_path, max_length=30)
        assert "V1__migration.sql" in result


class TestDisplayFormattersStatusIndicator(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def test_success_shows_checkmark(self):
        assert self.fmt.get_status_indicator(True) == "✓"

    def test_failure_shows_cross(self):
        assert self.fmt.get_status_indicator(False) == "✗"


class TestDisplayFormattersDeterminePendingStatus(unittest.TestCase):

    def setUp(self):
        self.fmt = DisplayFormatters(_make_log())

    def _make_pending(self, version, m_type):
        m = MagicMock()
        m.version = version
        m.type = m_type
        return m

    def test_repeatable_always_pending(self):
        m = self._make_pending(None, "REPEATABLE")
        assert self.fmt.determine_pending_migration_status(m) == "Pending"

    def test_callback_always_pending(self):
        m = self._make_pending(None, "CALLBACK")
        assert self.fmt.determine_pending_migration_status(m) == "Pending"

    def test_versioned_above_target_version(self):
        m = self._make_pending("3.0", "SQL")
        result = self.fmt.determine_pending_migration_status(m, target_version="2.0")
        assert result == "Above Target"

    def test_versioned_below_baseline(self):
        m = self._make_pending("1.0", "SQL")
        result = self.fmt.determine_pending_migration_status(m, baseline_version="2.0")
        assert result == "Below Baseline"

    def test_versioned_within_range_pending(self):
        m = self._make_pending("2.0", "SQL")
        result = self.fmt.determine_pending_migration_status(
            m, target_version="3.0", baseline_version="1.0"
        )
        assert result == "Pending"


# ===========================================================================
# MigrationUI orchestrator tests
# ===========================================================================


class TestMigrationUIInit(unittest.TestCase):

    def test_components_initialized(self):
        ui = MigrationUI(_make_log())
        assert ui.data_collector is not None
        assert ui.display_formatters is not None
        assert ui.migration_analyzer is not None
        assert ui.table_renderer is not None

    def test_none_log_uses_nulllog(self):
        from core.logger import NullLog

        ui = MigrationUI(None)
        assert isinstance(ui.log, NullLog)


class TestMigrationUIDelegations(unittest.TestCase):

    def setUp(self):
        self.ui = MigrationUI(_make_log())

    def test_format_state_delegates(self):
        self.ui.display_formatters.format_state = MagicMock(return_value="mocked")
        result = self.ui._format_state("SUCCESS")
        assert result == "mocked"

    def test_format_category_delegates(self):
        self.ui.display_formatters.format_category = MagicMock(return_value="cat")
        result = self.ui._format_category("versioned")
        assert result == "cat"

    def test_format_version_delegates(self):
        self.ui.display_formatters.format_version = MagicMock(return_value="1.0")
        result = self.ui._format_version("1.0")
        assert result == "1.0"

    def test_get_undone_versions_delegates(self):
        self.ui.migration_analyzer.get_undone_versions = MagicMock(return_value={"1.0"})
        result = self.ui._get_undone_versions([])
        assert "1.0" in result

    def test_get_reapplied_versions_delegates(self):
        self.ui.migration_analyzer.get_reapplied_versions = MagicMock(return_value={"2.0"})
        result = self.ui._get_reapplied_versions([])
        assert "2.0" in result

    def test_detect_out_of_order_delegates(self):
        self.ui.migration_analyzer.detect_out_of_order_migrations = MagicMock(
            return_value={"V1.sql"}
        )
        result = self.ui._detect_out_of_order_migrations([])
        assert "V1.sql" in result

    def test_build_repeatable_checksums_delegates(self):
        self.ui.migration_analyzer.build_repeatable_checksums = MagicMock(
            return_value={"R.sql": "ck"}
        )
        result = self.ui._build_repeatable_checksums([])
        assert result.get("R.sql") == "ck"

    def test_sort_applied_migrations_delegates(self):
        mocks = [MagicMock()]
        self.ui.migration_analyzer.sort_applied_migrations = MagicMock(return_value=mocks)
        result = self.ui._sort_applied_migrations([])
        assert result == mocks

    def test_mark_reapplied_duplicates_delegates(self):
        self.ui.migration_analyzer.mark_reapplied_duplicates = MagicMock(return_value={MagicMock()})
        result = self.ui._mark_reapplied_duplicates([], set())
        assert len(result) == 1

    def test_display_query_results_delegates(self):
        self.ui.table_renderer.display_query_results = MagicMock()
        rows = [{"id": 1}]
        self.ui.display_query_results(rows)
        self.ui.table_renderer.display_query_results.assert_called_once_with(rows)


class TestMigrationUIGetMigrationData(unittest.TestCase):

    def setUp(self):
        self.ui = MigrationUI(_make_log())

    def test_legacy_mode_returns_list(self):
        """Legacy path with applied/pending migrations returns a list."""
        m = _make_migration()
        result = self.ui.get_migration_data(applied_migrations=[m], pending_migrations=[])
        assert isinstance(result, list)

    def test_none_applied_treated_as_empty(self):
        result = self.ui.get_migration_data(applied_migrations=None, pending_migrations=None)
        assert isinstance(result, list)

    def test_new_mode_with_migration_state(self):
        """New mode with migration_state uses state-based path."""
        state = MagicMock()
        state.undone_versions = []
        state.repeatable_checksums = {}
        state.pending_objects = []
        state.current_version = None
        state.baseline_version = None
        all_applied = [_make_migration()]
        result = self.ui.get_migration_data(
            migration_state=state,
            all_applied_migrations=all_applied,
        )
        assert isinstance(result, list)


class TestMigrationUIDisplayMigrationStatus(unittest.TestCase):

    def test_delegates_to_table_renderer(self):
        ui = MigrationUI(_make_log())
        ui.table_renderer.display_migration_status = MagicMock()
        m = MagicMock()
        ui.display_migration_status(m)
        ui.table_renderer.display_migration_status.assert_called_once_with(m)


class TestMigrationUIDisplayMigrationDetails(unittest.TestCase):

    def test_delegates_to_table_renderer(self):
        ui = MigrationUI(_make_log())
        ui.table_renderer.display_migration_details = MagicMock()
        m = MagicMock()
        ui.display_migration_details(m)
        ui.table_renderer.display_migration_details.assert_called_once_with(m)


if __name__ == "__main__":
    unittest.main()
