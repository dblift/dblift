"""Handler for the ``baseline`` command."""

from __future__ import annotations

from typing import Any, Tuple

from dblift.cli.handlers._shared import CliCommandContext, _set_command_completed


def _handle_baseline(ctx: CliCommandContext) -> Tuple[bool, Any]:
    baseline_description = getattr(ctx.args, "baseline_description", None) or ""
    result = ctx.client.baseline(
        ctx.args.baseline_version,
        baseline_description,
        dry_run=getattr(ctx.args, "dry_run", False),
    )
    _set_command_completed(ctx.log, result, "BASELINE")
    return (result.success, result)
