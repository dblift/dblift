"""DuckDB schema facts retain identities through scanner-backed parser consumers."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks
from tests.support.facts_parser import facts_parser


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
    statements = facts_parser("duckdb").split(sql)
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


def test_schema_facts_share_duckdb_parser_consumers():
    quirks = DuckDBQuirks()

    assert quirks.supports_statement_facts


@pytest.mark.parametrize("dialect", ["sqlite", "tsql"])
@pytest.mark.parametrize(
    "sql,operation,kind,opaque",
    [
        ("DROP SCHEMA s CASCADE", "DROP", "DDL", False),
        ("COMMENT ON TABLE child IS 'note'", "COMMENT", "UNKNOWN", True),
        ("SHOW TABLES", "SHOW", "UNKNOWN", True),
        ("DESCRIBE child", "DESCRIBE", "UNKNOWN", True),
    ],
)
def test_duckdb_schema_and_metadata_mappings_preserve_other_dialects(
    dialect, sql, operation, kind, opaque
):
    facts = read_statement_facts(sql, dialect=dialect)
    assert facts.operation == operation
    assert facts.kind == kind
    if dialect == "tsql" and sql == "DROP SCHEMA s CASCADE":
        assert facts.objects == (NamedObject("s", SqlObjectType.SCHEMA, "dropped"),)
    else:
        assert facts.objects == ()
    assert facts.opaque is opaque


@pytest.mark.parametrize("dialect", ["postgres"])
@pytest.mark.parametrize(
    "sql,operation,kind,opaque",
    [
        ("SHOW TABLES", "SHOW", "UNKNOWN", True),
        ("DESCRIBE child", "DESCRIBE", "UNKNOWN", True),
    ],
)
def test_duckdb_metadata_mappings_preserve_postgres(dialect, sql, operation, kind, opaque):
    facts = read_statement_facts(sql, dialect=dialect)
    assert facts.operation == operation
    assert facts.kind == kind
    assert facts.objects == ()
    assert facts.opaque is opaque


@pytest.mark.parametrize(
    "dialect,expected",
    [
        ("sqlite", "child AS c"),
        ("postgres", "child"),
        ("oracle", "child c"),
        ("mysql", "child"),
        ("tsql", "child"),
    ],
)
def test_target_alias_normalization_preserves_each_dialect_contract(dialect, expected):
    facts = read_statement_facts("UPDATE child AS c SET id = 2 WHERE c.id = 1", dialect=dialect)
    assert facts.target_sql == expected
