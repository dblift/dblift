"""Snowflake forms whose affected objects the shared mappings would drop or mistype."""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject


def _facts(sql):
    return read_statement_facts(sql, dialect="snowflake")


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TRIGGER trg BEFORE INSERT ON s.t FOR EACH ROW EXECUTE FUNCTION audit('a;b')",
        'CREATE TRIGGER "Tg" AFTER INSERT ON "T" FOR EACH ROW EXECUTE FUNCTION f()',
    ],
)
def test_create_whose_object_is_not_read_is_not_presented_as_a_reference_only(sql):
    facts = _facts(sql)

    assert facts.opaque
    assert facts.error is None
    assert not any(
        obj.type == SqlObjectType.TABLE and obj.role == "referenced" for obj in facts.objects
    )


def test_unnamed_index_keeps_its_referenced_table():
    facts = _facts("CREATE INDEX ON orders (email)")

    assert not facts.opaque
    assert facts.objects == (NamedObject("orders", SqlObjectType.TABLE, "referenced"),)


@pytest.mark.parametrize(
    "sql, operation",
    [
        ("INSERT INTO t{c} VALUES (1)", "INSERT"),
        ("UPDATE t{c} SET a = 1 WHERE b = 2", "UPDATE"),
        ("WITH x AS (SELECT 1) DELETE FROM u{c} WHERE a = 1", "DELETE"),
    ],
)
def test_mutation_without_a_read_target_is_opaque(sql, operation):
    facts = _facts(sql)

    assert (facts.operation, facts.kind) == (operation, "DML")
    assert facts.opaque
    assert facts.affected_objects == ()
    assert facts.target is None


@pytest.mark.parametrize(
    "sql",
    [
        "WITH d AS (INSERT INTO t VALUES (1) RETURNING id) SELECT * FROM d",
        "WITH x AS (UPDATE src SET id = id RETURNING id) INSERT INTO app_logs(msg) SELECT 'x' FROM x",
        "WITH d AS (DELETE FROM src WHERE id = 1 RETURNING id) INSERT INTO log(msg) SELECT 1 FROM d",
    ],
)
def test_common_table_expression_that_writes_is_opaque(sql):
    facts = _facts(sql)

    assert facts.opaque
    assert facts.error is None
    assert "cte" in facts.diagnostic.lower()


def test_query_common_table_expression_is_still_read():
    facts = _facts("WITH c AS (SELECT * FROM users) SELECT * FROM c")

    assert not facts.opaque
    assert facts.objects == (NamedObject("users", SqlObjectType.TABLE, "referenced"),)


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER TABLE t RENAME TO u",
        "ALTER TABLE IF EXISTS t RENAME TO u",
        "ALTER TABLE s.t SWAP WITH s.u",
        "ALTER VIEW v RENAME TO v2",
        "ALTER INDEX idx RENAME TO idx2",
    ],
)
def test_rename_and_swap_name_a_second_object_so_they_are_opaque(sql):
    facts = _facts(sql)

    assert facts.operation == "ALTER"
    assert facts.opaque
    assert facts.error is None
    assert not any(obj.role == "created" for obj in facts.objects)


@pytest.mark.parametrize(
    "sql",
    ["ALTER TABLE t RENAME COLUMN a TO b", "ALTER TABLE t ADD COLUMN c INT"],
)
def test_alter_of_a_single_table_is_still_read(sql):
    facts = _facts(sql)

    assert not facts.opaque
    assert facts.objects == (NamedObject("t", SqlObjectType.TABLE, "altered"),)


@pytest.mark.parametrize(
    "sql, created, source",
    [
        (
            "CREATE SCHEMA s2 CLONE s",
            NamedObject("s2", SqlObjectType.SCHEMA, "created"),
            NamedObject("s", SqlObjectType.SCHEMA, "referenced"),
        ),
        (
            "CREATE OR REPLACE SCHEMA d.s2 CLONE d.s",
            NamedObject("s2", SqlObjectType.SCHEMA, "created", "d"),
            NamedObject("s", SqlObjectType.SCHEMA, "referenced", "d"),
        ),
        (
            "CREATE DATABASE d2 CLONE d",
            NamedObject("d2", SqlObjectType.DATABASE, "created"),
            NamedObject("d", SqlObjectType.DATABASE, "referenced"),
        ),
        (
            "CREATE SEQUENCE sq2 CLONE sq",
            NamedObject("sq2", SqlObjectType.SEQUENCE, "created"),
            NamedObject("sq", SqlObjectType.SEQUENCE, "referenced"),
        ),
        (
            "CREATE TABLE t2 CLONE s.t",
            NamedObject("t2", SqlObjectType.TABLE, "created"),
            NamedObject("t", SqlObjectType.TABLE, "referenced", "s"),
        ),
    ],
)
def test_clone_source_has_the_type_of_the_object_it_copies(sql, created, source):
    facts = _facts(sql)

    assert facts.objects == (created, source)
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM @st",
        "SELECT * FROM @st/path (FILE_FORMAT => 'ff')",
        "SELECT * FROM t WHERE a IN (SELECT a FROM @st)",
        "INSERT INTO t SELECT * FROM @st",
    ],
)
def test_stage_reference_is_not_a_table_reference(sql):
    facts = _facts(sql)

    assert facts.opaque
    assert facts.error is None
    assert not any(obj.name.startswith("@") for obj in facts.objects)
    assert "stage" in facts.diagnostic.lower()


@pytest.mark.parametrize(
    "sql, target, target_sql",
    [
        ("UPDATE child AS c SET id = 2 WHERE c.id = 1", "child", "child"),
        ("DELETE FROM child AS c WHERE c.id = 1", "child", "child"),
        ('UPDATE "S"."T" AS c SET x = 1', "S.T", '"S"."T"'),
        ("UPDATE t SET a = 1", "t", "t"),
    ],
)
def test_mutation_target_sql_is_the_bare_table_reference(sql, target, target_sql):
    facts = _facts(sql)

    assert (facts.target, facts.target_sql) == (target, target_sql)
