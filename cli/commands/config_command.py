"""``dblift config --list`` — print every persistent property and its surfaces."""

from __future__ import annotations

from typing import Any, Dict, List

from config.property_registry import PROPERTY_REGISTRY, PropertySpec
from core.logger.console import render_records_table


def _cli_display(spec: PropertySpec) -> str:
    """The real CLI flag for a property: '(none)' if cli-exempt, the legacy
    alias if one is registered, else the derived flag."""
    if spec.cli_exempt:
        return "(none)"
    if spec.cli_aliases:
        return str(spec.cli_aliases[0])
    return spec.cli


def build_property_table() -> List[Dict[str, str]]:
    """Return one row per registry property with its config key, env var, CLI flag, and default."""
    rows: List[Dict[str, str]] = []
    for spec in PROPERTY_REGISTRY:
        rows.append(
            {
                "name": spec.name,
                "config": spec.name,
                "env": spec.env,
                "cli": _cli_display(spec),
                "default": "" if spec.default is None else str(spec.default),
            }
        )
    return rows


def run_config_command(args: Any) -> int:
    """Print the property/env/CLI surface table for ``dblift config --list``; return 0."""
    rows = build_property_table()
    table = render_records_table(
        [("PROPERTY", "left"), ("ENV VAR", "left"), ("CLI FLAG", "left")],
        [[r["name"], r["env"], r["cli"]] for r in rows],
        title="dblift configuration properties",
    )
    print(
        table
    )  # lint: allow-print  config --list self-documentation (pre-CommandOutput short-circuit)
    return 0
