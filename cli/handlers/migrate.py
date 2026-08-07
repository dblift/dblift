"""Handler for the ``migrate`` command."""

from __future__ import annotations

from typing import Any, Tuple

from cli.handlers._shared import (
    CliCommandContext,
    _extract_version_filters,
    _set_command_completed,
)


def _handle_migrate(ctx: CliCommandContext) -> Tuple[bool, Any]:
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        ctx.args
    )

    # Handle --validate-only by calling validate instead of migrate
    if getattr(ctx.args, "validate_only", False):
        result = ctx.client.validate(
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            recursive=ctx.recursive,
            additional_dirs=(ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None),
        )
        return (result.success, result)
    else:
        result = ctx.client.migrate(
            target_version=target_version,
            dry_run=ctx.args.dry_run,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            mark_as_executed=getattr(ctx.args, "mark_as_executed", False),
            show_sql=getattr(ctx.args, "show_sql", False),
            show_query_results=getattr(ctx.args, "show_query_results", False),
            placeholders=ctx.placeholders,
            recursive=ctx.recursive,
            additional_dirs=(ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None),
        )
        _set_command_completed(ctx.log, result, "MIGRATE")
        return (result.success, result)
