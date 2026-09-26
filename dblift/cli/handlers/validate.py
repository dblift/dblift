"""Handler for the ``validate`` command + ValidateResult JSON serialization."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple

from dblift.cli.handlers._shared import (
    CliCommandContext,
    _extract_version_filters,
    _migration_info_to_dict,
    run_json_guarded,
)
from dblift.core.migration.commands.base_command import PreflightConnectionError


def _validate_result_to_dict(result: Any) -> Dict[str, Any]:
    """Serialize a ValidateResult to a JSON-compatible dict."""
    return {
        "success": bool(getattr(result, "success", True)),
        # A clean validate leaves error_message empty (""); emit null, as info
        # and migrate do, so the three read tools share one error contract.
        "error": getattr(result, "error_message", None) or None,
        "target_schema": getattr(result, "target_schema", ""),
        "error_count": getattr(result, "error_count", 0),
        "issues": list(getattr(result, "issues", [])),
        "validated_migrations": [
            _migration_info_to_dict(m) for m in getattr(result, "validated_migrations", [])
        ],
        "failed_migrations": [
            _migration_info_to_dict(m) for m in getattr(result, "failed_migrations", [])
        ],
    }


class _FailedCommandResult(Protocol):
    """The fields this handler reads off a failed command result."""

    success: bool
    error_message: Optional[str]
    preflight_error: Optional[BaseException]


def _reraise_preflight_failure(
    result: _FailedCommandResult,
) -> _FailedCommandResult:
    """Keep the CLI, JSON and MCP error path for a preflight failure.

    ``DBLiftClient.validate()`` returns a failed result when the connection
    fails or the schema-history table cannot be created. These surfaces
    still raise ``ConnectionError`` — the base type, so the published text
    stays ``ConnectionError: ...`` — which ``run_json_guarded`` turns into
    ``{"success": false, "error": "ConnectionError: ..."}`` and which
    ``dblift mcp`` reports as an error result. Any other result, including
    another ``ConnectionError`` that was not a preflight failure, is returned
    as a validation verdict.
    """
    error = result.preflight_error
    if result.success is False and isinstance(error, PreflightConnectionError):
        raise ConnectionError(str(error))
    return result


def _handle_validate(ctx: CliCommandContext) -> Tuple[bool, Any]:
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        ctx.args
    )

    def call() -> Any:
        return _reraise_preflight_failure(
            ctx.client.validate(
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                recursive=ctx.recursive,
                dir_recursive_map=ctx.dir_recursive_map or None,
                additional_dirs=(
                    ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None
                ),
            )
        )

    return run_json_guarded(ctx, "VALIDATE", call, _validate_result_to_dict)
