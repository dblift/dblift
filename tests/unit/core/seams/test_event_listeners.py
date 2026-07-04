import importlib
from unittest.mock import MagicMock

import core.seams.event_listeners as event_listeners
from api.events import EventEmitter
from core.seams.event_listeners import attach_registered_listeners


def test_attach_no_entrypoints_is_noop():
    emitter = EventEmitter()
    # No dblift.event_listeners entry points installed in the OSS-only test env.
    attach_registered_listeners(emitter)  # must not raise


def test_attach_registered_listeners_uses_entrypoints_only(monkeypatch, caplog):
    emitter = EventEmitter()
    monkeypatch.setattr(
        event_listeners,
        "entry_points",
        lambda group: [] if group == "dblift.event_listeners" else [],
    )
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(AssertionError(f"unexpected import: {name}")),
    )
    attach_registered_listeners(emitter)

    assert "unexpected import" not in caplog.text


def test_attach_registered_listeners_does_not_duplicate_entrypoints(monkeypatch):
    emitter = EventEmitter()
    calls = []

    def _register(target):
        calls.append(target)
        target.on("test", lambda payload: None)

    entry_point = MagicMock()
    entry_point.name = "pro_snapshot"
    entry_point.load.return_value = _register

    monkeypatch.setattr(
        event_listeners,
        "entry_points",
        lambda group: [entry_point] if group == "dblift.event_listeners" else [],
    )

    attach_registered_listeners(emitter)

    assert calls == [emitter]
