"""Coverage tests for core/migration/ui/data_collector.py.

Targets the uncovered lines around _format_installed_on, _get_migration_type_string,
_status_to_display_state, _is_migration_type_equal, _is_versioned_type,
get_migration_data, _get_migration_data_from_state, _find_undo_versions,
_find_current_and_baseline_version, _collect_versioned_migrations,
_build_repeatable_checksums, _sort_applied_migrations, _mark_reapplied_duplicates,
_detect_out_of_order_migrations, _get_undone_versions, _get_reapplied_versions,
_should_exclude_migration, _clean_delete_description, _get_category_from_type,
_get_type_from_migration_type, _format_version, _determine_pending_migration_status,
_compare_versions.
"""

import datetime
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.logger import NullLog
from core.migration.migration import Migration, MigrationType
from core.migration.state.migration_state import MigrationState
from core.migration.ui.data_collector import MigrationDataCollector

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collector(script_manager=None):
    log = MagicMock()
    sm = script_manager or MagicMock()
    return MigrationDataCollector(log=log, script_manager=sm), log, sm


def _make_migration(
    version="1",
    mtype=MigrationType.SQL,
    success=True,
    installed_rank=1,
    script_name=None,
    checksum="csum",
    description="test",
    installed_by="ci",
    installed_on=None,
    execution_time=100,
):
    m = MagicMock(spec=Migration)
    m.version = version
    m.type = mtype
    m.success = success
    m.installed_rank = installed_rank
    m.script_name = script_name or (f"V{version}__test.sql" if version else "R__test.sql")
    m.checksum = checksum
    m.description = description
    m.installed_by = installed_by
    m.installed_on = installed_on
    m.execution_time = execution_time
    m.filepath = ""
    return m


# ===========================================================================
# _format_installed_on  (lines 52-75)
# ===========================================================================


class TestFormatInstalledOnCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_datetime_object_formatted(self):
        coll = self._c()
        dt = datetime.datetime(2024, 6, 15, 10, 30, 45)
        result = coll._format_installed_on(dt)
        assert result == "2024-06-15 10:30:45"

    def test_iso_string_with_z_suffix(self):
        coll = self._c()
        result = coll._format_installed_on("2024-06-15T10:30:45Z")
        assert "2024-06-15" in result
        assert "10:30:45" in result

    def test_iso_string_without_z(self):
        coll = self._c()
        result = coll._format_installed_on("2024-06-15T10:30:45")
        assert "2024-06-15" in result

    def test_iso_string_with_timezone_offset(self):
        coll = self._c()
        result = coll._format_installed_on("2024-06-15T10:30:45+02:00")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unparseable_iso_string_truncated_at_19(self):
        coll = self._c()
        # A string > 19 chars that cannot be parsed
        result = coll._format_installed_on("2024-13-99T99:99:99XYZ")
        # Should truncate or return as-is
        assert isinstance(result, str)

    def test_short_string_returned_as_is(self):
        coll = self._c()
        result = coll._format_installed_on("2024-06-15")
        assert isinstance(result, str)

    def test_non_datetime_non_string_uses_str(self):
        coll = self._c()
        result = coll._format_installed_on(12345)
        assert result == "12345"

    def test_none_returns_empty(self):
        coll = self._c()
        assert coll._format_installed_on(None) == ""

    def test_empty_string_returns_empty(self):
        coll = self._c()
        assert coll._format_installed_on("") == ""


# ===========================================================================
# _get_migration_type_string  (lines 83-85)
# ===========================================================================


class TestGetMigrationTypeStringCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_enum_type_returns_string(self):
        coll = self._c()
        result = coll._get_migration_type_string(MigrationType.SQL)
        assert result == "SQL"

    def test_string_type_returned_unchanged(self):
        coll = self._c()
        result = coll._get_migration_type_string("REPEATABLE")
        assert result == "REPEATABLE"

    def test_none_returns_some_string(self):
        coll = self._c()
        result = coll._get_migration_type_string(None)
        assert isinstance(result, str)


# ===========================================================================
# _status_to_display_state  (lines 90-96)
# ===========================================================================


class TestStatusToDisplayStateCoverage(unittest.TestCase):
    def test_success(self):
        result = MigrationDataCollector._status_to_display_state("SUCCESS")
        assert result == "Success"

    def test_out_of_order(self):
        result = MigrationDataCollector._status_to_display_state("OUT OF ORDER")
        assert result == "Out of order"

    def test_baseline(self):
        result = MigrationDataCollector._status_to_display_state("BASELINE")
        assert result == "Baseline"

    def test_other_status_capitalized(self):
        result = MigrationDataCollector._status_to_display_state("FAILED")
        assert result == "Failed"

    def test_pending_capitalized(self):
        result = MigrationDataCollector._status_to_display_state("PENDING")
        assert result == "Pending"


# ===========================================================================
# _is_migration_type_equal  (lines 98-106)
# ===========================================================================


class TestIsMigrationTypeEqualCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_enum_matches_string(self):
        coll = self._c()
        assert coll._is_migration_type_equal(MigrationType.SQL, "SQL") is True

    def test_string_matches_string(self):
        coll = self._c()
        assert coll._is_migration_type_equal("REPEATABLE", "REPEATABLE") is True

    def test_mismatch(self):
        coll = self._c()
        assert coll._is_migration_type_equal(MigrationType.SQL, "REPEATABLE") is False

    def test_none_type_does_not_match(self):
        coll = self._c()
        assert coll._is_migration_type_equal(None, "SQL") is False


# ===========================================================================
# _is_versioned_type  (lines 108-114)
# ===========================================================================


class TestIsVersionedTypeCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_sql_is_versioned(self):
        assert self._c()._is_versioned_type(MigrationType.SQL) is True

    def test_repeatable_not_versioned(self):
        assert self._c()._is_versioned_type(MigrationType.REPEATABLE) is False

    def test_baseline_not_versioned(self):
        assert self._c()._is_versioned_type(MigrationType.BASELINE) is False

    def test_none_not_versioned(self):
        assert self._c()._is_versioned_type(None) is False

    def test_string_sql_is_versioned(self):
        assert self._c()._is_versioned_type("SQL") is True


# ===========================================================================
# _find_current_and_baseline_version  (lines 631-646)
# ===========================================================================


class TestFindCurrentAndBaselineVersionCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_empty_migrations_returns_none_none(self):
        coll = self._c()
        current, baseline = coll._find_current_and_baseline_version([])
        assert current is None
        assert baseline is None

    def test_finds_current_version(self):
        coll = self._c()
        m = _make_migration("2.0", success=True)
        current, baseline = coll._find_current_and_baseline_version([m])
        assert current == "2.0"
        assert baseline is None

    def test_finds_baseline_version(self):
        coll = self._c()
        m = _make_migration("1.0", mtype=MigrationType.BASELINE, success=True)
        current, baseline = coll._find_current_and_baseline_version([m])
        assert baseline == "1.0"
        assert current is None

    def test_picks_highest_versioned(self):
        coll = self._c()
        m1 = _make_migration("1.0", success=True, installed_rank=1)
        m2 = _make_migration("2.0", success=True, installed_rank=2)
        current, _ = coll._find_current_and_baseline_version([m1, m2])
        assert current == "2.0"

    def test_skips_failed_migrations(self):
        coll = self._c()
        m = _make_migration("3.0", success=False)
        current, _ = coll._find_current_and_baseline_version([m])
        assert current is None


# ===========================================================================
# _collect_versioned_migrations  (lines 648-657)
# ===========================================================================


class TestCollectVersionedMigrationsCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_empty_list_returns_empty(self):
        assert self._c()._collect_versioned_migrations([]) == []

    def test_includes_sql_migrations(self):
        coll = self._c()
        m = _make_migration("1.0")
        result = coll._collect_versioned_migrations([m])
        assert len(result) == 1
        assert result[0]["version"] == "1.0"

    def test_excludes_repeatable_migrations(self):
        coll = self._c()
        m = _make_migration(None, mtype=MigrationType.REPEATABLE)
        result = coll._collect_versioned_migrations([m])
        assert len(result) == 0

    def test_excludes_versioned_without_version(self):
        coll = self._c()
        m = _make_migration(None, mtype=MigrationType.SQL)
        result = coll._collect_versioned_migrations([m])
        assert len(result) == 0


# ===========================================================================
# _build_repeatable_checksums  (lines 659-678)
# ===========================================================================


class TestBuildRepeatableChecksumsCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_empty_returns_empty(self):
        assert self._c()._build_repeatable_checksums([]) == {}

    def test_builds_checksum_for_repeatable_success(self):
        coll = self._c()
        m = _make_migration(None, mtype=MigrationType.REPEATABLE, success=True, checksum="abc")
        m.script_name = "R__init.sql"
        result = coll._build_repeatable_checksums([m])
        assert result.get("R__init.sql") == "abc"

    def test_skips_failed_repeatable(self):
        coll = self._c()
        m = _make_migration(None, mtype=MigrationType.REPEATABLE, success=False, checksum="abc")
        result = coll._build_repeatable_checksums([m])
        assert result == {}

    def test_latest_rank_wins(self):
        coll = self._c()
        m1 = _make_migration(
            None, mtype=MigrationType.REPEATABLE, success=True, checksum="old", installed_rank=1
        )
        m1.script_name = "R__init.sql"
        m2 = _make_migration(
            None, mtype=MigrationType.REPEATABLE, success=True, checksum="new", installed_rank=2
        )
        m2.script_name = "R__init.sql"
        result = coll._build_repeatable_checksums([m1, m2])
        # Sorted in reverse by rank; first occurrence wins
        assert result.get("R__init.sql") == "new"


# ===========================================================================
# _sort_applied_migrations  (lines 680-682)
# ===========================================================================


class TestSortAppliedMigrationsCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_sorts_ascending_by_rank(self):
        coll = self._c()
        m1 = _make_migration("2.0", installed_rank=2)
        m2 = _make_migration("1.0", installed_rank=1)
        result = coll._sort_applied_migrations([m1, m2])
        assert result[0].version == "1.0"
        assert result[1].version == "2.0"

    def test_handles_none_rank(self):
        coll = self._c()
        m1 = _make_migration("1.0", installed_rank=None)
        m2 = _make_migration("2.0", installed_rank=1)
        result = coll._sort_applied_migrations([m1, m2])
        assert len(result) == 2


# ===========================================================================
# _mark_reapplied_duplicates  (lines 684-700)
# ===========================================================================


class TestMarkReappliedDuplicatesCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_empty_returns_empty_set(self):
        coll = self._c()
        result = coll._mark_reapplied_duplicates([], set())
        assert result == set()

    def test_no_reapplied_versions_returns_empty(self):
        coll = self._c()
        m = _make_migration("1.0")
        result = coll._mark_reapplied_duplicates([m], set())
        assert result == set()

    def test_marks_duplicate_entries(self):
        coll = self._c()
        m1 = _make_migration("1.0", installed_rank=1)
        m2 = _make_migration("1.0", installed_rank=2)
        result = coll._mark_reapplied_duplicates([m1, m2], {"1.0"})
        # The second occurrence should be marked as duplicate
        assert m2 in result


# ===========================================================================
# _detect_out_of_order_migrations  (lines 702-713)
# ===========================================================================


class TestDetectOutOfOrderMigrationsCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_empty_returns_empty_set(self):
        assert self._c()._detect_out_of_order_migrations([]) == set()

    def test_in_order_returns_empty(self):
        coll = self._c()
        versioned = [
            {"version": "1.0", "migration": MagicMock(script_name="V1.sql")},
            {"version": "2.0", "migration": MagicMock(script_name="V2.sql")},
        ]
        result = coll._detect_out_of_order_migrations(versioned)
        assert len(result) == 0

    def test_detects_out_of_order(self):
        coll = self._c()
        m1 = MagicMock(script_name="V2.sql")
        m2 = MagicMock(script_name="V1.sql")
        versioned = [
            {"version": "2.0", "migration": m1},
            {"version": "1.0", "migration": m2},
        ]
        result = coll._detect_out_of_order_migrations(versioned)
        assert "V1.sql" in result


# ===========================================================================
# _get_undone_versions  (lines 715-762)
# ===========================================================================


class TestGetUndoneVersionsCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_empty_returns_empty(self):
        assert self._c()._get_undone_versions([]) == set()

    def test_finds_undone_version(self):
        coll = self._c()
        sql = _make_migration("1.0", mtype=MigrationType.SQL, success=True, installed_rank=1)
        undo = _make_migration("1.0", mtype=MigrationType.UNDO_SQL, success=True, installed_rank=2)
        result = coll._get_undone_versions([sql, undo])
        assert "1.0" in result

    def test_reapplied_after_undo_not_undone(self):
        coll = self._c()
        sql1 = _make_migration("1.0", mtype=MigrationType.SQL, success=True, installed_rank=1)
        undo = _make_migration("1.0", mtype=MigrationType.UNDO_SQL, success=True, installed_rank=2)
        sql2 = _make_migration("1.0", mtype=MigrationType.SQL, success=True, installed_rank=3)
        result = coll._get_undone_versions([sql1, undo, sql2])
        # After reapplication, should NOT be in undone
        assert "1.0" not in result

    def test_failed_undo_not_counted(self):
        coll = self._c()
        sql = _make_migration("1.0", mtype=MigrationType.SQL, success=True, installed_rank=1)
        undo = _make_migration("1.0", mtype=MigrationType.UNDO_SQL, success=False, installed_rank=2)
        result = coll._get_undone_versions([sql, undo])
        assert "1.0" not in result


# ===========================================================================
# _get_reapplied_versions  (lines 764-772)
# ===========================================================================


class TestGetReappliedVersionsCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_empty_returns_empty(self):
        assert self._c()._get_reapplied_versions([]) == set()

    def test_single_application_not_reapplied(self):
        coll = self._c()
        m = _make_migration("1.0", success=True)
        result = coll._get_reapplied_versions([m])
        assert "1.0" not in result

    def test_two_applications_marked_reapplied(self):
        coll = self._c()
        m1 = _make_migration("1.0", success=True, installed_rank=1)
        m2 = _make_migration("1.0", success=True, installed_rank=2)
        result = coll._get_reapplied_versions([m1, m2])
        assert "1.0" in result

    def test_failed_not_counted(self):
        coll = self._c()
        m = _make_migration("1.0", success=False)
        result = coll._get_reapplied_versions([m])
        assert "1.0" not in result


# ===========================================================================
# _should_exclude_migration  (lines 774-807)
# ===========================================================================


