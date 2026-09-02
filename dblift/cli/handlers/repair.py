"""Handler for the ``repair`` command."""

from __future__ import annotations

from typing import Any, Tuple

from dblift.cli.handlers._shared import CliCommandContext, _set_command_completed


def _handle_repair(ctx: CliCommandContext) -> Tuple[bool, Any]:
    result = ctx.client.repair(
        dry_run=ctx.args.dry_run,
        recursive=ctx.recursive,
        additional_dirs=ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None,
        dir_recursive_map=ctx.dir_recursive_map if ctx.dir_recursive_map else None,
    )
    _set_command_completed(ctx.log, result, "REPAIR")
    return (result.success, result)
