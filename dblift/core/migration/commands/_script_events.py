"""Shared helper to emit migration-script lifecycle events.

Used by migrate and undo commands. Emits on the active emitter bound by
``@_with_client_emitter`` (falls back to the process-wide default emitter).
"""

from __future__ import annotations

from typing import Any, Dict


def emit_script_event(event: str, data: Dict[str, Any]) -> None:
    """Emit a migration-script event; never raise into the engine."""
    try:
        from dblift.api.events import emit_event
    except ImportError:
        return
    emit_event(event, data)
