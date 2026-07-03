"""Discover and run tier-provided introspection registrars."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

_log = logging.getLogger(__name__)


def attach_registered_introspection() -> None:
    """Run every ``dblift.introspection`` registrar."""
    for ep in entry_points(group="dblift.introspection"):
        try:
            registrar = ep.load()
            registrar()
        except Exception as exc:  # a bad plugin must not break OSS introspection
            _log.warning("dblift.introspection '%s' failed to attach: %s", ep.name, exc)
