"""Handler for the ``validate`` command."""

from __future__ import annotations

from typing import Any, Tuple

from dblift.cli.handlers._shared import (
    CliCommandContext,
    _extract_version_filters,
    _set_command_completed,
)


def _handle_validate(ctx: CliCommandContext) -> Tuple[bool, Any]:
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        ctx.args
    )

    result = ctx.client.validate(
        target_version=target_version,
        tags=tags,
        exclude_tags=exclude_tags,
        versions=versions,
        exclude_versions=exclude_versions,
        recursive=ctx.recursive,
        additional_dirs=ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None,
    )
    _set_command_completed(ctx.log, result, "VALIDATE")
    return (result.success, result)
