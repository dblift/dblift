"""Tests for story 21-5: BaseProvider snapshot table default.

AC#1 — create_snapshot_table_if_not_exists is concrete on BaseProvider
AC#2 — close() and is_connected() have clear docstrings (already validated by code review)
AC#3 — Providers that strip snapshot hooks can still be concrete
"""

from unittest.mock import MagicMock

import pytest

from dblift.config import DbliftConfig
from dblift.db.base_provider import BaseProvider

pytestmark = [pytest.mark.unit]


def _make_config():
    mock_config = MagicMock(spec=DbliftConfig)
    mock_config.database = MagicMock()
    mock_config.database.type = "postgresql"
    return mock_config


def _make_concrete_provider_class(*, include_create_snapshot=True):
    """Build a concrete BaseProvider subclass with all abstract methods implemented.

    Args:
        include_create_snapshot: If False, omits create_snapshot_table_if_not_exists.
    """
    abstract_methods = set(BaseProvider.__abstractmethods__)

    methods = {}
    for name in abstract_methods:
        if name == "create_snapshot_table_if_not_exists" and not include_create_snapshot:
            continue
        methods[name] = lambda self, *args, **kwargs: None

    cls = type("ConcreteTestProvider", (BaseProvider,), methods)
    return cls


# AC#1.1 — create_snapshot_table_if_not_exists is not in __abstractmethods__
def test_create_snapshot_table_has_concrete_default():
    assert "create_snapshot_table_if_not_exists" not in BaseProvider.__abstractmethods__


# AC#1.2 — Subclass without a provider-owned snapshot hook is concrete
def test_subclass_without_create_snapshot_can_be_instantiated():
    Provider = _make_concrete_provider_class(include_create_snapshot=False)
    provider = Provider(config=_make_config())
    assert provider is not None


# AC#1.2 variant — Complete subclass can be instantiated
def test_complete_subclass_can_be_instantiated():
    CompleteProvider = _make_concrete_provider_class()
    provider = CompleteProvider(config=_make_config())
    assert provider is not None


# AC#1.3 — Default implementation delegates to the shared snapshot manager
def test_create_snapshot_default_delegates_to_base_snapshot_manager(monkeypatch):
    calls = []

    class FakeSnapshotManager:
        def __init__(self, provider):
            calls.append(("init", provider))

        def create_snapshot_table_if_not_exists(self, schema, table_name):
            calls.append(("create", schema, table_name))

    from dblift.db.plugins import base_snapshot_manager

    monkeypatch.setattr(base_snapshot_manager, "BaseSnapshotManager", FakeSnapshotManager)

    Provider = _make_concrete_provider_class(include_create_snapshot=False)
    provider = Provider(config=_make_config())

    provider.create_snapshot_table_if_not_exists("app", "custom_snapshots")

    assert calls == [("init", provider), ("create", "app", "custom_snapshots")]


# AC#2 — close() has a meaningful docstring documenting override expectations
def test_close_has_override_docstring():
    doc = BaseProvider.close.__doc__
    assert doc is not None
    assert len(doc.strip()) > 0
    # Docstring should mention when subclasses should override
    assert "override" in doc.lower() or "should" in doc.lower()


# AC#2 — is_connected() has a meaningful docstring documenting override expectations
def test_is_connected_has_override_docstring():
    doc = BaseProvider.is_connected.__doc__
    assert doc is not None
    assert len(doc.strip()) > 0
    # Docstring should mention override or acceptable default
    assert "override" in doc.lower() or "acceptable" in doc.lower()


# AC#3 — Providers that removed provider-owned snapshot hooks remain concrete
@pytest.mark.parametrize(
    "provider_module,class_name",
    [
        ("dblift.db.plugins.mysql.provider", "MySqlProvider"),
        ("dblift.db.plugins.mariadb.provider", "MariadbProvider"),
    ],
)
def test_snapshot_hook_removed_provider_remains_concrete(provider_module, class_name):
    import importlib

    mod = importlib.import_module(provider_module)
    cls = getattr(mod, class_name)
    assert "create_snapshot_table_if_not_exists" not in cls.__dict__
    assert "create_snapshot_table_if_not_exists" not in getattr(cls, "__abstractmethods__", set())
