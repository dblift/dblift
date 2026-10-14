"""DuckDB schema facts retain identities without activating parser consumers."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts
from dblift.db.plugins.duckdb.parser._script import scan_script
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks


@pytest.mark.parametrize(
    "sql,name,qualification",
    [
        ("CREATE SCHEMA analytics;", "analytics", None),
        ('CREATE SCHEMA IF NOT EXISTS "Sales";', "Sales", None),
        ('CREATE SCHEMA "Warehouse"."Reporting";', "Reporting", "Warehouse"),
        ('CREATE SCHEMA "a""b";', 'a"b', None),
    ],
    ids=["unqualified", "if_not_exists", "catalog_qualified", "escaped_quote"],
)
def test_create_schema_facts_keep_the_created_identity(sql, name, qualification):
    statements = scan_script(sql)
    assert len(statements) == 1

    facts = read_statement_facts(statements[0].text, dialect="duckdb")

    assert facts == StatementFacts(
        "CREATE", "DDL", (NamedObject(name, SqlObjectType.SCHEMA, "created", qualification),)
    )


def test_create_table_facts_keep_the_table_and_schema_identity():
    facts = read_statement_facts('CREATE TABLE "Sales"."Items" (id INT)', dialect="duckdb")

    assert facts == StatementFacts(
        "CREATE",
        "DDL",
        (NamedObject("Items", SqlObjectType.TABLE, "created", "Sales"),),
        declared_columns=("id",),
    )


def test_schema_facts_do_not_activate_duckdb_parser_consumers():
    quirks = DuckDBQuirks()

    assert not quirks.supports_statement_facts
    assert quirks.parser_class("regex") is DuckDBRegexParser
    assert quirks.parser_class("hybrid") is HybridParser
    assert quirks.parser_class("sqlglot") is SqlGlotParser
