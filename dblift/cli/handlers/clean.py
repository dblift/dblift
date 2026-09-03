"""Handler for the ``clean`` command."""

from __future__ import annotations

from typing import Any, Tuple

from dblift.cli.handlers._shared import CliCommandContext, _set_command_completed


def _handle_clean(ctx: CliCommandContext) -> Tuple[bool, Any]:
    result = ctx.client.clean(
        dry_run=ctx.args.dry_run,
        recursive=ctx.recursive,
        additional_dirs=ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None,
        show_query_results=getattr(ctx.args, "show_query_results", False),
    )
    _set_command_completed(ctx.log, result, "CLEAN")
    return (result.success, result)
