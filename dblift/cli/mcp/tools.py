"""Built-in MCP tools: the read-only OSS commands as typed tools.

Each ``*_argv`` builder maps tool parameters to the subcommand's flags. They
use builtin annotations only — the server evaluates them when it derives the
tool's input schema.
"""

from __future__ import annotations

from typing import Dict, List

from dblift.cli.mcp.server import DbliftMcpServer

_FILTERS = (
    ("target_version", "--target-version"),
    ("tags", "--tags"),
    ("exclude_tags", "--exclude-tags"),
    ("versions", "--versions"),
    ("exclude_versions", "--exclude-versions"),
)


def _filter_argv(values: Dict[str, "str | List[str] | None"]) -> List[str]:
    argv: List[str] = []
    for key, flag in _FILTERS:
        value = values.get(key)
        if not value:
            continue
        # The CLI flag takes a CSV string; an agent may naturally pass a
        # list instead (a pydantic list-typed argument), so join it here.
        argv += [flag, ",".join(value) if isinstance(value, list) else value]
    return argv


def info_argv(
    *,
    target_version: "str | None" = None,
    tags: "str | list[str] | None" = None,
    exclude_tags: "str | list[str] | None" = None,
    versions: "str | list[str] | None" = None,
    exclude_versions: "str | list[str] | None" = None,
) -> List[str]:
    """Schema history: every migration with its status, checksum and install time."""
    return _filter_argv(locals())


def validate_argv(
    *,
    target_version: "str | None" = None,
    tags: "str | list[str] | None" = None,
    exclude_tags: "str | list[str] | None" = None,
    versions: "str | list[str] | None" = None,
    exclude_versions: "str | list[str] | None" = None,
) -> List[str]:
    """Validate migration scripts against the history (checksums, ordering, missing files)."""
    return _filter_argv(locals())


def migrate_dry_run_argv(
    *,
    target_version: "str | None" = None,
    tags: "str | list[str] | None" = None,
    exclude_tags: "str | list[str] | None" = None,
    versions: "str | list[str] | None" = None,
    exclude_versions: "str | list[str] | None" = None,
    placeholders: "dict[str, str] | None" = None,
) -> List[str]:
    """Show which migrations would be applied. Never writes: ``--dry-run`` is fixed."""
    argv = ["--dry-run", *_filter_argv(locals())]
    if placeholders:
        # `--placeholders` is `nargs="+"` + `action="append"` (see
        # `_make_filter_parent` in `_parser_setup.py`), not a single
        # comma-separated flag — one occurrence per entry is what the parser
        # actually expects.
        for key, value in placeholders.items():
            argv += ["--placeholders", f"{key}={value}"]
    return argv


def register_oss_tools(server: DbliftMcpServer) -> None:
    """Register ``info``, ``validate``, ``migrate_dry_run`` and ``dblift://history``."""
    server.command_tool(
        name="info", command="info", description=str(info_argv.__doc__), fn=info_argv
    )
    server.command_tool(
        name="validate",
        command="validate",
        description=str(validate_argv.__doc__),
        fn=validate_argv,
    )
    server.command_tool(
        name="migrate_dry_run",
        command="migrate",
        description=str(migrate_dry_run_argv.__doc__),
        fn=migrate_dry_run_argv,
    )
    server.command_resource(
        uri="dblift://history",
        name="history",
        description="Migration history as a JSON array (same rows as the info tool).",
        command="info",
        argv=[],
        pick=lambda payload: payload.get("migrations", []),
    )
