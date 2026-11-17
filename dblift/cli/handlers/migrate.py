"""Handler for the ``migrate`` command + MigrateResult JSON serialization."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from dblift.cli.handlers._shared import (
    CliCommandContext,
    _extract_version_filters,
    _migration_info_to_dict,
    _reraise_preflight_failure,
    run_json_guarded,
)
from dblift.cli.handlers.validate import _validate_result_to_dict
from dblift.core.logger.formatters.jsonformatter import JsonFormatter


def _migrate_result_to_dict(result: Any, dry_run: bool) -> Dict[str, Any]:
    """Serialize a MigrateResult to a JSON-compatible dict."""
    data = {
        "success": bool(result.success),
        "error": result.error_message,
        "dry_run": bool(dry_run),
        "target_schema": result.target_schema,
        "current_schema_version": result.current_schema_version,
        "history_table_exists": result.history_table_exists,
        "dry_run_count": result.dry_run_count,
        "migrations": [_migration_info_to_dict(m) for m in result.migrations],
        "migrations_applied": list(result.migrations_applied),
    }
    # Reuse the same show-sql shape/sanitization JsonFormatter uses for the
    # text/HTML log formats, instead of duplicating its getattr/sanitize pair
    # here. It returns both `show_sql` and `sql` when show_sql is set, and {}
    # otherwise — merge it whole so this payload matches the log-format JSON
    # and adds nothing to ordinary output.
    data.update(JsonFormatter()._format_sql_visibility(result))
    return data


def _handle_migrate(ctx: CliCommandContext) -> Tuple[bool, Any]:
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        ctx.args
    )
    additional_dirs = ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None

    # Handle --validate-only by calling validate instead of migrate
    if ctx.args.validate_only:

        def _validate_call() -> Any:
            return _reraise_preflight_failure(
                ctx.client.validate(
                    target_version=target_version,
                    tags=tags,
                    exclude_tags=exclude_tags,
                    versions=versions,
                    exclude_versions=exclude_versions,
                    recursive=ctx.recursive,
                    dir_recursive_map=ctx.dir_recursive_map or None,
                    additional_dirs=additional_dirs,
                )
            )

        return run_json_guarded(ctx, "VALIDATE", _validate_call, _validate_result_to_dict)

    dry_run = bool(ctx.args.dry_run)

    def migrate_call() -> Any:
        return _reraise_preflight_failure(
            ctx.client.migrate(
                target_version=target_version,
                dry_run=dry_run,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                mark_as_executed=bool(ctx.args.mark_as_executed),
                show_sql=ctx.args.show_sql,
                show_query_results=ctx.args.show_query_results,
                placeholders=ctx.placeholders,
                recursive=ctx.recursive,
                dir_recursive_map=ctx.dir_recursive_map or None,
                additional_dirs=additional_dirs,
            )
        )

    return run_json_guarded(
        ctx, "MIGRATE", migrate_call, lambda r: _migrate_result_to_dict(r, dry_run)
    )


# The client connects on demand, after the pre-migrate checks have run.
_handle_migrate._dblift_needs_connection = lambda args: False  # type: ignore[attr-defined]
