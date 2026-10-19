"""``MigrationStateManager.plan_migrate`` selects what migrate runs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.migrate_plan import MigratePlan, StrictModeError
from dblift.core.migration.state.migration_display_state import MigrationDisplayState
from dblift.core.migration.state.migration_state import MigrationEntry, MigrationState
from dblift.core.migration.state.migration_state_manager import MigrationStateManager

PENDING = MigrationDisplayState.PENDING.value


def _migration(version: str) -> SimpleNamespace:
    return SimpleNamespace(
        script_name=f"V{version}__m.sql",
        version=version,
        description="m",
        type=MigrationType.SQL,
        checksum=1,
        tags=[],
    )


def _manager(rows, current_version):
    """A manager whose catalog holds ``rows`` ((migration, status) pairs)."""
    logger = MagicMock()
    manager = MigrationStateManager(logger, MagicMock(), MagicMock(), MagicMock())
    state = MigrationState(
        current_version=current_version,
        pending=[
            MigrationEntry(m.script_name, m.version, "m", "SQL", status, None) for m, status in rows
        ],
        pending_objects=[m for m, _ in rows],
        applied_objects=[],
    )
    manager.build_state = MagicMock(return_value=state)
    return manager, state, logger


def _plan(manager, **overrides):
    kwargs = dict(
        recursive=True,
        additional_dirs=None,
        dir_recursive_map=None,
        target_version=None,
        tags=None,
        exclude_tags=None,
        versions=None,
        exclude_versions=None,
        strict_mode=False,
    )
    kwargs.update(overrides)
    return manager.plan_migrate(Path("/migrations"), **kwargs)


def test_plan_is_the_executable_pending_of_the_state() -> None:
    v3, v4 = _migration("3"), _migration("4")
    manager, state, _ = _manager(
        [(v3, PENDING), (_migration("2"), MigrationDisplayState.SUCCESS.value), (v4, PENDING)],
        current_version="1",
    )
    snapshot = MagicMock()

    plan = _plan(manager, target_version="9", read_snapshot=snapshot)

    assert isinstance(plan, MigratePlan)
    assert plan.state is state
    assert plan.current_version == "1"
    assert plan.pending == tuple(state.executable_pending_objects()) == (v3, v4)
    kwargs = manager.build_state.call_args.kwargs
    assert kwargs["target_version"] == "9"
    assert kwargs["read_snapshot"] is snapshot
    assert "tags" not in kwargs and "versions" not in kwargs


def test_plan_applies_the_tag_and_version_filters() -> None:
    v3, v4 = _migration("3"), _migration("4")
    manager, _, _ = _manager([(v3, PENDING), (v4, PENDING)], current_version="1")

    assert _plan(manager, versions="4").pending == (v4,)
    assert _plan(manager, exclude_versions="4").pending == (v3,)


def test_strict_mode_raises_with_the_exact_message() -> None:
    manager, _, _ = _manager([(_migration("2"), PENDING)], current_version="3")

    with pytest.raises(StrictModeError) as raised:
        _plan(manager, strict_mode=True)

    assert str(raised.value) == (
        "Strict mode: out-of-order migration V2__m.sql "
        "(version 2 <= current version 3). "
        "Renumber the script above 3 or run without --strict to apply it anyway."
    )
    assert raised.value.current_version == "3"


def test_non_strict_logs_the_exact_warning_and_still_plans_it() -> None:
    late = _migration("2")
    manager, _, logger = _manager([(late, PENDING)], current_version="3")

    plan = _plan(manager)

    assert plan.pending == (late,)
    logger.warning.assert_called_once_with(
        "Out-of-order migration V2__m.sql (version 2 <= current version 3). "
        "Applying anyway; use --strict to enforce strict ordering."
    )


def test_in_order_pending_and_empty_schema_are_never_out_of_order() -> None:
    manager, _, logger = _manager([(_migration("4"), PENDING)], current_version="3")
    assert len(_plan(manager, strict_mode=True).pending) == 1

    manager, _, logger = _manager([(_migration("1"), PENDING)], current_version=None)
    assert len(_plan(manager, strict_mode=True).pending) == 1
    logger.warning.assert_not_called()


def test_filtered_out_migration_does_not_trip_strict_ordering() -> None:
    manager, _, _ = _manager(
        [(_migration("2"), PENDING), (_migration("4"), PENDING)], current_version="3"
    )

    assert [m.version for m in _plan(manager, strict_mode=True, versions="4").pending] == ["4"]


def test_versionless_pending_is_skipped_by_the_ordering_check() -> None:
    repeatable = SimpleNamespace(
        script_name="R__v.sql",
        version=None,
        description="v",
        type=MigrationType.SQL,
        checksum=1,
        tags=[],
    )
    manager, _, _ = _manager([(repeatable, PENDING)], current_version="3")

    assert _plan(manager, strict_mode=True).pending == (repeatable,)
