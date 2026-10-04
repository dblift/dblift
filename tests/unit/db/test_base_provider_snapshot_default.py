"""BaseProvider remains concrete after internal snapshot storage removal."""

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


def _make_concrete_provider_class():
    """Build a concrete BaseProvider subclass with all abstract methods implemented."""
    abstract_methods = set(BaseProvider.__abstractmethods__)

    methods = {}
    for name in abstract_methods:
        methods[name] = lambda self, *args, **kwargs: None

    cls = type("ConcreteTestProvider", (BaseProvider,), methods)
    return cls


# Subclass without a provider-owned snapshot hook is concrete.
def test_subclass_without_create_snapshot_can_be_instantiated():
    Provider = _make_concrete_provider_class()
    provider = Provider(config=_make_config())
    assert provider is not None


# close() has a meaningful docstring documenting override expectations
def test_close_has_override_docstring():
    doc = BaseProvider.close.__doc__
    assert doc is not None
    assert len(doc.strip()) > 0
    # Docstring should mention when subclasses should override
    assert "override" in doc.lower() or "should" in doc.lower()


# is_connected() has a meaningful docstring documenting override expectations
def test_is_connected_has_override_docstring():
    doc = BaseProvider.is_connected.__doc__
    assert doc is not None
    assert len(doc.strip()) > 0
    # Docstring should mention override or acceptable default
    assert "override" in doc.lower() or "acceptable" in doc.lower()


# Providers that removed provider-owned snapshot hooks remain concrete
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
