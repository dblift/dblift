"""Handler for the ``import-flyway`` command."""

from __future__ import annotations

from typing import Any, Tuple

from dblift.cli.handlers._shared import CliCommandContext, _set_command_completed


def _handle_import_flyway(ctx: CliCommandContext) -> Tuple[bool, Any]:
    result = ctx.client.import_flyway(
        dry_run=ctx.args.dry_run,
        recursive=ctx.recursive,
        flyway_table=getattr(ctx.args, "flyway_table", "flyway_schema_history"),
    )
    _set_command_completed(ctx.log, result, "IMPORT-FLYWAY")
    return (result.success, result)
