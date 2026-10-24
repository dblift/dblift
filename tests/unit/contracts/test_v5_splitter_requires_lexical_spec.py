"""A dialect is split by its lexical spec only; there is no second grammar behind the splitter."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsupportedDialectError
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("dialect", ["mongodb", "cosmosdb"])
def test_a_dialect_without_a_lexical_spec_is_refused_when_it_splits(dialect):
    assert ProviderRegistry.get_quirks(dialect).lexical_spec() is None
    with pytest.raises(UnsupportedDialectError):
        StatementSplitter(dialect).split("SELECT 1;")


def test_a_plugin_that_only_offers_a_parser_class_is_refused(monkeypatch):
    quirks = ProviderRegistry.get_quirks("sqlite")
    monkeypatch.setattr(type(quirks), "lexical_spec", lambda self: None)
    with pytest.raises(UnsupportedDialectError):
        StatementSplitter("sqlite").split("SELECT 1;")


def test_the_splitter_keeps_no_parser_factory():
    assert not hasattr(StatementSplitter("sqlite"), "parser_factory")
