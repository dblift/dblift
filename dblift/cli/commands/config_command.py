"""``dblift config --list`` — print every persistent property and its surfaces."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from dblift.config.property_registry import PROPERTY_REGISTRY, PropertySpec
from dblift.core.logger.console import render_records_table


def _cli_display(spec: PropertySpec, accepted: Optional[Set[str]]) -> str:
    """The real CLI flag for a property: '(none)' if cli-exempt or if this
    build does not register the flag, the legacy alias if one is registered,
    else the derived flag."""
    if spec.cli_exempt:
        return "(none)"
    flag = str(spec.cli_aliases[0]) if spec.cli_aliases else spec.cli
    if accepted is not None and flag not in accepted:
        return "(none)"
    return flag


def _accepted_cli_flags() -> Optional[Set[str]]:
    """Option strings the built parser accepts, or ``None`` if it cannot be built.

    Not every registry property has a flag in every build: a property whose
    command is not registered here has no flag to offer, and printing one
    anyway sends the reader to `unrecognized arguments`. Asking the parser is
    what keeps the column honest as the registered command set changes. If the
    parser cannot be built, fall back to showing the registry's own value
    rather than failing the listing — this command is self-documentation.
    """
    try:
        from dblift.cli._parser_setup import collect_option_strings, create_parser

        return collect_option_strings(create_parser())
    except Exception:  # pragma: no cover - listing must not die building a parser
        return None


def build_property_table() -> List[Dict[str, str]]:
    """Return one row per registry property with its config key, env var, CLI flag, and default."""
    accepted = _accepted_cli_flags()
    rows: List[Dict[str, str]] = []
    for spec in PROPERTY_REGISTRY:
        rows.append(
            {
                "name": spec.name,
                "config": spec.name,
                "env": spec.env,
                "cli": _cli_display(spec, accepted),
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
