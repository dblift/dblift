import importlib
from threading import Event, Thread

from dblift.core.seams.introspection import attach_registered_introspection


class _EntryPoint:
    name = "pro"

    def __init__(self, registrar):
        self._registrar = registrar

    def load(self):
        return self._registrar


def test_attach_registered_introspection_loads_entrypoints(monkeypatch):
    from dblift.core.seams import introspection

    calls = []

    def registrar():
        calls.append("registered")

    monkeypatch.setattr(
        introspection,
        "entry_points",
        lambda group: [_EntryPoint(registrar)] if group == "dblift.introspection" else [],
    )
    monkeypatch.setattr(introspection, "_introspection_attached", False)

    attach_registered_introspection()

    assert calls == ["registered"]


def test_attach_registered_introspection_uses_entrypoints_only(monkeypatch, caplog):
    from dblift.core.seams import introspection

    monkeypatch.setattr(
        introspection,
        "entry_points",
        lambda group: [],
    )
    monkeypatch.setattr(introspection, "_introspection_attached", False)
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(AssertionError(f"unexpected import: {name}")),
    )

    attach_registered_introspection()

    assert "unexpected import" not in caplog.text


def test_attach_registered_introspection_logs_failed_registrar(monkeypatch, caplog):
    from dblift.core.seams import introspection

    def register():
        raise RuntimeError("extension failed")

    monkeypatch.setattr(
        introspection,
        "entry_points",
        lambda group: [_EntryPoint(register)] if group == "dblift.introspection" else [],
    )
    monkeypatch.setattr(introspection, "_introspection_attached", False)

    attach_registered_introspection()

    assert "dblift.introspection 'pro' failed to attach: extension failed" in caplog.text


def test_concurrent_attach_waits_for_registrar_completion(monkeypatch):
    from dblift.core.seams import introspection

    registrar_started = Event()
    release_registrar = Event()
    second_started = Event()
    second_done = Event()

    def register():
        registrar_started.set()
        release_registrar.wait(timeout=2)

    monkeypatch.setattr(
        introspection,
        "entry_points",
        lambda group: [_EntryPoint(register)] if group == "dblift.introspection" else [],
    )
    monkeypatch.setattr(introspection, "_introspection_attached", False)

    first = Thread(target=attach_registered_introspection)

    def attach_second():
        second_started.set()
        attach_registered_introspection()
        second_done.set()

    second = Thread(target=attach_second)
    first.start()
    assert registrar_started.wait(timeout=2)
    second.start()
    assert second_started.wait(timeout=2)
    returned_before_registration = second_done.wait(timeout=0.1)
    release_registrar.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not returned_before_registration
    assert second_done.is_set()
