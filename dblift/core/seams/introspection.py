"""Discover and run tier-provided introspection registrars."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from threading import Condition, get_ident

_log = logging.getLogger(__name__)
_attach_condition = Condition()
_introspection_attached = False
_attaching_thread_id: int | None = None


def attach_registered_introspection() -> None:
    """Run every ``dblift.introspection`` registrar once."""
    global _attaching_thread_id, _introspection_attached
    thread_id = get_ident()
    with _attach_condition:
        while _attaching_thread_id is not None:
            if _attaching_thread_id == thread_id:
                return
            _attach_condition.wait()
        if _introspection_attached:
            return
        _attaching_thread_id = thread_id

    completed = False
    try:
        discovered = list(entry_points(group="dblift.introspection"))
        for ep in discovered:
            try:
                registrar = ep.load()
                registrar()
            except Exception as exc:  # a bad plugin must not break OSS introspection
                _log.warning("dblift.introspection '%s' failed to attach: %s", ep.name, exc)
        completed = True
    finally:
        with _attach_condition:
            _introspection_attached = completed
            _attaching_thread_id = None
            _attach_condition.notify_all()
