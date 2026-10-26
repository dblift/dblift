"""A permissive grammar must not prove objects for unsupported dialect syntax."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE UNLOGGED TABLE t AS SELECT x FROM orders",
        "CREATE TABLE t TABLESPACE fast AS SELECT x FROM orders",
        "CREATE UNLOGGED TABLE t TABLESPACE fast AS SELECT x FROM orders",
    ],
)
def test_redshift_rejects_postgres_only_create_table_clauses_as_facts(sql):
    facts = read_statement_facts(sql, dialect="redshift")

    assert facts.operation == "CREATE"
    assert facts.objects == ()
    assert facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TRIGGER trg ON t",
        "DROP TRIGGER IF EXISTS trg ON s.t",
    ],
)
def test_mysql_does_not_name_postgres_only_drop_trigger_on_clause(sql):
    facts = read_statement_facts(sql, dialect="mysql")

    assert facts.operation == "DROP"
    assert facts.objects == ()
    assert facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t AS SELECT x FROM orders",
        "CREATE TABLE t AS SELECT tablespace FROM orders",
    ],
)
def test_redshift_valid_create_table_as_keeps_its_objects(sql):
    facts = read_statement_facts(sql, dialect="redshift")

    assert not facts.opaque
    assert [(obj.name, obj.type, obj.role) for obj in facts.objects] == [
        ("t", SqlObjectType.TABLE, "created"),
        ("orders", SqlObjectType.TABLE, "referenced"),
    ]


def test_mysql_valid_drop_trigger_keeps_its_object():
    facts = read_statement_facts("DROP TRIGGER trg", dialect="mysql")

    assert not facts.opaque
    assert [(obj.name, obj.type, obj.role) for obj in facts.objects] == [
        ("trg", SqlObjectType.TRIGGER, "dropped"),
    ]
