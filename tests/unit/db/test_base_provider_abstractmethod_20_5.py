"""Tests for story 20-5: @abstractmethod create_migration_history_table_if_not_exists in BaseProvider."""

import inspect
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


def _make_concrete_provider_class(*, include_create_migration_history=True):
    """Build a concrete BaseProvider subclass with all abstract methods implemented.

    Args:
        include_create_migration_history: If False, omits create_migration_history_table_if_not_exists.
    """
    # Get all abstract methods from BaseProvider
    abstract_methods = set(BaseProvider.__abstractmethods__)

    methods = {}
    for name in abstract_methods:
        if (
            name == "create_migration_history_table_if_not_exists"
            and not include_create_migration_history
        ):
            continue
        methods[name] = lambda self, *args, **kwargs: None

    cls = type("ConcreteTestProvider", (BaseProvider,), methods)
    return cls


# AC#4.1 — Subclass without create_migration_history_table_if_not_exists raises TypeError
def test_subclass_without_create_migration_history_table_raises_type_error():
    IncompleteProvider = _make_concrete_provider_class(include_create_migration_history=False)
    with pytest.raises(TypeError):
        IncompleteProvider(config=_make_config())


# AC#4.2 — create_migration_history_table_if_not_exists is in __abstractmethods__
def test_create_migration_history_table_is_abstractmethod():
    assert "create_migration_history_table_if_not_exists" in BaseProvider.__abstractmethods__


# AC#4.3 — create_history_table_if_not_exists does not use hasattr()
def test_create_history_table_if_not_exists_no_hasattr():
    source = inspect.getsource(BaseProvider.create_history_table_if_not_exists)
    assert "hasattr" not in source


# AC#4.4 — create_history_table_if_not_exists delegates to create_migration_history_table_if_not_exists
def test_create_history_table_if_not_exists_delegates():
    ConcreteProvider = _make_concrete_provider_class()
    provider = ConcreteProvider(config=_make_config())
    provider.create_migration_history_table_if_not_exists = MagicMock()
    provider.create_history_table_if_not_exists("public", table_name="test_table")
    provider.create_migration_history_table_if_not_exists.assert_called_once_with(
        "public", False, "test_table"
    )
