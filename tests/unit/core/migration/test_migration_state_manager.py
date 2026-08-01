from pathlib import Path

import pytest

from core.migration.migration import Migration, MigrationType
from core.migration.rules.migration_rules import MigrationRules
from core.migration.state.migration_state_manager import MigrationStateManager
from core.migration.version_utils import compare_versions

pytestmark = [pytest.mark.unit]


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
    def __init__(self, applied_migrations):
        self._applied = applied_migrations

    def get_applied_migrations(self):
        return self._applied


class StubScriptManager:
    def __init__(self, scripts):
        self._scripts = scripts

    def get_all_scripts(self, *_args, **_kwargs):
        return [migration.script_name for migration in self._scripts]

    def load_migration_scripts(self, *_args, **_kwargs):
        return {"SQL": list(self._scripts)}

    @staticmethod
    def compare_versions(v1, v2):
        return compare_versions(v1, v2)

    @staticmethod
    def calculate_checksum(content):
        return content


def _create_versioned_migration(version, installed_rank, success=True):
    migration = Migration(
        script_name=f"V{version.replace('.', '_')}__test.sql",
        content="SELECT 1;",
        version=version,
        description="Test migration",
        type=MigrationType.SQL,
    )
    migration.success = success
    migration.installed_rank = installed_rank
    return migration


def _create_undo_migration(version, installed_rank, success=True):
    migration = Migration(
        script_name=f"U{version.replace('.', '_')}__test.sql",
        content="SELECT 1;",
        version=version,
        description="Undo test migration",
        type=MigrationType.UNDO_SQL,
    )
    migration.success = success
    migration.installed_rank = installed_rank
    return migration


def test_target_version_filter_includes_alphanumeric_numeric_prefix():
    log = DummyLog()
    rules = MigrationRules(log)
    manager = MigrationStateManager(
        log,
        history_manager=StubHistoryManager([]),
        script_manager=StubScriptManager([]),
        migration_rules=rules,
    )

    migration = _create_versioned_migration("8b", installed_rank=1)

    assert manager._passes_filters(migration, "17", None, None, None, None) is True
    assert manager._passes_filters(migration, "12", None, None, None, None) is True
    assert manager._passes_filters(migration, "8", None, None, None, None) is False


@pytest.mark.parametrize("include_reapply", [False, True])
def test_versioned_migration_pending_only_when_not_reapplied(include_reapply):
    version = "1.0.2"
    initial = _create_versioned_migration(version, installed_rank=1, success=True)
    undo = _create_undo_migration(version, installed_rank=2, success=True)
    applied = [initial, undo]

    if include_reapply:
        reapplied = _create_versioned_migration(version, installed_rank=3, success=True)
        applied.append(reapplied)

    log = DummyLog()
    rules = MigrationRules(log)
    script_manager = StubScriptManager(
        [
            _create_versioned_migration(version, installed_rank=99, success=False),
        ]
    )
    history_manager = StubHistoryManager(applied)

    manager = MigrationStateManager(
        log, history_manager=history_manager, script_manager=script_manager, migration_rules=rules
    )

    # Build analysis context similar to production code
    data_service_context = {
        "undone_versions": {version},
        "reapplied_versions": {version} if include_reapply else set(),
    }
    history_analysis = manager._analyse_history(applied, data_service_context)

    pending = manager._compute_pending_migrations(
        scripts_dir=Path("dummy"),
        executed_scripts=history_analysis.executed_scripts,
        applied_migrations=applied,
        undone_versions={version},
        repeatable_checksums=history_analysis.repeatable_checksums,
        recursive=False,
    )

    if include_reapply:
        assert not pending
    else:
        assert len(pending) == 1
        assert pending[0].version == version


class TestLookupChecksum:
    """Tests for _lookup_checksum static method — basename extraction coherence."""

    def test_exact_match(self):
        checksums = {"R__script.sql": "abc123"}
        result = MigrationStateManager._lookup_checksum(checksums, "R__script.sql")
        assert result == "abc123"

    def test_basename_fallback_single_level(self):
        """Single-level directory path falls back to basename."""
        checksums = {"R__script.sql": "abc123"}
        result = MigrationStateManager._lookup_checksum(checksums, "subdir/R__script.sql")
        assert result == "abc123"

    def test_basename_fallback_nested_path(self):
        """Nested path (2+ levels) — the original split('/', 1) bug returned None."""
        checksums = {"R__script.sql": "abc123"}
        result = MigrationStateManager._lookup_checksum(checksums, "migrations/v1/R__script.sql")
        assert result == "abc123"

    def test_not_found(self):
        checksums = {"other.sql": "xyz"}
        result = MigrationStateManager._lookup_checksum(checksums, "R__script.sql")
        assert result is None

    def test_absolute_path_fallback(self):
        """Absolute path — Path('/dir/file/R__script.sql').name → basename lookup."""
        checksums = {"R__script.sql": "abc123"}
        result = MigrationStateManager._lookup_checksum(checksums, "/absolute/dir/R__script.sql")
        assert result == "abc123"

    def test_empty_checksums(self):
        """Empty dict returns None for any script_name."""
        result = MigrationStateManager._lookup_checksum({}, "migrations/v1/R__script.sql")
        assert result is None


