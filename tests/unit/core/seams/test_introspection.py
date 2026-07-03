import importlib

from core.seams.introspection import attach_registered_introspection


class _EntryPoint:
    name = "pro"

    def __init__(self, registrar):
        self._registrar = registrar

    def load(self):
        return self._registrar


def test_attach_registered_introspection_loads_entrypoints(monkeypatch):
    calls = []

    def registrar():
        calls.append("registered")

    monkeypatch.setattr(
        "core.seams.introspection.entry_points",
        lambda group: [_EntryPoint(registrar)] if group == "dblift.introspection" else [],
    )

    attach_registered_introspection()

    assert calls == ["registered"]


def test_attach_registered_introspection_uses_entrypoints_only(monkeypatch, caplog):
    monkeypatch.setattr(
        "core.seams.introspection.entry_points",
        lambda group: [],
    )
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: (_ for _ in ()).throw(AssertionError(f"unexpected import: {name}")),
    )

    attach_registered_introspection()

    assert "unexpected import" not in caplog.text
