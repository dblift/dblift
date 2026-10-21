"""Snowflake reader identities and explicit boundaries, without native grammar claims."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject


@pytest.mark.parametrize(
    "sql, operation, kind",
    [
        ("SELECT * FROM a.b.c.d", "SELECT", "QUERY"),
        ("CREATE VIEW v AS SELECT * FROM a.b.c.d", "CREATE", "DDL"),
        ("CREATE TABLE t AS SELECT * FROM a.b.c.d", "CREATE", "DDL"),
    ],
)
def test_snowflake_discarded_source_qualifier_has_no_reference_or_effect(sql, operation, kind):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, kind)
    assert facts.objects == ()
    assert facts.target is None
    assert facts.opaque
    assert facts.diagnostic and "qualification" in facts.diagnostic.lower()
    assert facts.error is None


@pytest.mark.parametrize(
    "sql, operation, kind, objects",
    [
        (
            "SELECT * FROM a.b.c",
            "SELECT",
            "QUERY",
            (NamedObject("c", SqlObjectType.TABLE, "referenced", "a.b"),),
        ),
        (
            "CREATE VIEW v AS SELECT * FROM a.b.c",
            "CREATE",
            "DDL",
            (
                NamedObject("v", SqlObjectType.VIEW, "created"),
                NamedObject("c", SqlObjectType.TABLE, "referenced", "a.b"),
            ),
        ),
        (
            "CREATE TABLE t AS SELECT * FROM a.b.c",
            "CREATE",
            "DDL",
            (
                NamedObject("t", SqlObjectType.TABLE, "created"),
                NamedObject("c", SqlObjectType.TABLE, "referenced", "a.b"),
            ),
        ),
    ],
)
def test_snowflake_complete_three_part_reference_is_preserved(sql, operation, kind, objects):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, kind)
    assert facts.objects == objects
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql, operation",
    [
        ("WITH c AS (SELECT 1) UPDATE a.b.c SET x=1", "UPDATE"),
        ("WITH c AS (SELECT 1) INSERT INTO a.b.c SELECT * FROM c", "INSERT"),
        ("WITH c AS (SELECT 1) DELETE FROM a.b.c", "DELETE"),
    ],
)
def test_snowflake_complete_three_part_cte_mutation_target_is_preserved(sql, operation):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, "DML")
    assert facts.affected_objects == (NamedObject("c", SqlObjectType.TABLE, "altered", "a.b"),)
    assert facts.target == "a.b.c"
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql, operation",
    [("\0CREATE TABLE b(y)", "CREATE"), ("\0DROP TABLE child", "DROP")],
)
def test_snowflake_head_requires_a_source_verb_token(sql, operation):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.objects == ()
    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None


@pytest.mark.parametrize(
    "template, operation, kind",
    [
        ("CREATE TABLE {} (x INT)", "CREATE", "DDL"),
        ("DROP TABLE {}", "DROP", "DDL"),
        ("ALTER TABLE {} ADD COLUMN y INT", "ALTER", "DDL"),
        ("CREATE VIEW {} AS SELECT 1", "CREATE", "DDL"),
        ("DROP VIEW {}", "DROP", "DDL"),
        ("CREATE MATERIALIZED VIEW {} AS SELECT x FROM t", "CREATE", "DDL"),
        ("DROP MATERIALIZED VIEW {}", "DROP", "DDL"),
        ("UPDATE {} SET x = 1", "UPDATE", "DML"),
    ],
)
@pytest.mark.parametrize("name", ["a.b.c.d", '"a"."b"/* qualifier */."c"."d"'])
def test_snowflake_discarded_relation_qualifier_has_no_identity(template, operation, kind, name):
    facts = read_statement_facts(template.format(name), dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, kind)
    assert facts.objects == ()
    assert facts.target is None
    assert facts.target_sql is None
    assert facts.predicate is None
    assert facts.opaque
    assert facts.diagnostic
    assert "qualification" in facts.diagnostic.lower()
    assert facts.error is None


@pytest.mark.parametrize("name", ["a.b.c", '"a"."b"/* qualifier */."c"'])
@pytest.mark.parametrize(
    "template, operation, role, object_type",
    [
        ("CREATE TABLE {} (x INT)", "CREATE", "created", SqlObjectType.TABLE),
        ("DROP TABLE {}", "DROP", "dropped", SqlObjectType.TABLE),
        ("ALTER TABLE {} ADD COLUMN y INT", "ALTER", "altered", SqlObjectType.TABLE),
        ("CREATE VIEW {} AS SELECT 1", "CREATE", "created", SqlObjectType.VIEW),
        ("DROP VIEW {}", "DROP", "dropped", SqlObjectType.VIEW),
        (
            "CREATE MATERIALIZED VIEW {} AS SELECT x FROM t",
            "CREATE",
            "created",
            SqlObjectType.MATERIALIZED_VIEW,
        ),
        ("DROP MATERIALIZED VIEW {}", "DROP", "dropped", SqlObjectType.MATERIALIZED_VIEW),
        ("UPDATE {} SET x = 1", "UPDATE", "altered", SqlObjectType.TABLE),
    ],
)
def test_snowflake_complete_three_part_relation_is_preserved(
    name, template, operation, role, object_type
):
    facts = read_statement_facts(template.format(name), dialect="snowflake")

    assert facts.operation == operation
    assert facts.affected_objects == (NamedObject("c", object_type, role, "a.b"),)
    assert not facts.opaque


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
        pytest.param(
            'CREATE SCHEMA "a.b"',
            "CREATE",
            NamedObject("a.b", SqlObjectType.SCHEMA, "created"),
            id="quoted-dot-is-one-name",
        ),
        pytest.param(
            'DROP SCHEMA "a.b"."c.d"',
            "DROP",
            NamedObject("c.d", SqlObjectType.SCHEMA, "dropped", "a.b"),
            id="quoted-dots-are-two-name-parts",
        ),
        pytest.param(
            'CREATE SCHEMA "a"/* qualifier */."b"',
            "CREATE",
            NamedObject("b", SqlObjectType.SCHEMA, "created", "a"),
            id="comment-separated-two-part-create",
        ),
        pytest.param(
            'DROP SCHEMA "a"/* qualifier */."b"',
            "DROP",
            NamedObject("b", SqlObjectType.SCHEMA, "dropped", "a"),
            id="comment-separated-two-part-drop",
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
    "sql, operation",
    [
        ("CREATE SCHEMA a.b.c", "CREATE"),
        ("DROP SCHEMA a.b.c", "DROP"),
        ('CREATE SCHEMA "a"."b"."c"', "CREATE"),
        ('DROP SCHEMA "a"/* qualifier */."b"/* qualifier */."c"', "DROP"),
    ],
)
def test_snowflake_three_part_schema_identity_is_opaque(sql, operation):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.objects == facts.affected_objects == ()
    assert facts.diagnostic
    assert "snowflake schema qualification" in facts.diagnostic.lower()
    assert facts.error is None
    assert facts.opaque


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
        pytest.param(
            'CREATE MATERIALIZED VIEW "LOG" AS SELECT id FROM t',
            "CREATE",
            NamedObject("LOG", SqlObjectType.MATERIALIZED_VIEW, "created"),
            id="quoted-log-is-a-view-name",
        ),
        pytest.param(
            'DROP MATERIALIZED VIEW "LOG"',
            "DROP",
            NamedObject("LOG", SqlObjectType.MATERIALIZED_VIEW, "dropped"),
            id="drop-view-named-log",
        ),
        pytest.param(
            "CREATE MATERIALIZED VIEW LOG AS SELECT 1",
            "CREATE",
            NamedObject("LOG", SqlObjectType.MATERIALIZED_VIEW, "created"),
            id="unquoted-log-is-a-view-name",
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
    "sql, operation",
    [
        ("CREATE MATERIALIZED VIEW LOG ON t", "CREATE"),
        ("DROP MATERIALIZED VIEW LOG ON t", "DROP"),
        ("CREATE /* head */ MATERIALIZED VIEW /* gap */ LOG /* owner */ ON t", "CREATE"),
        ("DROP MATERIALIZED VIEW /* gap */ LOG /* owner */ ON t", "DROP"),
        ("CREATE OR REPLACE MATERIALIZED VIEW LOG ON t", "CREATE"),
        ("DROP MATERIALIZED VIEW IF EXISTS LOG ON t", "DROP"),
        ("CREATE MATERIALIZED VIEW // comment\n LOG ON t", "CREATE"),
    ],
)
def test_snowflake_materialized_view_log_form_is_opaque(sql, operation):
    facts = read_statement_facts(sql, dialect="snowflake")

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.objects == facts.affected_objects == ()
    assert facts.diagnostic
    assert "snowflake materialized view log" in facts.diagnostic.lower()
    assert facts.error is None
    assert facts.opaque


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
