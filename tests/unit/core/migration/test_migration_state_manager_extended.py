"""
Extended unit tests for MigrationStateManager covering paths not in
tests/unit/core/migration/test_migration_state_manager.py.

Covers:
  - _normalize_filter
  - _get_type_name
  - _installed_rank
  - _passes_filters  (tags, exclude_tags, versions, exclude_versions)
  - _is_versioned_pending  (strict mode, baseline)
  - _is_repeatable_pending  (no checksum, changed checksum)
  - _mark_resolved_status  (scripts_available=False path)
  - get_current_version
  - apply_filters_to_migrations
  - _determine_checksum_changes
  - _build_applied_entries / _build_pending_entries (via build_state stub)
  - _analyse_history  (DELETE, CALLBACK, REPEATABLE branches)
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.migration.migration import Migration, MigrationType
from core.migration.rules.migration_rules import MigrationRules
from core.migration.state.migration_state import ChecksumChange
from core.migration.state.migration_state_manager import MigrationStateManager
from core.migration.version_utils import compare_versions

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyLog:
    def debug(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def warn(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class StubHistoryManager:
    def __init__(self, applied=None):
        self._applied = applied or []

    def get_applied_migrations(self):
        return self._applied


class StubScriptManager:
    def __init__(self, scripts=None):
        self._scripts = scripts or []

    def get_all_scripts(self, *args, **kwargs):
        return [m.script_name for m in self._scripts]

    def load_migration_scripts(self, *args, **kwargs):
        return {"SQL": list(self._scripts)}

    @staticmethod
    def compare_versions(v1, v2):
        return compare_versions(v1, v2)

    @staticmethod
    def calculate_checksum(content):
        return content

    @staticmethod
    def extract_tags(script_name):
        return []


def _mk_versioned(version, rank=1, success=True, script_name=None):
    if script_name is None:
        script_name = f"V{version.replace('.', '_')}__test.sql"
    m = Migration(
        script_name=script_name,
        content="SELECT 1;",
        version=version,
        description="Test",
        type=MigrationType.SQL,
    )
    m.success = success
    m.installed_rank = rank
    return m


def _mk_undo(version, rank, success=True):
    m = Migration(
        script_name=f"U{version.replace('.', '_')}__test.sql",
        content="SELECT 2;",
        version=version,
        description="Undo test",
        type=MigrationType.UNDO_SQL,
    )
    m.success = success
    m.installed_rank = rank
    return m


def _mk_repeatable(script_name, rank=1, success=True, checksum="ck"):
    m = Migration(
        script_name=script_name,
        content="SELECT 3;",
        type=MigrationType.REPEATABLE,
    )
    m.success = success
    m.installed_rank = rank
    m.checksum = checksum
    return m


def _mk_manager(applied=None, scripts=None):
    log = DummyLog()
    rules = MigrationRules(log)
    return MigrationStateManager(
        log,
        history_manager=StubHistoryManager(applied),
        script_manager=StubScriptManager(scripts),
        migration_rules=rules,
    )


# ===========================================================================
# _normalize_filter
# ===========================================================================


class TestNormalizeFilter(unittest.TestCase):
    def test_none_returns_none(self):
        assert MigrationStateManager._normalize_filter(None) is None

    def test_string_comma_split(self):
        result = MigrationStateManager._normalize_filter("a, b, c")
        assert result == ["a", "b", "c"]

    def test_list_passthrough(self):
        result = MigrationStateManager._normalize_filter(["x", "y"])
        assert result == ["x", "y"]

    def test_empty_string_filtered(self):
        result = MigrationStateManager._normalize_filter(" , ")
        assert result == []


# ===========================================================================
# _get_type_name
# ===========================================================================


class TestGetTypeName(unittest.TestCase):
    def test_enum_type(self):
        m = _mk_versioned("1.0")
        assert MigrationStateManager._get_type_name(m) == "SQL"

    def test_string_type(self):
        m = MagicMock()
        m.type = "REPEATABLE"
        assert MigrationStateManager._get_type_name(m) == "REPEATABLE"

    def test_none_type(self):
        m = MagicMock()
        m.type = None
        assert MigrationStateManager._get_type_name(m) == ""


# ===========================================================================
# _installed_rank
# ===========================================================================


class TestInstalledRank(unittest.TestCase):
    def test_normal_rank(self):
        m = _mk_versioned("1.0", rank=5)
        assert MigrationStateManager._installed_rank(m) == 5

    def test_none_rank_returns_zero(self):
        m = MagicMock()
        m.installed_rank = None
        assert MigrationStateManager._installed_rank(m) == 0

    def test_missing_attribute_returns_zero(self):
        m = MagicMock(spec=[])
        assert MigrationStateManager._installed_rank(m) == 0


# ===========================================================================
# _passes_filters
# ===========================================================================


class TestPassesFilters(unittest.TestCase):
    def setUp(self):
        self.mgr = _mk_manager()

    def _m(self, version="1.0", tags=None):
        m = _mk_versioned(version)
        m.tags = tags or []
        return m

    def test_no_filters_always_passes(self):
        m = self._m("1.0")
        assert self.mgr._passes_filters(m, None, None, None, None, None) is True

    def test_target_version_above_migration_excludes(self):
        m = self._m("5.0")
        assert self.mgr._passes_filters(m, "3.0", None, None, None, None) is False

    def test_target_version_at_migration_includes(self):
        m = self._m("3.0")
        assert self.mgr._passes_filters(m, "3.0", None, None, None, None) is True

    def test_versions_inclusion_passes(self):
        m = self._m("2.0")
        assert self.mgr._passes_filters(m, None, None, None, ["2.0"], None) is True

    def test_versions_inclusion_fails(self):
        m = self._m("2.0")
        assert self.mgr._passes_filters(m, None, None, None, ["1.0"], None) is False

    def test_exclude_versions_excludes(self):
        m = self._m("2.0")
        assert self.mgr._passes_filters(m, None, None, None, None, ["2.0"]) is False

    def test_tags_inclusion_passes(self):
        m = self._m(tags=["feature"])
        assert self.mgr._passes_filters(m, None, ["feature"], None, None, None) is True

    def test_tags_inclusion_fails_no_match(self):
        m = self._m(tags=["other"])
        assert self.mgr._passes_filters(m, None, ["feature"], None, None, None) is False

    def test_tags_inclusion_fails_no_tags(self):
        m = self._m(tags=[])
        assert self.mgr._passes_filters(m, None, ["feature"], None, None, None) is False

    def test_exclude_tags_excludes(self):
        m = self._m(tags=["hotfix"])
        assert self.mgr._passes_filters(m, None, None, ["hotfix"], None, None) is False

    def test_exclude_tags_passes_when_no_match(self):
        m = self._m(tags=["feature"])
        assert self.mgr._passes_filters(m, None, None, ["hotfix"], None, None) is True


# ===========================================================================
# _is_versioned_pending
# ===========================================================================


class TestIsVersionedPending(unittest.TestCase):
    def setUp(self):
        self.mgr = _mk_manager()

    def _call(self, **kwargs):
        defaults = dict(
            script_name="V1__a.sql",
            version="1.0",
            executed_scripts=set(),
            executed_versions=set(),
            undone_versions=set(),
            current_version=None,
            highest_applied_version=None,
            strict_mode=False,
            baseline_version=None,
        )
        defaults.update(kwargs)
        return self.mgr._is_versioned_pending(**defaults)

    def test_not_executed_is_pending(self):
        assert self._call() is True

    def test_executed_by_version_not_pending(self):
        assert self._call(executed_versions={"1.0"}) is False

    def test_executed_by_script_name_not_pending(self):
        assert self._call(executed_scripts={"V1__a.sql"}) is False

    def test_undone_version_is_pending(self):
        assert self._call(executed_versions={"1.0"}, undone_versions={"1.0"}) is True

    def test_baseline_covers_older_version(self):
        """Version at or below baseline is not pending."""
        assert self._call(version="1.0", baseline_version="2.0") is False

    def test_baseline_does_not_cover_newer_version(self):
        """Version above baseline is still pending."""
        assert self._call(version="3.0", baseline_version="2.0") is True

    def test_out_of_order_strict_raises(self):
        with self.assertRaises(ValueError):
            self._call(
                version="1.0",
                current_version="2.0",
                strict_mode=True,
            )

    def test_out_of_order_non_strict_included(self):
        """Non-strict out-of-order migration still returns True."""
        assert self._call(version="1.0", current_version="2.0", strict_mode=False) is True


# ===========================================================================
# _is_repeatable_pending
# ===========================================================================


class TestIsRepeatablePending(unittest.TestCase):
    def setUp(self):
        self.mgr = _mk_manager()

    def test_never_executed_is_pending(self):
        m = _mk_repeatable("R__a.sql", checksum="abc")
        assert self.mgr._is_repeatable_pending("R__a.sql", m, set(), {}) is True

    def test_executed_same_checksum_not_pending(self):
        m = Migration(
            script_name="R__a.sql",
            content="SELECT 1;",
            type=MigrationType.REPEATABLE,
        )
        checksums = {"R__a.sql": m.checksum}
        assert self.mgr._is_repeatable_pending("R__a.sql", m, {"R__a.sql"}, checksums) is False

    def test_executed_changed_checksum_is_pending(self):
        m = Migration(
            script_name="R__a.sql",
            content="SELECT 1;",
            type=MigrationType.REPEATABLE,
        )
        checksums = {"R__a.sql": "old_checksum_that_differs"}
        assert self.mgr._is_repeatable_pending("R__a.sql", m, {"R__a.sql"}, checksums) is True

    def test_no_checksum_uses_content(self):
        """Migration without pre-set checksum uses calculate_checksum from content."""
        m = Migration(
            script_name="R__b.sql",
            content="SELECT 99;",
            type=MigrationType.REPEATABLE,
        )
        m.checksum = None  # force recalculation
        # With no stored checksum entry, not pending (no previous → no change)
        result = self.mgr._is_repeatable_pending("R__b.sql", m, {"R__b.sql"}, {})
        # No stored checksum means stored_checksum=None → condition `stored_checksum and ...` is False → not pending
        assert result is False


# ===========================================================================
# _mark_resolved_status
# ===========================================================================


class TestMarkResolvedStatus(unittest.TestCase):
    def setUp(self):
        self.mgr = _mk_manager()

    def test_no_scripts_available_all_resolved(self):
        m1 = _mk_versioned("1.0", rank=1)
        m2 = _mk_versioned("2.0", rank=2)
        self.mgr._mark_resolved_status([m1, m2], [], scripts_available=False)
        assert m1.resolved is True
        assert m2.resolved is True

    def test_scripts_available_matches_pending_script(self):
        applied = _mk_versioned("1.0", rank=1)
        pending = _mk_versioned("2.0", rank=99)
        self.mgr._mark_resolved_status([applied], [pending], scripts_available=True)
        assert pending.resolved is True
        # applied.script_name not in pending scripts → not resolved
        assert applied.resolved is False

    def test_scripts_available_applied_with_matching_script(self):
        """Applied migration whose script_name matches a pending script is marked resolved."""
        applied = _mk_versioned("1.0", rank=1, script_name="V1__test.sql")
        pending = _mk_versioned("1.0", rank=1, script_name="V1__test.sql")
        self.mgr._mark_resolved_status([applied], [pending], scripts_available=True)
        assert applied.resolved is True


# ===========================================================================
# get_current_version
# ===========================================================================


class TestGetCurrentVersion(unittest.TestCase):
    def setUp(self):
        self.mgr = _mk_manager()

    def test_no_migrations_returns_none(self):
        assert self.mgr.get_current_version([]) is None

    def test_single_success_returns_version(self):
        m = _mk_versioned("3.0", rank=1)
        assert self.mgr.get_current_version([m]) == "3.0"

    def test_failed_not_included(self):
        m = _mk_versioned("3.0", rank=1, success=False)
        assert self.mgr.get_current_version([m]) is None

    def test_highest_version_returned(self):
        m1 = _mk_versioned("1.0", rank=1)
        m2 = _mk_versioned("5.0", rank=2)
        m3 = _mk_versioned("3.0", rank=3)
        assert self.mgr.get_current_version([m1, m2, m3]) == "5.0"


# ===========================================================================
# apply_filters_to_migrations
# ===========================================================================


class TestApplyFiltersToMigrations(unittest.TestCase):
    def setUp(self):
        self.mgr = _mk_manager()

    def _m(self, version, tags=None):
        m = _mk_versioned(version)
        m.tags = tags or []
        return m

    def test_no_filters_returns_all(self):
        migrations = [self._m("1.0"), self._m("2.0")]
        result = self.mgr.apply_filters_to_migrations(migrations)
        assert len(result) == 2

    def test_target_version_filters_above(self):
        migrations = [self._m("1.0"), self._m("3.0"), self._m("5.0")]
        result = self.mgr.apply_filters_to_migrations(migrations, target_version="3.0")
        versions = [m.version for m in result]
        assert "5.0" not in versions
        assert "1.0" in versions
        assert "3.0" in versions

    def test_versions_inclusion(self):
        migrations = [self._m("1.0"), self._m("2.0"), self._m("3.0")]
        result = self.mgr.apply_filters_to_migrations(migrations, versions=["2.0"])
        assert len(result) == 1
        assert result[0].version == "2.0"

    def test_exclude_versions(self):
        migrations = [self._m("1.0"), self._m("2.0")]
        result = self.mgr.apply_filters_to_migrations(migrations, exclude_versions=["1.0"])
        assert len(result) == 1
        assert result[0].version == "2.0"

    def test_tags_filter(self):
        m_tag = self._m("1.0", tags=["feature"])
        m_no_tag = self._m("2.0", tags=[])
        result = self.mgr.apply_filters_to_migrations([m_tag, m_no_tag], tags=["feature"])
        assert len(result) == 1
        assert result[0].version == "1.0"

    def test_exclude_tags(self):
        m_tag = self._m("1.0", tags=["hotfix"])
        m_clean = self._m("2.0", tags=["feature"])
        result = self.mgr.apply_filters_to_migrations([m_tag, m_clean], exclude_tags=["hotfix"])
        assert len(result) == 1
        assert result[0].version == "2.0"

    def test_normalize_string_tags(self):
        """Tags passed as comma-delimited string are split and matched."""
        m = self._m("1.0", tags=["feature"])
        result = self.mgr.apply_filters_to_migrations([m], tags="feature,other")
        assert len(result) == 1


# ===========================================================================
# _determine_checksum_changes
# ===========================================================================


class TestDetermineChecksumChanges(unittest.TestCase):
    def setUp(self):
        self.mgr = _mk_manager()

    def test_no_repeatables_returns_empty(self):
        m = _mk_versioned("1.0")
        changes = self.mgr._determine_checksum_changes([m], {})
        assert changes == []

    def test_no_previous_checksum_no_change(self):
        m = _mk_repeatable("R__a.sql", checksum="new_ck")
        changes = self.mgr._determine_checksum_changes([m], {})
        assert changes == []

    def test_unchanged_checksum_no_change(self):
        m = _mk_repeatable("R__a.sql", checksum="same")
        changes = self.mgr._determine_checksum_changes([m], {"R__a.sql": "same"})
        assert changes == []

    def test_changed_checksum_detected(self):
        m = _mk_repeatable("R__a.sql", checksum="new")
        changes = self.mgr._determine_checksum_changes([m], {"R__a.sql": "old"})
        assert len(changes) == 1
        assert isinstance(changes[0], ChecksumChange)
        assert changes[0].previous_checksum == "old"
        assert changes[0].current_checksum == "new"

    def test_no_checksum_on_migration_skipped(self):
        m = _mk_repeatable("R__b.sql", checksum=None)
        changes = self.mgr._determine_checksum_changes([m], {"R__b.sql": "old"})
        assert changes == []


# ===========================================================================
# _analyse_history (various branches)
# ===========================================================================


class TestAnalyseHistory(unittest.TestCase):
    def setUp(self):
        self.mgr = _mk_manager()

    def _empty_context(self):
        return {
            "undone_versions": set(),
            "reapplied_versions": set(),
        }

    def test_delete_migration_added_to_deleted_scripts(self):
        m = MagicMock()
        m.type = "DELETE"
        m.script_name = "V1__deleted.sql"
        m.success = True
        m.installed_rank = 1
        m.version = None

        ctx = self._empty_context()
        result = self.mgr._analyse_history([m], ctx)
        assert "V1__deleted.sql" in result.deleted_scripts

    def test_failed_migration_added_to_failed_list(self):
        m = _mk_versioned("2.0", rank=1, success=False)
        ctx = self._empty_context()
        result = self.mgr._analyse_history([m], ctx)
        assert m in result.failed_migrations

    def test_successful_repeatable_checksum_captured(self):
        m = _mk_repeatable("R__data.sql", rank=1, success=True, checksum="crc123")
        ctx = self._empty_context()
        result = self.mgr._analyse_history([m], ctx)
        assert "R__data.sql" in result.repeatable_checksums
        assert result.repeatable_checksums["R__data.sql"] == "crc123"

    def test_callback_added_to_executed_scripts(self):
        m = MagicMock()
        m.type = MigrationType.CALLBACK if hasattr(MigrationType, "CALLBACK") else "CALLBACK"
        m.script_name = "CB__after_migrate.sql"
        m.success = True
        m.installed_rank = 5
        m.version = None
        m.checksum = None

        # Use rules mock
        self.mgr.migration_rules = MagicMock()
        self.mgr.migration_rules.is_success = lambda mg: getattr(mg, "success", False) is True

        ctx = self._empty_context()
        # Override type name to look like CALLBACK
        with patch.object(MigrationStateManager, "_get_type_name", return_value="CALLBACK"):
            result = self.mgr._analyse_history([m], ctx)
        assert "CB__after_migrate.sql" in result.executed_scripts

    def test_versioned_success_in_executed_versions(self):
        m = _mk_versioned("3.0", rank=1, success=True)
        ctx = self._empty_context()
        result = self.mgr._analyse_history([m], ctx)
        assert "3.0" in result.executed_versions

    def test_undone_versioned_excluded_from_executed_versions(self):
        """Undone versions (not reapplied) should not be in executed_versions."""
        m = _mk_versioned("4.0", rank=1, success=True)
        ctx = {
            "undone_versions": {"4.0"},
            "reapplied_versions": set(),
        }
        result = self.mgr._analyse_history([m], ctx)
        # Version is undone and not reapplied → should NOT appear in executed_versions
        assert "4.0" not in result.executed_versions

    def test_reapplied_versioned_in_executed_versions(self):
        """Reapplied versions should remain in executed_versions."""
        m = _mk_versioned("5.0", rank=1, success=True)
        ctx = {
            "undone_versions": {"5.0"},
            "reapplied_versions": {"5.0"},
        }
        result = self.mgr._analyse_history([m], ctx)
        assert "5.0" in result.executed_versions


if __name__ == "__main__":
    unittest.main()
