"""Header/footer versions preserve history semantics without display analysis."""

from itertools import permutations
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from dblift.core.migration.migration import VERSIONED_SCRIPT_TYPES, MigrationType
from dblift.core.migration.rules.migration_rules import MigrationRules
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.state.migration_data_service import MigrationDataService
from dblift.core.migration.state.migration_state_manager import MigrationStateManager

pytestmark = pytest.mark.unit


def row(version, mtype="SQL", rank=1, success=True):
    return SimpleNamespace(
        version=version,
        type=mtype,
        installed_rank=rank,
        success=success,
        script_name=f"{mtype}{version}__test.sql",
    )


@pytest.fixture
def manager():
    logger = Mock()
    return MigrationStateManager(
        logger, Mock(), MigrationScriptManager(logger), MigrationRules(logger)
    )


def legacy_version(manager, rows):
    """Keep the previous display-analysis route as an independent equivalence oracle."""
    context = MigrationDataService(manager.logger)._build_analysis_context(rows)
    history = manager._analyse_history(rows, context)
    excluded = history.undone_versions - history.reapplied_versions
    return manager.get_current_version(
        [
            migration
            for migration in rows
            if manager._get_type_name(migration) not in VERSIONED_SCRIPT_TYPES
            or str(getattr(migration, "version", "")) not in excluded
        ]
    )


@pytest.mark.parametrize(
    "rows,expected",
    [
        ([], None),
        ([row("3", "BASELINE")], "3"),
        ([row("3", "BASELINE"), row("3", "UNDO_SQL", 2)], "3"),
        ([row("1"), row("2", rank=2), row("2", "UNDO_SQL", 3)], "1"),
        ([row("2"), row("2", "UNDO_SQL", 2), row("2", rank=3)], "2"),
        ([row("2", "UNDO_SQL", 2), row("2", rank=3), row("2", "UNDO_SQL", 4)], None),
        ([row("2", rank=2), row("2", "UNDO_SQL", 2)], None),
        ([row("2", rank=3), row("2", "UNDO_SQL", 0)], None),
        ([row("2", rank=3), row("2", "UNDO_SQL", -1)], None),
        ([row("2", rank=None)], "2"),
        ([row("2", MigrationType.PYTHON), row("2", MigrationType.UNDO_SQL, 2)], None),
        ([row("2", "sql", 3), row("2", "UNDO_SQL", 2)], None),
        ([row("2", rank=3), row("2", "undo_sql", 2)], None),
        ([row("2", rank=3), row("2", SimpleNamespace(value="UNDO_SQL"), 2)], "2"),
        ([row("2"), row("2", SimpleNamespace(name="UNDO_SQL"), 2)], None),
        ([row("1.2.3RC1", rank=9), row("1.2.4", rank=2), row("A", rank=1)], "A"),
        ([row("2"), row("9", "DELETE", 2), row("8", "REPEATABLE", 3)], "2"),
        ([row(None), row("", "UNDO_SQL", 2), row(0, "SQL", 3)], None),
    ],
)
def test_schema_version_matches_display_analysis(manager, rows, expected):
    for ordered in permutations(rows):
        records = list(ordered)
        assert legacy_version(manager, records) == expected
        manager.history_manager.get_applied_migrations.return_value = records
        with (
            patch.object(
                MigrationDataService, "_build_analysis_context", side_effect=AssertionError
            ),
            patch.object(manager, "_analyse_history", side_effect=AssertionError),
        ):
            assert manager.resolve_current_schema_version() == expected


@pytest.mark.parametrize("success", [True, 1, "true", "TRUE", "1", False, 0, "false", "0", None])
def test_success_normalization_for_undo_and_reapply(manager, success):
    successful = success in (True, 1, "true", "TRUE", "1")
    for rows, expected in (
        ([row("2"), row("2", "UNDO_SQL", 2, success)], None if successful else "2"),
        ([row("2", "UNDO_SQL", 2), row("2", rank=3, success=success)], "2" if successful else None),
    ):
        assert legacy_version(manager, rows) == expected
        manager.history_manager.get_applied_migrations.return_value = rows
        assert manager.resolve_current_schema_version() == expected


def test_missing_rank_undo_still_excludes_version(manager):
    rows = [row("2", rank=3), row("2", "UNDO_SQL")]
    del rows[1].installed_rank
    assert legacy_version(manager, rows) is None
    manager.history_manager.get_applied_migrations.return_value = rows
    assert manager.resolve_current_schema_version() is None


@pytest.mark.parametrize(
    "rows,header_version,public_version",
    [
        ([row("3", "BASELINE")], "3", None),
        ([row("1"), row("2", rank=2), row("2", "UNDO_SQL", 3)], "1", "2"),
    ],
)
def test_public_state_version_and_payload_remain_distinct(
    manager, rows, header_version, public_version
):
    manager.history_manager.get_applied_migrations.return_value = rows
    before = manager.build_state(None).to_dict()
    assert before["current_version"] == public_version
    assert manager.resolve_current_schema_version() == header_version
    after = manager.build_state(None).to_dict()
    before.pop("generated_at")
    after.pop("generated_at")
    assert after == before


def test_snapshot_retains_history_while_unsnapshotted_version_reads_fresh(manager):
    manager.history_manager.get_applied_migrations.side_effect = [[row("1")], [row("2")]]
    snapshot = manager.new_read_snapshot()
    assert manager.resolve_current_schema_version(snapshot) == "1"
    assert manager.resolve_current_schema_version(snapshot) == "1"
    assert manager.resolve_current_schema_version() == "2"
    assert manager.history_manager.get_applied_migrations.call_count == 2


def test_history_failure_propagates_and_snapshot_retries(manager):
    manager.history_manager.get_applied_migrations.side_effect = [
        RuntimeError("history unavailable"),
        [],
    ]
    snapshot = manager.new_read_snapshot()
    with pytest.raises(RuntimeError, match="history unavailable"):
        manager.resolve_current_schema_version(snapshot)
    assert manager.resolve_current_schema_version(snapshot) is None
    assert manager.resolve_current_schema_version(snapshot) is None
    assert manager.history_manager.get_applied_migrations.call_count == 2


def test_version_comparison_failure_propagates(manager):
    manager.history_manager.get_applied_migrations.return_value = [row("1"), row("2", rank=2)]
    with patch.object(
        manager.script_manager, "compare_versions", side_effect=ValueError("bad version")
    ):
        with pytest.raises(ValueError, match="bad version"):
            manager.resolve_current_schema_version()
