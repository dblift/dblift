"""Test helpers: let a mocked state manager answer ``plan_undo`` with the real selection."""

from functools import partial
from typing import Any
from unittest.mock import patch

from dblift.core.migration.state.undo_plan import plan_undo


def wire_plan_undo(state_manager: Any) -> Any:
    """Route ``state_manager.plan_undo`` through its mocked ``build_state`` and filters."""
    state_manager.plan_undo.side_effect = partial(plan_undo, state_manager)
    return state_manager


def patch_undo_script_lookup(lookup: Any) -> Any:
    """Make ``plan_undo`` resolve undo scripts through ``lookup(migration, state)``.

    The patch lasts until ``patch.stopall()``; the caller's module stops it after each test.
    """
    patch("dblift.core.migration.state.undo_plan._find_undo_script", lookup).start()
    return lookup