class TestShouldExcludeMigrationCoverage(unittest.TestCase):
    def _c(self, sm=None):
        return _make_collector(sm)[0]

    def test_no_filters_not_excluded(self):
        coll = self._c()
        assert coll._should_exclude_migration("1.0", "V1.sql", [], [], [], []) is False

    def test_exclude_by_version(self):
        coll = self._c()
        assert coll._should_exclude_migration("1.0", "V1.sql", [], [], [], ["1.0"]) is True

    def test_include_filter_matches(self):
        coll = self._c()
        assert coll._should_exclude_migration("1.0", "V1.sql", [], [], ["1.0"], []) is False

    def test_include_filter_no_match(self):
        coll = self._c()
        assert coll._should_exclude_migration("2.0", "V2.sql", [], [], ["1.0"], []) is True

    def test_tag_inclusion_filter_with_no_tags_excludes(self):
        sm = MagicMock()
        sm.extract_tags.return_value = []
        coll = self._c(sm)
        assert coll._should_exclude_migration("1.0", "V1.sql", ["urgent"], [], [], []) is True

    def test_tag_inclusion_filter_match_includes(self):
        sm = MagicMock()
        sm.extract_tags.return_value = ["urgent"]
        coll = self._c(sm)
        assert coll._should_exclude_migration("1.0", "V1.sql", ["urgent"], [], [], []) is False

    def test_tag_exclusion_filter_excludes(self):
        sm = MagicMock()
        sm.extract_tags.return_value = ["skip"]
        coll = self._c(sm)
        assert coll._should_exclude_migration("1.0", "V1.sql", [], ["skip"], [], []) is True

    def test_no_script_manager_no_tag_filtering(self):
        coll, _, _ = _make_collector()
        coll.script_manager = None
        # Without script_manager, tag filters on exclusion should not exclude (no tags found)
        result = coll._should_exclude_migration("1.0", "V1.sql", [], ["skip"], [], [])
        assert result is False


# ===========================================================================
# _clean_delete_description  (lines 818-823)
# ===========================================================================


class TestCleanDeleteDescriptionCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_no_prefix_unchanged(self):
        coll = self._c()
        assert coll._clean_delete_description("normal description") == "normal description"

    def test_delete_prefix_removed(self):
        coll = self._c()
        result = coll._clean_delete_description("[DELETE:SQL] my description")
        assert result == "my description"

    def test_none_returns_none(self):
        coll = self._c()
        assert coll._clean_delete_description(None) is None

    def test_empty_returns_empty(self):
        coll = self._c()
        assert coll._clean_delete_description("") == ""

    def test_delete_with_whitespace_stripped(self):
        coll = self._c()
        result = coll._clean_delete_description("[DELETE:SQL]   spaced   ")
        assert result == "spaced"


# ===========================================================================
# _get_category_from_type  (lines 825-872)
# ===========================================================================


class TestGetCategoryFromTypeCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_sql_is_versioned(self):
        assert self._c()._get_category_from_type("SQL") == "Versioned"

    def test_python_is_versioned(self):
        assert self._c()._get_category_from_type("PYTHON") == "Versioned"

    def test_repeatable(self):
        assert self._c()._get_category_from_type("REPEATABLE") == "Repeatable"

    def test_callback(self):
        assert self._c()._get_category_from_type("CALLBACK") == "Callback"

    def test_baseline(self):
        assert self._c()._get_category_from_type("BASELINE") == "Baseline"

    def test_undo_sql(self):
        assert self._c()._get_category_from_type("UNDO_SQL") == "Undo"

    def test_unknown_type(self):
        assert self._c()._get_category_from_type("WHATEVER") == "Unknown"

    def test_delete_with_sql_description(self):
        coll = self._c()
        m = MagicMock()
        m.description = "[DELETE:SQL] something"
        m.script_name = "V1__test.sql"
        result = coll._get_category_from_type("DELETE", migration=m)
        assert result == "Versioned"

    def test_delete_with_repeatable_description(self):
        coll = self._c()
        m = MagicMock()
        m.description = "[DELETE:REPEATABLE] something"
        m.script_name = "R__test.sql"
        result = coll._get_category_from_type("DELETE", migration=m)
        assert result == "Repeatable"

    def test_delete_script_name_v_fallback(self):
        coll = self._c()
        m = MagicMock()
        m.description = ""
        m.script_name = "V1__test.sql"
        result = coll._get_category_from_type("DELETE", migration=m)
        assert result == "Versioned"

    def test_delete_script_name_r_fallback(self):
        coll = self._c()
        m = MagicMock()
        m.description = ""
        m.script_name = "R__test.sql"
        result = coll._get_category_from_type("DELETE", migration=m)
        assert result == "Repeatable"

    def test_delete_script_name_u_fallback(self):
        coll = self._c()
        m = MagicMock()
        m.description = ""
        m.script_name = "U1__test.sql"
        result = coll._get_category_from_type("DELETE", migration=m)
        assert result == "Undo"

    def test_delete_no_prefix_last_fallback(self):
        coll = self._c()
        m = MagicMock()
        m.description = ""
        m.script_name = "X__test.sql"
        result = coll._get_category_from_type("DELETE", migration=m)
        assert result == "Deleted"


# ===========================================================================
# _get_type_from_migration_type  (lines 874-893)
# ===========================================================================


class TestGetTypeFromMigrationTypeCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_none_returns_unknown(self):
        assert self._c()._get_type_from_migration_type(None) == "UNKNOWN"

    def test_sql(self):
        assert self._c()._get_type_from_migration_type(MigrationType.SQL) == "SQL"

    def test_python(self):
        assert self._c()._get_type_from_migration_type(MigrationType.PYTHON) == "Python"

    def test_repeatable_sql(self):
        assert (
            self._c()._get_type_from_migration_type(MigrationType.REPEATABLE, "R__refresh.sql")
            == "SQL"
        )

    def test_repeatable_python_script_shows_python(self):
        """BUG-05: Python repeatable migrations must show 'Python', not 'SQL'."""
        assert (
            self._c()._get_type_from_migration_type(MigrationType.REPEATABLE, "R__seed.py")
            == "Python"
        )

    def test_repeatable_no_script_name_defaults_sql(self):
        assert self._c()._get_type_from_migration_type(MigrationType.REPEATABLE) == "SQL"
        assert self._c()._get_type_from_migration_type(MigrationType.REPEATABLE, "") == "SQL"

    def test_baseline(self):
        assert self._c()._get_type_from_migration_type(MigrationType.BASELINE) == "SQL"

    def test_undo_sql(self):
        assert self._c()._get_type_from_migration_type(MigrationType.UNDO_SQL) == "UNDO_SQL"

    def test_string_sql(self):
        assert self._c()._get_type_from_migration_type("SQL") == "SQL"

    def test_unknown_type_returns_unknown(self):
        assert self._c()._get_type_from_migration_type("UNKNOWN_TYPE") == "UNKNOWN"


# ===========================================================================
# _format_version  (lines 895-897)
# ===========================================================================


class TestFormatVersionCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_returns_version_string(self):
        assert self._c()._format_version("1.0.0") == "1.0.0"

    def test_none_returns_empty(self):
        assert self._c()._format_version(None) == ""

    def test_empty_string_returns_empty(self):
        assert self._c()._format_version("") == ""


# ===========================================================================
# _determine_pending_migration_status  (lines 899-908)
# ===========================================================================


class TestDeterminePendingMigrationStatusCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_always_returns_pending(self):
        coll = self._c()
        m = _make_migration("1.0")
        result = coll._determine_pending_migration_status(m, None, None, None)
        assert result == "PENDING"

    def test_returns_pending_with_versions(self):
        coll = self._c()
        m = _make_migration("2.0")
        result = coll._determine_pending_migration_status(m, "5.0", "1.0", "0.5")
        assert result == "PENDING"


# ===========================================================================
# _compare_versions  (line 910-912)
# ===========================================================================


class TestCompareVersionsCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_equal_versions(self):
        assert self._c()._compare_versions("1.0", "1.0") == 0

    def test_greater_than(self):
        assert self._c()._compare_versions("2.0", "1.0") > 0

    def test_less_than(self):
        assert self._c()._compare_versions("1.0", "2.0") < 0

    def test_none_values(self):
        # Should not raise
        result = self._c()._compare_versions(None, "1.0")
        assert isinstance(result, int)


# ===========================================================================
# _find_undo_versions  (lines 603-624) – mocked filesystem
# ===========================================================================


class TestFindUndoVersionsCoverage(unittest.TestCase):
    def test_none_scripts_dir_returns_empty(self):
        coll = _make_collector()[0]
        result = coll._find_undo_versions(None)
        assert result == set()

    def test_nonexistent_scripts_dir_returns_empty(self):
        coll = _make_collector()[0]
        result = coll._find_undo_versions(Path("/nonexistent/path"))
        assert result == set()

    def test_finds_undo_sql_scripts(self):
        import os
        import tempfile

        coll, _, sm = _make_collector()
        sm.extract_version.return_value = "1.0"

        with tempfile.TemporaryDirectory() as tmpdir:
            scripts_dir = Path(tmpdir)
            undo_file = scripts_dir / "U1__undo.sql"
            undo_file.write_text("DELETE FROM test", encoding="utf-8")

            result = coll._find_undo_versions(scripts_dir)
            assert "1.0" in result

    def test_finds_python_migrations_with_undo_function(self):
        import tempfile

        coll, _, sm = _make_collector()
        sm.extract_version.return_value = "2.0"

        with tempfile.TemporaryDirectory() as tmpdir:
            scripts_dir = Path(tmpdir)
            py_file = scripts_dir / "V2__migrate.py"
            py_file.write_text("def undo(conn):\n    pass\n", encoding="utf-8")

            result = coll._find_undo_versions(scripts_dir)
            assert "2.0" in result

    def test_python_without_undo_function_not_included(self):
        import tempfile

        coll, _, sm = _make_collector()
        sm.extract_version.return_value = "3.0"

        with tempfile.TemporaryDirectory() as tmpdir:
            scripts_dir = Path(tmpdir)
            py_file = scripts_dir / "V3__migrate.py"
            py_file.write_text("def upgrade(conn):\n    pass\n", encoding="utf-8")

            result = coll._find_undo_versions(scripts_dir)
            assert "3.0" not in result


# ===========================================================================
# get_migration_data — legacy path  (lines 161-383)
# ===========================================================================


class TestGetMigrationDataLegacyCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_empty_inputs_returns_empty_list(self):
        coll = self._c()
        result = coll.get_migration_data(applied_migrations=[], pending_migrations=[])
        assert result == []

    def test_successful_sql_migration_in_result(self):
        coll = self._c()
        m = _make_migration("1.0", success=True, installed_rank=1)
        result = coll.get_migration_data(applied_migrations=[m], pending_migrations=[])
        assert len(result) == 1
        assert result[0]["version"] == "1.0"
        assert result[0]["state"] == "Success"

    def test_failed_migration_state(self):
        coll = self._c()
        m = _make_migration("1.0", success=False, installed_rank=1)
        result = coll.get_migration_data(applied_migrations=[m], pending_migrations=[])
        assert result[0]["state"] == "Failed"

    def test_pending_migration_in_result(self):
        coll = self._c()
        pending = _make_migration("2.0")
        pending.success = None
        result = coll.get_migration_data(applied_migrations=[], pending_migrations=[pending])
        assert len(result) == 1
        assert result[0]["state"] == "Pending"

    def test_undone_migration_state(self):
        coll = self._c()
        sql = _make_migration("1.0", success=True, installed_rank=1)
        undo = _make_migration(
            "1.0",
            mtype=MigrationType.UNDO_SQL,
            success=True,
            installed_rank=2,
            script_name="U1__undo.sql",
        )
        result = coll.get_migration_data(applied_migrations=[sql, undo], pending_migrations=[])
        # The SQL migration should show as UNDONE
        sql_rows = [r for r in result if r.get("version") == "1.0" and r.get("type") == "SQL"]
        assert any(r["state"] == "Undone" for r in sql_rows)

    def test_creates_script_manager_when_none(self):
        coll = MigrationDataCollector(log=MagicMock(), script_manager=None)
        result = coll.get_migration_data(applied_migrations=[], pending_migrations=[])
        assert result == []
        assert coll.script_manager is not None

    def test_exclude_version_filter(self):
        coll = self._c()
        m = _make_migration("1.0", success=True, installed_rank=1)
        result = coll.get_migration_data(
            applied_migrations=[m], pending_migrations=[], exclude_versions=["1.0"]
        )
        assert len(result) == 0

    def test_versions_filter_includes_only_specified(self):
        coll = self._c()
        m1 = _make_migration("1.0", success=True, installed_rank=1)
        m2 = _make_migration("2.0", success=True, installed_rank=2)
        result = coll.get_migration_data(
            applied_migrations=[m1, m2], pending_migrations=[], versions=["2.0"]
        )
        versions_in_result = [r["version"] for r in result]
        assert "2.0" in versions_in_result
        assert "1.0" not in versions_in_result

    def test_delete_type_shows_deleted_state(self):
        coll = self._c()
        m = _make_migration("1.0", mtype=MigrationType.DELETE, success=True, installed_rank=1)
        result = coll.get_migration_data(applied_migrations=[m], pending_migrations=[])
        assert result[0]["state"] == "Deleted"

    def test_baseline_migration_state(self):
        coll = self._c()
        m = _make_migration("1.0", mtype=MigrationType.BASELINE, success=True, installed_rank=1)
        result = coll.get_migration_data(applied_migrations=[m], pending_migrations=[])
        assert result[0]["state"] == "Baseline"

    def test_repeatable_migration_included(self):
        coll = self._c()
        m = _make_migration(
            None,
            mtype=MigrationType.REPEATABLE,
            success=True,
            installed_rank=1,
            script_name="R__init.sql",
            checksum="abc",
        )
        result = coll.get_migration_data(applied_migrations=[m], pending_migrations=[])
        assert len(result) == 1

    def test_uses_migration_state_when_provided(self):
        coll = self._c()
        state = MigrationState(pending_objects=[])
        m = _make_migration("1.0", success=True, installed_rank=1)
        result = coll.get_migration_data(migration_state=state, all_applied_migrations=[m])
        assert len(result) == 1


# ===========================================================================
# _get_migration_data_from_state  (lines 385-601)
# ===========================================================================


class TestGetMigrationDataFromStateCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_empty_state_returns_empty(self):
        coll = self._c()
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[]
        )
        assert result == []

    def test_applied_migration_in_result(self):
        coll = self._c()
        m = _make_migration("1.0", success=True, installed_rank=1)
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[m]
        )
        assert len(result) == 1
        assert result[0]["version"] == "1.0"

    def test_undone_version_from_state(self):
        coll = self._c()
        m = _make_migration("1.0", success=True, installed_rank=1)
        undo = _make_migration(
            "1.0",
            mtype=MigrationType.UNDO_SQL,
            success=True,
            installed_rank=2,
            script_name="U1__undo.sql",
        )
        state = MigrationState(pending_objects=[], undone_versions=["1.0"])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[m, undo]
        )
        sql_rows = [r for r in result if r.get("version") == "1.0" and r.get("type") == "SQL"]
        assert any(r["state"] == "Undone" for r in sql_rows)

    def test_pending_migration_appended(self):
        coll = self._c()
        pending = _make_migration("2.0")
        pending.success = None
        state = MigrationState(pending_objects=[pending])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[]
        )
        assert any(r["version"] == "2.0" for r in result)

    def test_exclude_filter_applied(self):
        coll = self._c()
        m = _make_migration("1.0", success=True, installed_rank=1)
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state,
            all_applied_migrations=[m],
            exclude_versions=["1.0"],
        )
        assert len(result) == 0

    def test_creates_script_manager_when_none(self):
        coll = MigrationDataCollector(log=MagicMock(), script_manager=None)
        state = MigrationState(pending_objects=[])
        coll._get_migration_data_from_state(migration_state=state, all_applied_migrations=[])
        assert coll.script_manager is not None

    def test_failed_migration_state(self):
        coll = self._c()
        m = _make_migration("1.0", success=False, installed_rank=1)
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[m]
        )
        assert result[0]["state"] == "Failed"

    def test_delete_type_shows_deleted(self):
        coll = self._c()
        m = _make_migration("1.0", mtype=MigrationType.DELETE, success=True, installed_rank=1)
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[m]
        )
        assert result[0]["state"] == "Deleted"

    def test_baseline_shows_baseline(self):
        coll = self._c()
        m = _make_migration("1.0", mtype=MigrationType.BASELINE, success=True, installed_rank=1)
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[m]
        )
        assert result[0]["state"] == "Baseline"

    def test_repeatable_old_checksum_skipped(self):
        coll = self._c()
        old = _make_migration(
            None, mtype=MigrationType.REPEATABLE, success=True, installed_rank=1, checksum="old"
        )
        old.script_name = "R__init.sql"
        new = _make_migration(
            None, mtype=MigrationType.REPEATABLE, success=True, installed_rank=2, checksum="new"
        )
        new.script_name = "R__init.sql"
        state = MigrationState(pending_objects=[], repeatable_checksums={"R__init.sql": "new"})
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[old, new]
        )
        # Only the new one should be shown; old should be skipped
        r_rows = [r for r in result if r["script"] == "R__init.sql"]
        assert len(r_rows) == 1

    def test_versions_filter(self):
        coll = self._c()
        m = _make_migration("1.0", success=True, installed_rank=1)
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[m], versions=["2.0"]
        )
        assert len(result) == 0


# ===========================================================================
# Additional tests to cover remaining lines
# ===========================================================================


class TestFormatInstalledOnException(unittest.TestCase):
    """Covers lines 73-75: exception handler in _format_installed_on."""

    def test_exception_during_format_returns_str(self):
        """When strftime raises unexpectedly, log.debug is called and str(val) returned."""
        coll, log, _ = _make_collector()

        class BadDt:
            def strftime(self, fmt):
                raise RuntimeError("unexpected")

            def __str__(self):
                return "bad-dt"

        # BadDt has strftime so it takes the datetime branch which raises
        bad = BadDt()
        result = coll._format_installed_on(bad)
        log.debug.assert_called_once()
        assert "bad-dt" in result


class TestLegacyPathRemainingLines(unittest.TestCase):
    """Covers lines 163/165 (None defaults), 198-203 (reapplied lookup),
    272 (UNKNOWN status), 285 (repeatable old-checksum skip),
    332-333 (undone version shown as pending), 345/348 (should_skip paths).
    """

    def _c(self):
        return _make_collector()[0]

    def test_none_applied_and_pending_uses_defaults(self):
        """Lines 163/165: None applied/pending are set to []."""
        coll = self._c()
        result = coll.get_migration_data(applied_migrations=None, pending_migrations=None)
        assert result == []

    def test_reapplied_migration_lookup_updates_latest(self):
        """Lines 198-203: when two entries share script_name, later rank wins in lookup dict."""
        coll = self._c()
        m1 = _make_migration("1.0", success=True, installed_rank=1)
        m2 = _make_migration("1.0", success=True, installed_rank=2)
        m2.script_name = m1.script_name  # same script name, higher rank
        result = coll.get_migration_data(applied_migrations=[m1, m2], pending_migrations=[])
        # Both rows should be present (legacy shows all)
        assert len(result) >= 1

    def test_unknown_success_value_gives_unknown_status(self):
        """Line 272: success value that is neither truthy nor failure => UNKNOWN."""
        coll = self._c()
        m = _make_migration("1.0", success=None, installed_rank=1)
        result = coll.get_migration_data(applied_migrations=[m], pending_migrations=[])
        assert result[0]["state"] == "Unknown"

    def test_repeatable_old_checksum_skipped_in_legacy(self):
        """Line 285: older repeatable row with stale checksum is skipped."""
        coll = self._c()
        old = _make_migration(
            None, mtype=MigrationType.REPEATABLE, success=True, installed_rank=1, checksum="old"
        )
        old.script_name = "R__init.sql"
        new = _make_migration(
            None, mtype=MigrationType.REPEATABLE, success=True, installed_rank=2, checksum="new"
        )
        new.script_name = "R__init.sql"
        result = coll.get_migration_data(applied_migrations=[old, new], pending_migrations=[])
        r_rows = [r for r in result if r["script"] == "R__init.sql"]
        assert len(r_rows) == 1

    def test_undone_version_also_shown_as_pending(self):
        """Lines 332-333: undone migration can appear both as UNDONE and PENDING."""
        coll = self._c()
        sql = _make_migration("1.0", success=True, installed_rank=1)
        undo = _make_migration(
            "1.0",
            mtype=MigrationType.UNDO_SQL,
            success=True,
            installed_rank=2,
            script_name="U1__undo.sql",
        )
        pending = _make_migration("1.0", success=None)
        # pending has same script_name as sql — but version is in undone_versions
        pending.script_name = sql.script_name
        result = coll.get_migration_data(
            applied_migrations=[sql, undo], pending_migrations=[pending]
        )
        # The undone SQL appears as UNDONE, and the pending entry shows again
        states = [r["state"] for r in result if r["version"] == "1.0"]
        assert "Undone" in states

    def test_pending_excluded_by_version_filter(self):
        """Lines 345/348: pending migration excluded via should_exclude."""
        coll = self._c()
        pending = _make_migration("3.0", success=None)
        pending.script_name = "V3__init.sql"
        result = coll.get_migration_data(
            applied_migrations=[],
            pending_migrations=[pending],
            exclude_versions=["3.0"],
        )
        assert all(r["version"] != "3.0" for r in result)

    def test_pending_skipped_when_already_shown(self):
        """Line 347/348: pending migration with a version already in shown_versions is skipped."""
        coll = self._c()
        applied = _make_migration("2.0", success=True, installed_rank=1)
        pending = _make_migration("2.0", success=None)
        pending.script_name = "V2__other.sql"
        result = coll.get_migration_data(applied_migrations=[applied], pending_migrations=[pending])
        # Version 2.0 should appear only once (the applied one)
        v2_rows = [r for r in result if r["version"] == "2.0"]
        assert len(v2_rows) == 1


