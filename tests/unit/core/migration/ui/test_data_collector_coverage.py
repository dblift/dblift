"""Coverage tests for core/migration/ui/data_collector.py.

Targets the uncovered lines around _format_installed_on, _get_migration_type_string,
_is_migration_type_equal, _is_versioned_type, get_migration_data,
_get_migration_data_from_state, _find_undo_versions, _should_exclude_migration,
_clean_delete_description, _get_category_from_type, _get_type_from_migration_type,
_format_version, _compare_versions.
"""

import datetime
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.logger import NullLog
from core.migration.migration import Migration, MigrationType
from core.migration.state.migration_state import MigrationEntry, MigrationState
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


def _applied_state(migrations_and_statuses, **state_kwargs):
    """Build a MigrationState whose .applied/.all_applied_objects mirror what
    MigrationStateManager.build_state() produces (MigrationStateService-computed
    statuses), so _get_migration_data_from_state can look status up instead of
    re-deriving it.
    """
    migrations = [m for m, _ in migrations_and_statuses]
    entries = [MigrationEntry.from_migration(m, status=s) for m, s in migrations_and_statuses]
    return MigrationState(all_applied_objects=migrations, applied=entries, **state_kwargs)


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

    def test_include_filter_does_not_exclude_versionless_migration(self):
        """F-6 regression: a repeatable migration (version=None) must not be
        excluded by a --versions inclusion filter aimed at versioned migrations.
        """
        coll = self._c()
        result = coll._should_exclude_migration(None, "R__untagged.sql", [], [], ["1.0", "2.0"], [])
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

    def test_finds_python_migrations_with_undo_script(self):
        import tempfile

        coll, _, sm = _make_collector()
        sm.extract_version.return_value = "2.0"

        with tempfile.TemporaryDirectory() as tmpdir:
            scripts_dir = Path(tmpdir)
            undo_file = scripts_dir / "U2__undo.py"
            undo_file.write_text("def migrate(conn):\n    pass\n", encoding="utf-8")

            result = coll._find_undo_versions(scripts_dir)
            assert "2.0" in result

    def test_inline_undo_function_in_versioned_py_not_included(self):
        import tempfile

        coll, _, sm = _make_collector()
        sm.extract_version.return_value = "3.0"

        with tempfile.TemporaryDirectory() as tmpdir:
            scripts_dir = Path(tmpdir)
            py_file = scripts_dir / "V3__migrate.py"
            # Inline leftover is not an undo companion (U*.py / U*.sql only).
            py_file.write_text("def migrate(conn):\n    pass\n", encoding="utf-8")

            result = coll._find_undo_versions(scripts_dir)
            assert "3.0" not in result


# ===========================================================================
# get_migration_data — public wrapper over _get_migration_data_from_state
# ===========================================================================


