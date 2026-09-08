"""Shared infrastructure for cli/handlers/* — context dataclasses + helpers.

Each ``_handle_<command>`` module imports what it needs from here. Kept
intentionally small and free of command-specific logic so that the
per-command files stay focused on their own behaviour.
"""

from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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


def _enum_name(value: Any) -> Any:
    """Return an enum member's ``name`` (``MigrationType.SQL`` → ``"SQL"``), else *value*.

    ``MigrationInfo.type`` / ``.status`` can be enum members; ``json.dumps``
    cannot serialise those, so the machine payload carries the name.
    """
    if value is None or isinstance(value, str):
        return value
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


def _migration_info_to_dict(m: Any) -> Dict[str, Any]:
    """Serialise one ``MigrationInfo`` row for ``--format json`` payloads.

    Shared by ``info``, ``validate`` and ``migrate`` so the row shape is one
    contract, not three.
    """
    installed_on = getattr(m, "installed_on", None)
    return {
        "script": m.script,
        "version": str(m.version) if m.version else None,
        "description": m.description,
        "type": _enum_name(m.type),
        "status": _enum_name(m.status),
        "checksum": m.checksum,
        "installed_on": (
            (installed_on.isoformat() if hasattr(installed_on, "isoformat") else installed_on)
            if installed_on
            else None
        ),
        "installed_by": m.installed_by,
        "execution_time": m.execution_time,
        "error": getattr(m, "error", None),
    }


def run_json_guarded(
    ctx: "CliCommandContext",
    command_type: str,
    call: Callable[[], Any],
    serialize: Callable[[Any], Dict[str, Any]],
) -> Tuple[bool, Any]:
    """Run *call* honouring the ``--format`` contract of ``ctx.args``.

    Human mode: run, report completion, return ``(result.success, result)``;
    exceptions propagate so the outer runner formats them. Machine mode:
    stdout is redirected while *call* runs (banners and headers printed by
    the command must not contaminate the JSON payload), an exception becomes
    ``{"success": false, "error": "<Type>: <msg>"}`` on stdout, and the
    serialised result is the only thing written. ``SystemExit`` and
    ``KeyboardInterrupt`` are not ``Exception`` and always propagate.
    """
    from dblift.cli._output import from_args

    command_output = from_args(ctx.args)
    result: Any = None
    if not command_output.is_machine_format:
        result = call()
        if result is None:
            return (False, None)
        _set_command_completed(ctx.log, result, command_type)
        return (result.success, result)

    error: Optional[Exception] = None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            result = call()
    except Exception as exc:
        error = exc
    if error is not None or result is None:
        text = (
            f"{type(error).__name__}: {error}"
            if error is not None
            else f"{command_type.lower()}() returned no result"
        )
        command_output.machine({"success": False, "error": text})
        return (False, None)
    command_output.machine(serialize(result))
    return (result.success, result)
