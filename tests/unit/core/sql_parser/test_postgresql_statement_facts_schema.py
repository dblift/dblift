"""PostgreSQL schema identities without activating parser consumers."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks


@pytest.mark.parametrize(
    "sql,name",
    [
        ("CREATE SCHEMA sales;", "sales"),
        ('CREATE SCHEMA IF NOT EXISTS "Sales";', "Sales"),
        ('CREATE SCHEMA " Sales Team ";', " Sales Team "),
        ('CREATE SCHEMA "a""b";', 'a"b'),
    ],
    ids=["bare", "if_not_exists", "quoted_whitespace", "escaped_quote"],
)
def test_create_schema_facts_keep_the_created_identity(sql, name):
    facts = read_statement_facts(sql, dialect="postgres")

    assert facts == StatementFacts(
        "CREATE", "DDL", (NamedObject(name, SqlObjectType.SCHEMA, "created"),)
    )


def test_create_table_facts_keep_the_table_and_schema_identity():
    facts = read_statement_facts('CREATE TABLE "Sales"."Items" (id INT)', dialect="postgres")

    assert facts == StatementFacts(
        "CREATE",
        "DDL",
        (NamedObject("Items", SqlObjectType.TABLE, "created", "Sales"),),
        declared_columns=("id",),
        events=frozenset(),
    )


def test_authorization_only_schema_facts_remain_opaque():
    facts = read_statement_facts("CREATE SCHEMA AUTHORIZATION owner_role", dialect="postgres")

    assert facts.operation == "CREATE"
    assert facts.kind == "DDL"
    assert facts.objects == ()
    assert facts.opaque
    assert facts.error is None


@pytest.mark.parametrize("dialect", ["sqlite", "oracle"])
def test_schema_identity_projection_does_not_expand_to_other_dialects(dialect):
    facts = read_statement_facts("CREATE SCHEMA sales", dialect=dialect)

    assert facts.objects == ()