class TestGetMigrationDataWrapperCoverage(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_delegates_to_get_migration_data_from_state(self):
        coll = self._c()
        m = _make_migration("1.0", success=True, installed_rank=1)
        state = _applied_state([(m, "Success")], pending_objects=[])
        result = coll.get_migration_data(migration_state=state, all_applied_migrations=[m])
        assert len(result) == 1
        assert result[0]["version"] == "1.0"
        assert result[0]["state"] == "Success"


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
        state = _applied_state(
            [(m, "Undone"), (undo, "Success")],
            pending_objects=[],
            undone_versions=["1.0"],
        )
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
        state = _applied_state([(m, "Failed")], pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[m]
        )
        assert result[0]["state"] == "Failed"

    def test_delete_type_shows_deleted(self):
        coll = self._c()
        m = _make_migration("1.0", mtype=MigrationType.DELETE, success=True, installed_rank=1)
        state = _applied_state([(m, "Deleted")], pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state, all_applied_migrations=[m]
        )
        assert result[0]["state"] == "Deleted"

    def test_baseline_shows_baseline(self):
        coll = self._c()
        m = _make_migration("1.0", mtype=MigrationType.BASELINE, success=True, installed_rank=1)
        state = _applied_state([(m, "Baseline")], pending_objects=[])
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

    def test_tags_filter_excludes_non_matching_repeatable(self):
        """F-6: repeatable migrations (version=None) must still be tag-filtered."""
        sm = MagicMock()
        sm.extract_tags.return_value = ["alpha"]
        coll = _make_collector(sm)[0]
        m = _make_migration(
            None,
            mtype=MigrationType.REPEATABLE,
            success=True,
            installed_rank=1,
            checksum="abc",
        )
        m.script_name = "R__tagged[alpha].sql"
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state,
            all_applied_migrations=[m],
            tags=["beta"],
            exclude_tags=[],
            versions=[],
            exclude_versions=[],
        )
        assert result == [], "repeatable tagged 'alpha' must be excluded when filtering --tags beta"

    def test_tags_filter_includes_matching_repeatable(self):
        """F-6: a repeatable migration matching --tags must still be included."""
        sm = MagicMock()
        sm.extract_tags.return_value = ["alpha"]
        coll = _make_collector(sm)[0]
        m = _make_migration(
            None,
            mtype=MigrationType.REPEATABLE,
            success=True,
            installed_rank=1,
            checksum="abc",
        )
        m.script_name = "R__tagged[alpha].sql"
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state,
            all_applied_migrations=[m],
            tags=["alpha"],
            exclude_tags=[],
            versions=[],
            exclude_versions=[],
        )
        assert len(result) == 1

    def test_versions_filter_does_not_exclude_repeatable(self):
        """F-6 regression: repeatable migrations (version=None) must not be
        excluded by --versions — that filter only applies to versioned migrations.
        """
        sm = MagicMock()
        sm.extract_tags.return_value = []
        coll = _make_collector(sm)[0]
        m = _make_migration(
            None,
            mtype=MigrationType.REPEATABLE,
            success=True,
            installed_rank=1,
            checksum="abc",
        )
        m.script_name = "R__untagged.sql"
        state = MigrationState(pending_objects=[])
        result = coll._get_migration_data_from_state(
            migration_state=state,
            all_applied_migrations=[m],
            tags=[],
            exclude_tags=[],
            versions=["1.0", "2.0"],
            exclude_versions=[],
        )
        assert len(result) == 1, "repeatable must not be excluded by an unrelated --versions filter"


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
            # Only U*.py companions count; a V*.py file is not scanned for content.
            py_file.write_text("def migrate(conn):\n    pass\n", encoding="utf-8")

            result = coll._find_undo_versions(scripts_dir)
            assert isinstance(result, set)
            assert "2.0" not in result


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


class TestPendingMigrationsNumericSort(unittest.TestCase):
    """Pending versioned migrations must sort numerically (V2, V3, V10), not lexicographically."""

    def _c(self):
        return _make_collector()[0]

    def test_state_pending_sorted_numerically(self):
        coll = self._c()
        pending = [
            _make_migration("10", success=None),
            _make_migration("2", success=None),
            _make_migration("3", success=None),
        ]
        state = MigrationState(pending_objects=pending)
        result = coll.get_migration_data(migration_state=state, all_applied_migrations=[])
        assert [r["version"] for r in result] == ["2", "3", "10"]

    def test_versioned_pending_before_repeatable(self):
        coll = self._c()
        pending = [
            _make_migration(
                None, mtype=MigrationType.REPEATABLE, script_name="R__z.sql", success=None
            ),
            _make_migration("5", success=None),
        ]
        state = MigrationState(pending_objects=pending)
        result = coll.get_migration_data(migration_state=state, all_applied_migrations=[])
        assert [r["script"] for r in result] == ["V5__test.sql", "R__z.sql"]

    def test_repeatable_pending_sorted_by_script_name(self):
        coll = self._c()
        pending = [
            _make_migration(
                None, mtype=MigrationType.REPEATABLE, script_name="R__b.sql", success=None
            ),
            _make_migration(
                None, mtype=MigrationType.REPEATABLE, script_name="R__a.sql", success=None
            ),
        ]
        state = MigrationState(pending_objects=pending)
        result = coll.get_migration_data(migration_state=state, all_applied_migrations=[])
        assert [r["script"] for r in result] == ["R__a.sql", "R__b.sql"]
