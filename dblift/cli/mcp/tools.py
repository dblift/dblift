"""Built-in (OSS) MCP tools."""

from __future__ import annotations

from typing import Any


def register_oss_tools(server: Any) -> None:
    """Register ``info``, ``validate``, ``migrate_dry_run`` and the history resource."""
    for name in ("info", "validate", "migrate_dry_run"):
        server.command_tool(name=name, command="info", description=name, fn=lambda: [])
