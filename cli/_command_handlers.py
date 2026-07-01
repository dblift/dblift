"""Façade re-exporting OSS CLI command handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from cli.extensions import load_command_handlers, load_terminal_commands
from cli.handlers._shared import (  # noqa: F401
    _MIGRATION_FILENAME_RE,
    CliCommandContext,
    _extract_version_filters,
    _is_migration_sql_file,
    _minimal_result,
    _set_command_completed,
)
from cli.handlers.baseline import _handle_baseline
from cli.handlers.clean import _handle_clean
from cli.handlers.import_flyway import _handle_import_flyway
from cli.handlers.info import _handle_info, _info_result_to_dict  # noqa: F401
from cli.handlers.migrate import _handle_migrate
from cli.handlers.repair import _handle_repair
from cli.handlers.undo import _handle_undo
from cli.handlers.validate import _handle_validate

_COMMAND_HANDLERS: Dict[str, Callable[[CliCommandContext], Tuple[bool, Any]]] = {
    "migrate": _handle_migrate,
    "undo": _handle_undo,
    "clean": _handle_clean,
    "validate": _handle_validate,
    "info": _handle_info,
    "baseline": _handle_baseline,
    "repair": _handle_repair,
    "import-flyway": _handle_import_flyway,
}

_extension_handlers = load_command_handlers()
_builtin_conflicts = set(_extension_handlers) & set(_COMMAND_HANDLERS)
if _builtin_conflicts:
    raise ValueError(
        f"Extension command handler(s) conflict with builtins: {sorted(_builtin_conflicts)}"
    )
_COMMAND_HANDLERS.update(_extension_handlers)
del _extension_handlers, _builtin_conflicts

_AVAILABLE_COMMANDS = (
    list(_COMMAND_HANDLERS.keys()) + ["db", "config"] + list(load_terminal_commands())
)


def execute_single_command(
    client: Any,
    command: str,
    args: Any,
    log: Any,
    scripts_dir: Optional[Path],
    additional_scripts_dirs: List[Path],
    recursive: bool,
    placeholders: Dict[str, Any],
    dir_recursive_map: Dict[Path, bool],
) -> tuple[bool, Any]:
    """Execute a single command using the DBLift client."""
    handler = _COMMAND_HANDLERS.get(command)
    if handler is None:
        raise ValueError(f"Unknown command: {command}")
    ctx = CliCommandContext(
        client=client,
        args=args,
        log=log,
        scripts_dir=scripts_dir,
        additional_scripts_dirs=additional_scripts_dirs,
        recursive=recursive,
        placeholders=placeholders,
        dir_recursive_map=dir_recursive_map,
    )
    return handler(ctx)


def _validate_migrate_options(cmd_args: Any, parser: Any) -> None:
    """Validate conflicting options for the migrate command."""
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        cmd_args
    )
    if target_version and versions:
        parser.error("Cannot specify both --target-version and --versions")
    if versions and exclude_versions:
        versions_list = [v.strip() for v in versions.split(",")]
        exclude_versions_list = [v.strip() for v in exclude_versions.split(",")]
        if any(v in exclude_versions_list for v in versions_list):
            parser.error("Cannot include and exclude the same version")
    if tags and exclude_tags:
        tags_list = [t.strip() for t in tags.split(",")]
        exclude_tags_list = [t.strip() for t in exclude_tags.split(",")]
        if any(t in exclude_tags_list for t in tags_list):
            parser.error("Cannot include and exclude the same tag")
