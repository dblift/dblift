"""Handler for the ``info`` command + InfoResult JSON serialization."""

from __future__ import annotations

import contextlib
import io
from typing import Any, Dict, Optional, Tuple

from cli.handlers._shared import (
    CliCommandContext,
    _extract_version_filters,
    _set_command_completed,
)


def _info_result_to_dict(result: Any) -> Dict[str, Any]:
    """Serialize an InfoResult to a JSON-compatible dict."""

    def _enum_to_str(value: Any) -> Any:
        """Return the enum's name (e.g. MigrationType.SQL → "SQL") or the value unchanged.

        ``m.type`` and ``m.status`` can be enum members (``MigrationType``, etc.).
        The downstream serializer does not know how to handle arbitrary enum
        members, so passing them through would raise ``TypeError`` and crash
        ``info --format json``.
        """
        if value is None or isinstance(value, str):
            return value
        name = getattr(value, "name", None)
        if isinstance(name, str):
            return name
        return str(value)

    migrations = []
    for m in getattr(result, "migrations", []):
        installed_on = getattr(m, "installed_on", None)
        migrations.append(
            {
                "script": m.script,
                "version": str(m.version) if m.version else None,
                "description": m.description,
                "type": _enum_to_str(m.type),
                "status": _enum_to_str(m.status),
                "checksum": m.checksum,
                "installed_on": (
                    (
                        installed_on.isoformat()
                        if hasattr(installed_on, "isoformat")
                        else installed_on
                    )
                    if installed_on
                    else None
                ),
                "installed_by": m.installed_by,
                "execution_time": m.execution_time,
                "error": getattr(m, "error", None),
            }
        )
    return {
        # ``success`` mirrors the error-path payload (``{"success": False, ...}``)
        # so downstream consumers can do ``result["success"]`` on both happy and
        # error paths without a KeyError on the happy path.
        "success": bool(getattr(result, "success", True)),
        "current_schema_version": getattr(result, "current_schema_version", None),
        "target_schema": getattr(result, "target_schema", ""),
        "db_version": getattr(result, "db_version", None),
        "database_url_masked": getattr(result, "database_url_masked", None),
        "native_driver": getattr(result, "native_driver", None),
        "migrations": migrations,
    }


def _handle_info(ctx: CliCommandContext) -> Tuple[bool, Any]:
    target_version, versions, exclude_versions, tags, exclude_tags = _extract_version_filters(
        ctx.args
    )

    info_kwargs = {
        "target_version": target_version,
        "tags": tags,
        "exclude_tags": exclude_tags,
        "versions": versions,
        "exclude_versions": exclude_versions,
        "recursive": ctx.recursive,
        "additional_dirs": ctx.additional_scripts_dirs if ctx.additional_scripts_dirs else None,
    }

    from cli._output import from_args as _output_from_args

    command_output = _output_from_args(ctx.args)
    use_json = command_output.is_machine_format
    info_kwargs["display_human"] = not use_json
    if use_json:
        # Redirect stdout while the command runs so that the human-readable
        # banner and command header printed by base_command do not contaminate
        # the JSON output. The result object is returned normally; only its
        # dict serialisation goes to real stdout afterwards.
        _sink = io.StringIO()
        cm: contextlib.AbstractContextManager[Any] = contextlib.redirect_stdout(_sink)
    else:
        cm = contextlib.nullcontext()

    # Guard the call so a raised exception still produces a JSON error payload
    # on stdout — otherwise the user gets a raw traceback and the JSON contract
    # is broken for error cases. In human mode, re-raise to keep the existing
    # behavior (the outer runner formats/prints the error).
    #
    # We intentionally narrow the catch to ``Exception``: ``KeyboardInterrupt``
    # (Ctrl-C) and ``SystemExit`` (raised by argparse)
    # MUST propagate so the process terminates with the correct exit code.
    # Wrapping them as ``{"success": false}`` would silently swallow the signal.
    result: Any = None
    info_error: Optional[Exception] = None
    try:
        with cm:
            result = ctx.client.info(**info_kwargs)
    except Exception as exc:
        if not use_json:
            raise
        info_error = exc

    if use_json:
        # Defensive: a provider bug could theoretically return None without
        # raising. Emit a structured error payload instead of crashing on
        # ``getattr(result, ...)`` or producing a misleading ``success: true``
        # with empty fields.
        if info_error is not None or result is None:
            error_text = (
                f"{type(info_error).__name__}: {info_error}"
                if info_error is not None
                else "info() returned no result"
            )
            command_output.machine(
                {
                    "success": False,
                    "error": error_text,
                }
            )
            return (False, None)

        command_output.machine(_info_result_to_dict(result))
    else:
        if result is None:
            return (False, None)
        _set_command_completed(ctx.log, result, "INFO")

    return (result.success, result)