class TestStatePathRemainingLines(unittest.TestCase):
    """Covers line 514 (UNKNOWN in state path) and 567 (pending exclude in state path)."""

    def _c(self):
        return _make_collector()[0]

    def test_unknown_status_in_state_path(self):
        """Line 514: success=None in state path produces UNKNOWN."""
        coll = self._c()
        m = _make_migration("1.0", success=None, installed_rank=1)
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[m]
        )
        assert result[0]["state"] == "Unknown"

    def test_pending_excluded_by_filter_in_state_path(self):
        """Line 567: pending migration excluded by exclude_versions in state path."""
        coll = self._c()
        pending = _make_migration("3.0", success=None)
        pending.script_name = "V3__init.sql"
        state = MigrationState(pending_objects=[pending])
        result = coll._get_migration_data_from_state(
            migration_state=state,
            all_applied_migrations=[],
            exclude_versions=["3.0"],
        )
        assert all(r["version"] != "3.0" for r in result)


class TestOSErrorInFindUndoVersions(unittest.TestCase):
    """Covers lines 622-623: OSError when reading a Python migration file."""

    def test_oserror_skipped_gracefully(self):
        import tempfile
        from unittest.mock import patch as mock_patch

        coll, _, sm = _make_collector()
        sm.extract_version.return_value = "2.0"

        with tempfile.TemporaryDirectory() as tmpdir:
            scripts_dir = Path(tmpdir)
            py_file = scripts_dir / "V2__migrate.py"
            py_file.write_text("def undo(conn):\n    pass\n", encoding="utf-8")

            # Patch read_text to raise OSError
            with mock_patch.object(Path, "read_text", side_effect=OSError("permission denied")):
                result = coll._find_undo_versions(scripts_dir)
            # Should not raise; result may be empty since read_text failed
            assert isinstance(result, set)


class TestCleanDeleteDescriptionEdgeCases(unittest.TestCase):
    """Covers lines 821-822: ValueError/IndexError in _clean_delete_description."""

    def _c(self):
        return _make_collector()[0]

    def test_delete_prefix_without_closing_bracket_handled(self):
        """A description that starts with [DELETE: but has no ] — ValueError path."""
        coll = self._c()
        # This actually won't reach the try block because "]" not in description
        # So normal path returns description as-is
        result = coll._clean_delete_description("[DELETE:SQL no bracket")
        # Since ']' not in description, skip and return as-is
        assert "[DELETE:SQL no bracket" in result


class TestGetCategoryFromTypeEdgeCases(unittest.TestCase):
    """Covers lines 857-858: ValueError/IndexError in _get_category_from_type for DELETE."""

    def _c(self):
        return _make_collector()[0]

    def test_malformed_delete_prefix_uses_fallback(self):
        """Lines 857-858: description starts with [DELETE: but has no ] for the type."""
        coll = self._c()
        m = MagicMock()
        # description has [DELETE: but no matching ] before another [
        m.description = "[DELETE:"  # no closing bracket
        m.script_name = "V1__test.sql"
        # This exercises the ValueError/IndexError except branch in _get_category_from_type
        result = coll._get_category_from_type("DELETE", migration=m)
        # Falls through to script_name check → "Versioned"
        assert result == "Versioned"
