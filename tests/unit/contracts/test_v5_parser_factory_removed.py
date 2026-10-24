"""The parser factory, the analyzer and the parser-class hook are gone in v5.

Statements are split by `StatementSplitter` and read by the plugin's statement facts
(`quirks.statement_facts`, `read_statement_facts`); nothing builds a parser by name.
"""

from __future__ import annotations

import importlib
import importlib.util

import pytest

from dblift.db.base_quirks import BaseQuirks
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit

REMOVED_MODULES = [
    "dblift.core.sql_parser.parser_factory",
    "dblift.core.sql_parser._deprecation",
    "dblift.core.migration.sql.sql_analyzer",
    "dblift.db.plugins.mysql.parser.mysql_facts_parser",
    "dblift.db.plugins.mariadb.facts_parser",
    "dblift.db.plugins.sqlite.parser.sqlite_facts_parser",
    "dblift.db.plugins.snowflake.lexical_parser",
]


@pytest.mark.parametrize("module", REMOVED_MODULES)
def test_the_module_is_gone(module):
    assert importlib.util.find_spec(module) is None


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("dblift.db.plugins.duckdb.parser.duckdb_facts_parser", "DuckDBFactsParser"),
        ("dblift.db.plugins.db2.parser.statement_facts", "Db2FactsParser"),
        ("dblift.core.migration.sql.statement_reader", "SqlAnalyzer"),
    ],
)
def test_the_class_is_gone_from_its_module(module, name):
    assert not hasattr(importlib.import_module(module), name)


def test_the_names_are_gone_from_the_package():
    import dblift.core.sql_parser as package

    assert not hasattr(package, "SqlParserFactory")
    assert "SqlParserFactory" not in package.__all__


def test_the_quirks_no_longer_name_a_parser_class():
    assert not hasattr(BaseQuirks, "parser_class")
    for plugin in ProviderRegistry.list_plugins():
        assert not hasattr(ProviderRegistry.get_quirks(plugin.name), "parser_class")


def test_the_facts_parser_survives_without_the_factory():
    from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser

    parser = StatementFactsParser(ProviderRegistry.get_quirks("postgresql"))
    assert parser.split_statements("SELECT 1; SELECT 2;") == ["SELECT 1;", "SELECT 2;"]
