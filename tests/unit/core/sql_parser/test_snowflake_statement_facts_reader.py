"""Snowflake reader identities and explicit boundaries, without native grammar claims."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject


@pytest.mark.parametrize(
    "sql, operation, identity",
    [
        pytest.param(
            'CREATE SCHEMA IF NOT EXISTS "APP"',
            "CREATE",
            NamedObject("APP", SqlObjectType.SCHEMA, "created"),
            id="06c17bf92030b519",
        ),
        pytest.param(
            'DROP SCHEMA "Warehouse"."Reporting" CASCADE',
            "DROP",
            NamedObject("Reporting", SqlObjectType.SCHEMA, "dropped", "Warehouse"),
            id="899c3c99c43246a7",
        ),
    ],
)
def test_snowflake_schema_identity_is_read(sql, operation, identity):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.objects == facts.affected_objects == (identity,)
    assert facts.diagnostic is None
    assert facts.error is None


@pytest.mark.parametrize(
    "sql, operation, identity",
    [
        pytest.param(
            'CREATE MATERIALIZED VIEW "S"."ORDER_COUNTS" AS ' 'SELECT id FROM "S"."ORDERS"',
            "CREATE",
            NamedObject("ORDER_COUNTS", SqlObjectType.MATERIALIZED_VIEW, "created", "S"),
            id="create-materialized-view-bounded-probe",
        ),
        pytest.param(
            'DROP MATERIALIZED VIEW IF EXISTS "S"."ORDER_COUNTS"',
            "DROP",
            NamedObject("ORDER_COUNTS", SqlObjectType.MATERIALIZED_VIEW, "dropped", "S"),
            id="73038d91ee5cb697",
        ),
    ],
)
def test_snowflake_materialized_view_identity_is_typed(sql, operation, identity):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.affected_objects == (identity,)
    assert facts.diagnostic is None
    assert facts.error is None


@pytest.mark.parametrize(
    "sql, operation, subject",
    [
        pytest.param("CREATE STAGE stage1", "CREATE", "STAGE", id="create-stage-bounded-probe"),
        pytest.param(
            'DROP FILE FORMAT IF EXISTS "S"."CSV_FMT"',
            "DROP",
            "FILE FORMAT",
            id="4b52534407d0f882",
        ),
        pytest.param('DROP STAGE IF EXISTS "S"."LANDING"', "DROP", "STAGE", id="f2e09deb93a6cabe"),
        pytest.param('DROP TAG IF EXISTS "S"."PII"', "DROP", "TAG", id="686001cd0f92670c"),
    ],
)
def test_unmodelled_snowflake_ddl_identity_is_explicitly_opaque(sql, operation, subject):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.objects == facts.affected_objects == ()
    assert facts.diagnostic
    assert "snowflake" in facts.diagnostic.lower()
    assert subject.lower() in facts.diagnostic.lower()
    assert facts.error is None
    assert facts.opaque


@pytest.mark.parametrize(
    "sql, object_type, name, schema",
    [
        ('CREATE TABLE "QA"."A;B" ("V" VARCHAR)', SqlObjectType.TABLE, "A;B", "QA"),
        ('CREATE VIEW "S"."V" AS SELECT 1', SqlObjectType.VIEW, "V", "S"),
    ],
)
def test_plain_relation_reader_facts_remain_available(sql, object_type, name, schema):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert facts.objects == (NamedObject(name, object_type, "created", schema),)
    assert facts.diagnostic is None
