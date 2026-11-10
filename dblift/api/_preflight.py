"""Re-raise a command preflight failure carried on a failed result.

Shared by the command-line handlers and the web-framework integrations, so
it lives on the API layer: the integrations can use it without importing the
command-line package.
"""

from __future__ import annotations

from typing import Optional, Protocol, TypeVar

from dblift.core.migration.commands.base_command import PreflightConnectionError


class _FailedCommandResult(Protocol):
    """The fields ``reraise_preflight_failure`` reads off a command result."""

    success: bool
    error_message: Optional[str]
    _preflight_error: Optional[BaseException]


_ResultT = TypeVar("_ResultT", bound=_FailedCommandResult)


def reraise_preflight_failure(result: _ResultT) -> _ResultT:
    """Keep the CLI, JSON and MCP error path for a preflight failure.

    ``DBLiftClient`` command methods return a failed result when the
    connection fails or the schema-history table cannot be created. These
    surfaces still raise ``ConnectionError`` — the base type, so the
    published text stays ``ConnectionError: ...`` — which ``run_json_guarded``
    turns into ``{"success": false, "error": "ConnectionError: ..."}`` and
    which ``dblift mcp`` reports as an error result. Any other result,
    including one for another ``ConnectionError`` that was not a preflight
    failure, is returned as the command's verdict.
    """
    error = getattr(result, "_preflight_error", None)
    if isinstance(error, PreflightConnectionError) and result.success is False:
        raise ConnectionError(str(error))
    return result
