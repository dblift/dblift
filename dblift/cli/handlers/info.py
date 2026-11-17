"""Handler for the ``info`` command + InfoResult JSON serialization."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from dblift.cli.handlers._shared import (
    CliCommandContext,
    _extract_version_filters,
    _migration_info_to_dict,
    _reraise_preflight_failure,
    run_json_guarded,
)


def _info_result_to_dict(result: Any) -> Dict[str, Any]:
    """Serialize an InfoResult to a JSON-compatible dict."""
    migrations = [_migration_info_to_dict(m) for m in result.migrations]
    return {
        # ``success`` mirrors the error-path payload (``{"success": False, ...}``)
        # so downstream consumers can do ``result["success"]`` on both happy and
        # error paths without a KeyError on the happy path.
        "success": bool(result.success),
        # Same reason ``OutputFormatter.format_info`` prints as ``Error: ...``.
        # Without it a JSON consumer saw ``success: false`` and nothing else,
        # while the key was already populated on the handler's exception payload.
        "error": result.error_message,
        "current_schema_version": result.current_schema_version,
        "history_table_exists": result.history_table_exists,
        "target_schema": result.target_schema,
        "db_version": result.db_version,
        "database_url_masked": result.database_url_masked,
        "native_driver": result.native_driver,
        "migrations": migrations,
    }


def _handle_info(ctx: CliCommandContext) -> Tuple[bool, Any]:
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        ctx.args
    )

    from dblift.cli._output import from_args as _output_from_args

    use_json = _output_from_args(ctx.args).is_machine_format
    info_kwargs = {
        "target_version": target_version,
        "tags": tags,
        "exclude_tags": exclude_tags,
        "versions": versions,
        "exclude_versions": exclude_versions,
        "recursive": ctx.recursive,
        "dir_recursive_map": ctx.dir_recursive_map or None,
        "additional_dirs": ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None,
        "display_human": not use_json,
    }
    return run_json_guarded(
        ctx,
        "INFO",
        lambda: _reraise_preflight_failure(ctx.client.info(**info_kwargs)),
        _info_result_to_dict,
    )
