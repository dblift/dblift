"""In-process cover of the install hint and of the reader's splitting seams."""

from __future__ import annotations

import sys

import pytest

from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit


def test_reading_facts_without_sqlglot_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "sqlglot", None)
    monkeypatch.delitem(
        sys.modules, "dblift.core.sql_parser.sqlglot_statement_facts", raising=False
    )

    with pytest.raises(ModuleNotFoundError, match=r"pip install dblift\[analysis\]") as raised:
        ProviderRegistry.get_quirks("postgresql").statement_facts("SELECT 1")

    assert raised.value.name == "sqlglot"
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)


def test_another_missing_module_is_not_renamed(monkeypatch):
    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "dblift.core.sql_parser.sqlglot_statement_facts":
            raise ModuleNotFoundError("No module named 'other'", name="other")
        return original(name, globals, locals, fromlist, level)

    import builtins

    original = builtins.__import__
    monkeypatch.delitem(
        sys.modules, "dblift.core.sql_parser.sqlglot_statement_facts", raising=False
    )
    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ModuleNotFoundError) as raised:
        ProviderRegistry.get_quirks("postgresql").statement_facts("SELECT 1")

    assert raised.value.name == "other"


class _FixedSplitter:
    _engine = None

    def split_statements(self, sql):
        return ["one", "two"]


def test_a_reader_without_an_engine_analyses_the_execution_split():
    reader = StatementReader("postgresql", statement_splitter=_FixedSplitter())

    assert reader.split_statements_for_analysis("ignored") == ["one", "two"]


def test_last_split_reuses_the_records_of_the_same_script_only():
    splitter = StatementSplitter("postgresql")
    first = splitter.split("SELECT 1; SELECT 2;")

    assert splitter.last_split("SELECT 1; SELECT 2;") == first
    assert [r.text for r in splitter.last_split("SELECT 3;")] == ["SELECT 3"]
