"""Handler for the ``migrate`` command + MigrateResult JSON serialization."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from dblift.cli.handlers._shared import (
    CliCommandContext,
    _extract_version_filters,
    _migration_info_to_dict,
    run_json_guarded,
)
from dblift.cli.handlers.validate import _validate_result_to_dict


def _migrate_result_to_dict(result: Any, dry_run: bool) -> Dict[str, Any]:
    """Serialize a MigrateResult to a JSON-compatible dict."""
    return {
        "success": bool(getattr(result, "success", True)),
        "error": getattr(result, "error_message", None),
        "dry_run": bool(dry_run),
        "target_schema": getattr(result, "target_schema", ""),
        "current_schema_version": getattr(result, "current_schema_version", None),
        "dry_run_count": getattr(result, "dry_run_count", 0),
        "migrations": [_migration_info_to_dict(m) for m in getattr(result, "migrations", [])],
        "migrations_applied": list(getattr(result, "migrations_applied", [])),
    }


def _handle_migrate(ctx: CliCommandContext) -> Tuple[bool, Any]:
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        ctx.args
    )
    additional_dirs = ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None

    # Handle --validate-only by calling validate instead of migrate
    if getattr(ctx.args, "validate_only", False):

        def _validate_call() -> Any:
            return ctx.client.validate(
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                recursive=ctx.recursive,
                additional_dirs=additional_dirs,
            )

        return run_json_guarded(ctx, "VALIDATE", _validate_call, _validate_result_to_dict)

    dry_run = bool(getattr(ctx.args, "dry_run", False))

    def migrate_call() -> Any:
        return ctx.client.migrate(
            target_version=target_version,
            dry_run=dry_run,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            mark_as_executed=getattr(ctx.args, "mark_as_executed", False),
            show_sql=getattr(ctx.args, "show_sql", False),
            show_query_results=getattr(ctx.args, "show_query_results", False),
            placeholders=ctx.placeholders,
            recursive=ctx.recursive,
            additional_dirs=additional_dirs,
        )

    return run_json_guarded(
        ctx, "MIGRATE", migrate_call, lambda r: _migrate_result_to_dict(r, dry_run)
    )