class TestIsVersionedPendingNestedPath:
    """Tests for _is_versioned_pending basename extraction (L612 change)."""

    def _make_manager(self):
        log = DummyLog()
        rules = MigrationRules(log)
        script_manager = StubScriptManager([])
        history_manager = StubHistoryManager([])
        return MigrationStateManager(
            log,
            history_manager=history_manager,
            script_manager=script_manager,
            migration_rules=rules,
        )

    def test_nested_path_detected_as_executed_via_basename(self):
        """Nested path script is not pending when executed_scripts has basename only."""
        manager = self._make_manager()
        result = manager._is_versioned_pending(
            script_name="migrations/v1/V001__init.sql",
            version="1",
            executed_scripts={"V001__init.sql"},  # basename only — Path.name must match
            executed_versions=set(),
            undone_versions=set(),
            current_version=None,
            highest_applied_version=None,
            strict_mode=False,
        )
        assert result is False  # Already executed via basename fallback (L612 fix)

    def test_nested_path_pending_when_not_executed(self):
        """Nested path script is pending when absent from executed_scripts entirely."""
        manager = self._make_manager()
        result = manager._is_versioned_pending(
            script_name="migrations/v1/V001__init.sql",
            version="1",
            executed_scripts=set(),
            executed_versions=set(),
            undone_versions=set(),
            current_version=None,
            highest_applied_version=None,
            strict_mode=False,
        )
        assert result is True


class TestIsRepeatablePendingNestedPath:
    """Tests for _is_repeatable_pending with nested paths — exercises _lookup_checksum chain."""

    def _make_manager(self):
        log = DummyLog()
        rules = MigrationRules(log)
        script_manager = StubScriptManager([])
        history_manager = StubHistoryManager([])
        return MigrationStateManager(
            log,
            history_manager=history_manager,
            script_manager=script_manager,
            migration_rules=rules,
        )

    def test_nested_path_not_pending_when_checksum_unchanged(self):
        """Repeatable with nested path not pending when checksum matches basename-keyed entry."""
        manager = self._make_manager()
        migration = Migration(
            script_name="migrations/v1/R__init.sql",
            content="SELECT 1;",
            type=MigrationType.REPEATABLE,
        )
        # Migration.__init__ computes Flyway CRC32(content) — use that as the stored value
        # Stored by basename only (historical pattern without directory prefix)
        checksums = {"R__init.sql": migration.checksum}
        result = manager._is_repeatable_pending(
            "migrations/v1/R__init.sql",
            migration,
            executed_scripts={"migrations/v1/R__init.sql"},
            repeatable_checksums=checksums,
        )
        assert result is False  # Not pending: checksum found via Path.name and matches

    def test_nested_path_pending_when_checksum_changed(self):
        """Repeatable with nested path is pending when checksum changed."""
        manager = self._make_manager()
        migration = Migration(
            script_name="migrations/v1/R__init.sql",
            content="new_content",
            type=MigrationType.REPEATABLE,
        )
        checksums = {"R__init.sql": "old_checksum"}
        result = manager._is_repeatable_pending(
            "migrations/v1/R__init.sql",
            migration,
            executed_scripts={"migrations/v1/R__init.sql"},
            repeatable_checksums=checksums,
        )
        assert result is True  # Pending: checksum changed


class TestIsRepeatablePendingLegacyQualifiedHistory:
    """PR #129 removed the override that stored a directory-qualified
    ``script_name`` for migrations found in a secondary ``--scripts``
    directory, so freshly-loaded migrations now always get the bare
    filename. A history row written *before* that fix (any installation
    using ``--scripts`` prior to this PR) still has the old qualified
    value stored as ``script_name`` (e.g. ``extra-migrations/R__cleanup.sql``).

    Without a basename fallback on the "never executed" check,
    ``_is_repeatable_pending`` treats the exact-match miss between the old
    qualified history row and the new bare script_name as "never executed"
    and re-runs an already-applied repeatable migration on upgrade.

    ``_is_versioned_pending`` already solves the equivalent problem for
    versioned migrations (see "Also check script_name for backward
    compatibility" in its docstring/comments) — this is the same fix for
    the repeatable path.
    """

    def _make_manager(self):
        log = DummyLog()
        rules = MigrationRules(log)
        script_manager = StubScriptManager([])
        history_manager = StubHistoryManager([])
        return MigrationStateManager(
            log,
            history_manager=history_manager,
            script_manager=script_manager,
            migration_rules=rules,
        )

    def test_old_qualified_history_row_not_re_executed_for_bare_fresh_name(self):
        """A repeatable migration already applied under the old scheme must
        not be treated as pending just because the fresh Migration now
        computes a bare script_name."""
        manager = self._make_manager()
        migration = Migration(
            script_name="R__cleanup.sql",  # bare, as computed post-PR#129
            content="SELECT 1;",
            type=MigrationType.REPEATABLE,
        )
        checksums = {"extra-migrations/R__cleanup.sql": migration.checksum}
        result = manager._is_repeatable_pending(
            "R__cleanup.sql",
            migration,
            executed_scripts={"extra-migrations/R__cleanup.sql"},  # old qualified history row
            repeatable_checksums=checksums,
        )
        assert result is False, (
            "An already-applied repeatable migration whose history row still has the "
            "pre-PR#129 directory-qualified script_name must not be re-executed just "
            "because the fresh in-memory Migration now computes the bare filename."
        )

    def test_old_qualified_history_row_with_changed_checksum_is_still_pending(self):
        """The basename fallback must not suppress genuine checksum drift
        detection for a legacy-scheme row."""
        manager = self._make_manager()
        migration = Migration(
            script_name="R__cleanup.sql",
            content="new_content",
            type=MigrationType.REPEATABLE,
        )
        checksums = {"extra-migrations/R__cleanup.sql": "old_checksum"}
        result = manager._is_repeatable_pending(
            "R__cleanup.sql",
            migration,
            executed_scripts={"extra-migrations/R__cleanup.sql"},
            repeatable_checksums=checksums,
        )
        assert result is True  # Pending: checksum changed
