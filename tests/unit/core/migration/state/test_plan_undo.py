"""``MigrationStateManager.plan_undo`` selects what undo reverts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional, Sequence
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.migration.rules.migration_rules import GROUP_TAG_PREFIX, MigrationRules
from dblift.core.migration.state.migration_display_state import MigrationDisplayState
from dblift.core.migration.state.migration_state import MigrationEntry, MigrationState
from dblift.core.migration.state.migration_state_manager import MigrationStateManager
from dblift.core.migration.state.undo_plan import UndoPlan, UndoStep

AVAILABLE = MigrationDisplayState.AVAILABLE.value
PENDING = MigrationDisplayState.PENDING.value


def _applied(
    version: str,
    rank: int,
    *,
    type_=MigrationType.SQL,
    success: bool = True,
    tags: Sequence[str] = (),
) -> SimpleNamespace:
    prefix = "U" if type_ == MigrationType.UNDO_SQL else "V"
    return SimpleNamespace(
        script_name=f"{prefix}{version}__m.sql",
        version=version,
        description="m",
        type=type_,
        checksum=1,
        success=success,
        installed_rank=rank,
        tags=list(tags),
    )


def _undo_script(version: str) -> SimpleNamespace:
    return SimpleNamespace(script_name=f"U{version}__m.sql", version=version, tags=[])


def _manager(
    applied: List[SimpleNamespace],
    undo_versions: Sequence[str],
    *,
    current_version: Optional[str] = "9",
):
    """A manager whose history is ``applied`` and whose catalog holds ``U`` scripts."""
    scripts = [_undo_script(v) for v in undo_versions]
    state = MigrationState(
        pending=[
            MigrationEntry(s.script_name, s.version, "m", "UNDO_SQL", AVAILABLE, None)
            for s in scripts
        ],
        pending_objects=scripts,
        applied_objects=[a for a in applied if a.type != MigrationType.UNDO_SQL],
        all_applied_objects=applied,
    )
    manager = MigrationStateManager(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    manager.build_state = MagicMock(return_value=state)
    manager.get_current_version = MagicMock(return_value=current_version)
    return manager, state, scripts


def _plan(manager, rules=None, **overrides):
    kwargs = dict(
        recursive=True,
        additional_dirs=None,
        dir_recursive_map=None,
        target_version=None,
        tags=None,
        exclude_tags=None,
        versions=None,
        exclude_versions=None,
        migration_rules=rules or MigrationRules(MagicMock()),
    )
    kwargs.update(overrides)
    return manager.plan_undo(Path("/migrations"), **kwargs)


def _versions(plan: UndoPlan) -> List[str]:
    return [step.migration.version for step in plan.steps]


def test_plan_is_the_latest_undoable_migration_with_its_script() -> None:
    v1, v2 = _applied("1", 1), _applied("2", 2)
    manager, state, scripts = _manager([v1, v2], ["1", "2"])
    snapshot = MagicMock()

    plan = _plan(manager, target_version=None, read_snapshot=snapshot)

    assert isinstance(plan, UndoPlan)
    assert plan.state is state
    assert plan.current_version == "9"
    assert plan.steps == (UndoStep(migration=v2, undo_script=scripts[1]),)
    assert plan.selected == (v2,)
    assert plan.refusal is None and plan.missing_undo_script is None
    assert plan.group_additions == () and plan.target_boundary_in_group is False
    kwargs = manager.build_state.call_args.kwargs
    assert kwargs["target_version"] is None
    assert kwargs["read_snapshot"] is snapshot
    assert "tags" not in kwargs and "versions" not in kwargs


def test_current_version_is_read_from_the_applied_objects() -> None:
    v1 = _applied("1", 1)
    manager, state, _ = _manager([v1], ["1"])

    _plan(manager)

    manager.get_current_version.assert_called_once_with(state.applied_objects)


def test_no_history_gives_no_current_version_and_no_steps() -> None:
    manager, _, _ = _manager([], [])

    plan = _plan(manager)

    assert plan.current_version is None
    assert plan.steps == () and plan.selected == () and plan.refusal is None
    manager.get_current_version.assert_not_called()


def test_failed_and_non_versioned_rows_are_not_candidates() -> None:
    v1 = _applied("1", 1)
    failed = _applied("2", 2, success=False)
    repeatable = _applied("3", 3, type_=MigrationType.REPEATABLE)
    manager, _, _ = _manager([v1, failed, repeatable], ["1", "2", "3"])

    assert _versions(_plan(manager)) == ["1"]


def test_tag_filter_selects_every_matching_migration_highest_rank_first() -> None:
    v1 = _applied("1", 1, tags=["feature"])
    v2 = _applied("2", 2, tags=["other"])
    v3 = _applied("3", 3, tags=["feature"])
    manager, _, _ = _manager([v1, v2, v3], ["1", "2", "3"])

    assert _versions(_plan(manager, tags="feature")) == ["3", "1"]
    assert _versions(_plan(manager, exclude_tags="feature")) == ["2"]
    assert _versions(_plan(manager, tags=["FEATURE "])) == ["3", "1"]


def test_an_already_undone_version_is_skipped_without_a_refusal() -> None:
    v1, v2 = _applied("1", 1), _applied("2", 2)
    undo2 = _applied("2", 3, type_=MigrationType.UNDO_SQL)
    manager, _, _ = _manager([v1, v2, undo2], ["1", "2"])

    plan = _plan(manager)

    assert _versions(plan) == ["1"]
    assert plan.refusal is None


def test_a_version_reapplied_after_its_undo_is_planned_once_from_its_latest_row() -> None:
    first = _applied("2", 2)
    undo = _applied("2", 3, type_=MigrationType.UNDO_SQL)
    again = _applied("2", 4)
    v1 = _applied("1", 1)
    manager, _, scripts = _manager([v1, first, undo, again], ["1", "2"])

    plan = _plan(manager)

    assert plan.steps == (UndoStep(migration=again, undo_script=scripts[1]),)


def test_target_version_undoes_everything_above_it_in_out_of_order_history() -> None:
    v3 = _applied("3", 1)
    v2 = _applied("2", 2)
    v4 = _applied("4", 3)
    manager, _, _ = _manager([v3, v2, v4], ["2", "3", "4"])

    plan = _plan(manager, target_version="2")

    assert _versions(plan) == ["4", "3"]
    assert manager.build_state.call_args.kwargs["target_version"] == "2"


def test_target_version_with_nothing_above_it_plans_nothing() -> None:
    manager, _, _ = _manager([_applied("1", 1), _applied("2", 2)], ["1", "2"])

    plan = _plan(manager, target_version="2")

    assert plan.steps == () and plan.selected == () and plan.refusal is None


def test_the_rules_refusal_message_becomes_the_plan_refusal() -> None:
    manager, _, _ = _manager([_applied("1", 1), _applied("2", 2)], ["1", "2"])
    rules = MagicMock()
    rules._is_currently_undone.return_value = False
    rules.should_undo_version.side_effect = lambda version, applied, *, version_ranks: (
        (False, f"Version {version} has already been undone.") if version == "2" else (True, "")
    )

    plan = _plan(manager, rules, target_version="0")

    assert plan.refusal == "Version 2 has already been undone."
    assert plan.steps == () and plan.missing_undo_script is None
    assert plan.group_additions == ()


def test_a_refusal_without_a_message_skips_the_version() -> None:
    manager, _, _ = _manager([_applied("1", 1), _applied("2", 2)], ["1", "2"])
    rules = MagicMock()
    rules._is_currently_undone.return_value = False
    rules.should_undo_version.side_effect = lambda version, applied, *, version_ranks: (
        (False, "") if version == "2" else (True, "")
    )

    plan = _plan(manager, rules, target_version="0")

    assert plan.refusal is None
    assert _versions(plan) == ["1"]


def test_a_missing_undo_script_refuses_the_whole_plan() -> None:
    v1, v2 = _applied("1", 1), _applied("2", 2)
    manager, _, _ = _manager([v1, v2], ["1"])

    plan = _plan(manager, target_version="0")

    assert plan.refusal == "No undo script found for V2__m.sql"
    assert plan.missing_undo_script is v2
    assert plan.steps == ()
    assert plan.selected == (v2, v1)


def test_a_catalog_script_that_is_not_available_does_not_count() -> None:
    v1 = _applied("1", 1)
    manager, state, _ = _manager([v1], ["1"])
    state.pending[0].status = PENDING

    plan = _plan(manager)

    assert plan.refusal == "No undo script found for V1__m.sql"


def _group_history():
    tag = f"{GROUP_TAG_PREFIX}V9"
    return [
        _applied("9_1", 1, tags=[tag]),
        _applied("9_2", 2, tags=[tag]),
        _applied("9_3", 3, tags=[tag]),
    ]


def test_plain_undo_widens_to_the_whole_group() -> None:
    v9_1, v9_2, v9_3 = _group_history()
    manager, _, _ = _manager([v9_1, v9_2, v9_3], ["9_1", "9_2", "9_3"])

    plan = _plan(manager)

    assert _versions(plan) == ["9_3", "9_2", "9_1"]
    assert {m.version for m in plan.group_additions} == {"9_1", "9_2"}
    assert plan.target_boundary_in_group is False


def test_a_target_inside_a_group_widens_to_the_whole_group() -> None:
    v9_1, v9_2, v9_3 = _group_history()
    manager, _, _ = _manager([v9_1, v9_2, v9_3], ["9_1", "9_2", "9_3"])

    plan = _plan(manager, target_version="9_2")

    assert _versions(plan) == ["9_3", "9_2", "9_1"]
    assert {m.version for m in plan.group_additions} == {"9_1", "9_2"}
    assert plan.target_boundary_in_group is True


def test_a_target_outside_the_group_leaves_it_alone() -> None:
    v9_1, v9_2, _ = _group_history()
    manager, _, _ = _manager([v9_1, v9_2], ["9_1", "9_2"])

    plan = _plan(manager, target_version="9_2")

    assert plan.steps == () and plan.group_additions == ()
    assert plan.target_boundary_in_group is False


@pytest.mark.parametrize("values", [None, "", " , "])
def test_blank_tag_filters_do_not_select_every_migration(values) -> None:
    manager, _, _ = _manager([_applied("1", 1), _applied("2", 2)], ["1", "2"])

    assert _versions(_plan(manager, tags=values, exclude_tags=values)) == ["2"]
