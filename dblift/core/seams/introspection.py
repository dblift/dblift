"""Discover and run tier-provided introspection registrars."""

from __future__ import annotations

import logging
from importlib.metadata import EntryPoint, entry_points
from threading import Condition, get_ident

_log = logging.getLogger(__name__)
_attach_condition = Condition()
_introspection_attached = False
_attaching_thread_id: int | None = None
_pending_entry_points: tuple[EntryPoint, ...] | None = None


def attach_registered_introspection() -> None:
    """Run each introspection registrar until it succeeds."""
    global _attaching_thread_id, _introspection_attached, _pending_entry_points
    thread_id = get_ident()
    with _attach_condition:
        while _attaching_thread_id is not None:
            if _attaching_thread_id == thread_id:
                return
            _attach_condition.wait()
        if _introspection_attached:
            return
        _attaching_thread_id = thread_id

    remaining: tuple[EntryPoint, ...] | None = None
    try:
        discovered = _pending_entry_points
        if discovered is None:
            discovered = tuple(entry_points(group="dblift.introspection"))
        failed = []
        for ep in discovered:
            try:
                registrar = ep.load()
                registrar()
            except Exception as exc:  # a bad plugin must not break OSS introspection
                failed.append(ep)
                _log.warning("dblift.introspection '%s' failed to attach: %s", ep.name, exc)
        remaining = tuple(failed)
    finally:
        with _attach_condition:
            if remaining is not None:
                _pending_entry_points = remaining
            _introspection_attached = remaining == ()
            _attaching_thread_id = None
            _attach_condition.notify_all()
