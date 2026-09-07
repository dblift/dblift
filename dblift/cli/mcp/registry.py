"""Discover MCP tool registrars contributed by installed add-on packages.

Each ``dblift.mcp_tools`` entry point resolves to ``register(server) -> None``,
which receives the :class:`dblift.cli.mcp.server.DbliftMcpServer` and calls
``server.command_tool(...)`` for every tool it contributes. OSS declares the
group empty; the built-in tools are registered by :mod:`dblift.cli.mcp.tools`.
"""

from __future__ import annotations

import os
from importlib.metadata import entry_points
from typing import Any, Callable, Dict, List

MCP_TOOLS_ENTRY_POINT_GROUP = "dblift.mcp_tools"

ToolRegistrar = Callable[[Any], None]


def load_mcp_tool_registrars() -> List[ToolRegistrar]:
    """Load every ``dblift.mcp_tools`` registrar, sorted by entry-point name.

    Honours ``DBLIFT_DISABLE_CLI_EXTENSIONS=1`` like the other CLI seams and
    rejects two entry points sharing a name — silently keeping one would make
    the tool list depend on install order.
    """
    if os.environ.get("DBLIFT_DISABLE_CLI_EXTENSIONS") == "1":
        return []
    by_name: Dict[str, ToolRegistrar] = {}
    for entry_point in entry_points(group=MCP_TOOLS_ENTRY_POINT_GROUP):
        if entry_point.name in by_name:
            raise ValueError(f"Duplicate MCP tool registrar: {entry_point.name}")
        by_name[entry_point.name] = entry_point.load()
    return [by_name[name] for name in sorted(by_name)]
