"""Test helpers: let a mocked state manager answer ``plan_repairs``, and build planned actions."""

from functools import partial
from typing import Any, Dict, List

from dblift.core.migration.state.repair_plan import RepairAction, plan_repairs


def wire_plan_repairs(state_manager: Any) -> Any:
    """Route ``state_manager.plan_repairs`` through its mocked ``build_state`` and catalog."""
    state_manager.plan_repairs.side_effect = partial(plan_repairs, state_manager)
    return state_manager


def as_actions(repairs: List[Dict[str, Any]]) -> List[RepairAction]:
    """Wrap repair dicts as planned actions, each kind being the dict's own ``type``."""
    return [
        RepairAction(kind=repair["type"], script=str(repair.get("script", "")), details=repair)
        for repair in repairs
    ]
