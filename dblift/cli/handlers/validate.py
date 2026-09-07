"""Handler for the ``validate`` command + ValidateResult JSON serialization."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from dblift.cli.handlers._shared import (
    CliCommandContext,
    _extract_version_filters,
    _migration_info_to_dict,
    run_json_guarded,
)


def _validate_result_to_dict(result: Any) -> Dict[str, Any]:
    """Serialize a ValidateResult to a JSON-compatible dict."""
    return {
        "success": bool(getattr(result, "success", True)),
        "error": getattr(result, "error_message", None),
        "target_schema": getattr(result, "target_schema", ""),
        "error_count": getattr(result, "error_count", 0),
        "validated_migrations": [
            _migration_info_to_dict(m) for m in getattr(result, "validated_migrations", [])
        ],
        "failed_migrations": [
            _migration_info_to_dict(m) for m in getattr(result, "failed_migrations", [])
        ],
    }


def _handle_validate(ctx: CliCommandContext) -> Tuple[bool, Any]:
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        ctx.args
    )

    def call() -> Any:
        return ctx.client.validate(
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            recursive=ctx.recursive,
            additional_dirs=ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None,
        )

    return run_json_guarded(ctx, "VALIDATE", call, _validate_result_to_dict)
