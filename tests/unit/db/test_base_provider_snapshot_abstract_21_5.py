"""Tests for story 21-5: @abstractmethod create_snapshot_table_if_not_exists in BaseProvider.

AC#1 — create_snapshot_table_if_not_exists is @abstractmethod on BaseProvider
AC#2 — close() and is_connected() have clear docstrings (already validated by code review)
AC#3 — All concrete providers implement the method
"""

import inspect
from unittest.mock import MagicMock

import pytest

from config import DbliftConfig
from db.base_provider import BaseProvider

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


# AC#1.1 — create_snapshot_table_if_not_exists is in __abstractmethods__
def test_create_snapshot_table_is_abstractmethod():
    assert "create_snapshot_table_if_not_exists" in BaseProvider.__abstractmethods__


# AC#1.2 — Instantiating incomplete subclass raises TypeError
def test_subclass_without_create_snapshot_raises_type_error():
    IncompleteProvider = _make_concrete_provider_class(include_create_snapshot=False)
    with pytest.raises(TypeError):
        IncompleteProvider(config=_make_config())


# AC#1.2 variant — Complete subclass can be instantiated
def test_complete_subclass_can_be_instantiated():
    CompleteProvider = _make_concrete_provider_class()
    provider = CompleteProvider(config=_make_config())
    assert provider is not None


# AC#1.3 — Default warning-only body is removed (body is empty / docstring only)
def test_create_snapshot_no_warning_body():
    source = inspect.getsource(BaseProvider.create_snapshot_table_if_not_exists)
    assert "log.warning" not in source
    assert "not implemented" not in source.lower()


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


# AC#3 — Parametric test: all concrete providers implement create_snapshot_table_if_not_exists
@pytest.mark.parametrize(
    "provider_module,class_name",
    [
        ("db.plugins.sqlite.provider", "SQLiteProvider"),
        ("db.plugins.cosmosdb.provider", "CosmosDbProvider"),
    ],
)
def test_concrete_provider_implements_create_snapshot(provider_module, class_name):
    """Each concrete (or intermediate) provider class must define create_snapshot_table_if_not_exists."""
    import importlib

    mod = importlib.import_module(provider_module)
    cls = getattr(mod, class_name)
    assert (
        "create_snapshot_table_if_not_exists" in cls.__dict__
    ), f"{class_name} does not define create_snapshot_table_if_not_exists in its own __dict__"
