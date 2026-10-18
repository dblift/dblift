"""Test helper: let a mocked state manager answer ``plan_migrate`` with the real selection."""

from functools import partial
from typing import Any

from dblift.core.migration.state.migrate_plan import plan_migrate


def wire_plan_migrate(state_manager: Any) -> Any:
    """Route ``state_manager.plan_migrate`` through its mocked ``build_state`` and filters."""
    state_manager.plan_migrate.side_effect = partial(plan_migrate, state_manager)
    return state_manager
