"""Resolve the CLI's client class through the ``dblift.client`` seam.

The CLI builds one client per invocation. Paid tiers ship a ``DBLiftClient``
subclass carrying their commands (offline planning, snapshots, ...) and
register it under the ``dblift.client`` entry-point group; the CLI then
constructs that subclass instead of the OSS client, so tier-provided command
handlers receive a client exposing their methods. Without a registration the
OSS ``api.DBLiftClient`` is used — behavior is unchanged for OSS-only
installs.

At most one registration is honored (the first the interpreter yields);
loading failures are logged and fall back to the OSS client, so a broken
plugin can never take the CLI down.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any, Optional, Type

_log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "dblift.client"

_resolved_class: Optional[Type[Any]] = None
_resolution_done = False


def resolve_client_class() -> Type[Any]:
    """The registered ``dblift.client`` class, or the OSS ``DBLiftClient``."""
    global _resolved_class, _resolution_done
    if not _resolution_done:
        _resolution_done = True
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                loaded = ep.load()
            except Exception as exc:  # a bad plugin must not break the CLI
                _log.warning("dblift.client '%s' failed to load: %s", ep.name, exc)
                continue
            if not isinstance(loaded, type):
                _log.warning(
                    "dblift.client '%s' did not load a class (got %r); ignoring",
                    ep.name,
                    type(loaded).__name__,
                )
                continue
            _resolved_class = loaded
            break
    if _resolved_class is not None:
        return _resolved_class
    from dblift.api import DBLiftClient

    return DBLiftClient


def _reset_for_tests() -> None:
    """Test-only: clear the cached resolution."""
    global _resolved_class, _resolution_done
    _resolved_class = None
    _resolution_done = False
