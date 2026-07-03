"""Discover and attach event-bus listeners registered by higher tiers.

Each ``dblift.event_listeners`` entry point resolves to a callable
``register(emitter) -> None`` that subscribes its listeners. OSS ships none;
dblift-enterprise registers (e.g.) the snapshot capture listener.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.events import EventEmitter

_log = logging.getLogger(__name__)


def attach_registered_listeners(emitter: "EventEmitter") -> None:
    """Attach every registered ``dblift.event_listeners`` listener to *emitter*."""
    for ep in entry_points(group="dblift.event_listeners"):
        try:
            register = ep.load()
            register(emitter)
        except Exception as exc:  # a bad plugin must not break the engine
            _log.warning("dblift.event_listeners '%s' failed to attach: %s", ep.name, exc)
