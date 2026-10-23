"""The legacy regex, hybrid and sqlglot parser stacks are gone in v5.

Every SQL dialect is split by its lexical spec and read through its statement facts; there is no
second grammar to fall back to.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from dblift.core.exceptions import UnsupportedDialectError
from dblift.core.sql_parser import SqlParserFactory
from dblift.core.sql_parser._deprecation import internal_parser_construction
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.provider_registry import ProviderRegistry

pytestmark = pytest.mark.unit

REMOVED_MODULES = [
    "dblift.core.sql_parser.hybrid_parser",
    "dblift.core.sql_parser.sqlglot_parser",
    "dblift.core.sql_parser.enhanced_regex_parser",
    "dblift.core.sql_parser.unified_regex_parser",
    "dblift.core.sql_parser._sqlglot_builders",
    "dblift.core.sql_parser.common.base_parser",
    "dblift.core.sql_parser.dialects.base_config",
    "dblift.db.plugins.postgresql.parser.parser_config",
    "dblift.db.plugins.postgresql.parser.postgresql_regex_parser",
    "dblift.db.plugins.redshift.parser.redshift_regex_parser",
    "dblift.db.plugins.mysql.parser.parser_config",
    "dblift.db.plugins.mysql.parser.mysql_regex_parser",
    "dblift.db.plugins.mariadb.regex_parser",
    "dblift.db.plugins.sqlserver.parser.parser_config",
    "dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser",
    "dblift.db.plugins.db2.parser.parser_config",
    "dblift.db.plugins.db2.parser.db2_regex_parser",
    "dblift.db.plugins.duckdb.parser.parser_config",
    "dblift.db.plugins.duckdb.parser.duckdb_regex_parser",
    "dblift.db.plugins.oracle.parser.oracle_parser",
    "dblift.db.plugins.oracle.parser._object_extractor",
    "dblift.db.plugins.snowflake.statement_parser",
]


@pytest.mark.parametrize("module", REMOVED_MODULES)
def test_the_legacy_parser_module_is_gone(module):
    assert importlib.util.find_spec(module) is None


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlserver", "oracle", "db2", "sqlite"])
@pytest.mark.parametrize("parser_type", [None, "regex", "hybrid", "sqlglot"])
def test_every_parser_type_is_served_the_facts_parser(dialect, parser_type):
    with internal_parser_construction():
        parser = SqlParserFactory(dialect, parser_type).get_parser()
    assert isinstance(parser, StatementFactsParser)


@pytest.mark.parametrize("dialect", ["mongodb", "cosmosdb"])
def test_a_dialect_without_statement_facts_has_no_parser(dialect):
    with internal_parser_construction(), pytest.raises(UnsupportedDialectError):
        SqlParserFactory(dialect).get_parser()


def test_no_fallback_chain_remains_in_the_parser_package():
    root = Path(__file__).resolve().parents[3] / "dblift" / "core" / "sql_parser"
    offenders = [
        f"{path.name}:{number}"
        for path in sorted(root.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"fall(?:s)?[ -]?back", line, re.IGNORECASE)
    ]
    assert offenders == []


@pytest.mark.parametrize("name", sorted(p.name for p in ProviderRegistry.list_plugins()))
def test_the_quirks_hook_names_no_legacy_parser(name):
    cls = ProviderRegistry.get_quirks(name).parser_class("regex")
    assert cls is None or issubclass(cls, StatementFactsParser)
