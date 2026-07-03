"""Shared infrastructure for cli/handlers/* — context dataclasses + helpers.

Each ``_handle_<command>`` module imports what it needs from here. Kept
intentionally small and free of command-specific logic so that the
per-command files stay focused on their own behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Flyway-compatible migration filename patterns — used by SQL-file validation to
# skip non-migration SQL files when scanning a directory (e.g. leftover
# temp files, schema dumps) so only intentional migration scripts are
# checked. Explicitly-listed files are always validated regardless of name.
_MIGRATION_FILENAME_RE = re.compile(
    r"^[VRUBvrub][\d_.]*__.*\.sql$",
    re.IGNORECASE,
)


def _is_migration_sql_file(path: Path) -> bool:
    """Return True iff the filename matches the Flyway migration naming convention."""
    return bool(_MIGRATION_FILENAME_RE.match(path.name))


def _minimal_result(success: bool) -> Any:
    """Minimal result for handlers that return early without a full result object."""

    class _Result:
        def __init__(self, s: bool) -> None:
            self.success = s

        def execution_time(self) -> int:
            return 0

    return _Result(success)


@dataclass
class CliCommandContext:
    """Context passed to CLI command handlers.

    Groups the 8 shared parameters of ``_handle_*`` functions to avoid
    repeating the same 8-parameter signature across all 12 handlers.
    """

    # Core execution context
    client: Any = None
    args: Any = None
    log: Any = None
    # Scripts configuration
    scripts_dir: Optional[Path] = None
    additional_scripts_dirs: List[Path] = field(default_factory=list)
    recursive: bool = False
    # Migration configuration
    placeholders: Dict[str, Any] = field(default_factory=dict)
    dir_recursive_map: Dict[Path, bool] = field(default_factory=dict)
    # License tier for feature-level gates. Opaque to OSS (see
    # core.seams.tier_resolver) — execute_single_command supplies the real
    # CLI-resolved tier; paid-tier handler tests must pass their own tier
    # explicitly since OSS no longer has a permissive default to fall back on.
    license_tier: Any = None


@dataclass
class ConfigOnlyClient:
    """Config-only stand-in for commands that do not need a live provider."""

    config: Any


ValidateSqlConfigClient = ConfigOnlyClient


def _set_command_completed(log: Any, result: Any, command_type: str) -> None:
    """Helper to report command completion to the logger (eliminates SMELL-04 duplication)."""
    if result is None:
        return
    execution_time = result.execution_time() if hasattr(result, "execution_time") else 0
    success = getattr(result, "success", True)
    status = "completed successfully" if success else "failed"
    log.set_command_completed(
        success=success,
        message=f"Command {command_type.lower()} {status} in {execution_time} ms",
        command_type=command_type,
        result=result,
    )


def emit_rendered_output(
    ctx: "CliCommandContext",
    command_output: Any,
    rendered: str,
    output_format: str,
    output_path: Optional[Path],
    result: Any,
    command_type: str,
) -> None:
    """Dispatch a rendered command output to machine channel, logger, and/or file.

    Shared by extension report handlers that follow the same machine/human/file
    dispatch pattern once the command-specific rendering is done.
    """
    if command_output.is_machine_format:
        command_output.machine(rendered)
    else:
        if output_format == "html":
            if output_path is None:
                command_output.status(rendered)
            # html + output_path: written to file below, nothing logged to console
        else:
            ctx.log.info(rendered)
        _set_command_completed(ctx.log, result, command_type)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")


def _extract_version_filters(args: Any) -> tuple[Any, Any, Any, Any, Any]:
    """Extract version/tag filter arguments common to filtered migration handlers.

    Returns:
        Tuple (target_version, versions, exclude_versions, tags, exclude_tags),
        all defaulting to None if absent from args.
    """
    return (
        getattr(args, "target_version", None),
        getattr(args, "versions", None),
        getattr(args, "exclude_versions", None),
        getattr(args, "tags", None),
        getattr(args, "exclude_tags", None),
    )
