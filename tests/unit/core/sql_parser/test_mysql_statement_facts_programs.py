"""MySQL stored programs, triggers and a nameless-looking index name the object the engine creates.

Checked on MySQL 8.4.11 and MariaDB 11.8.8: every statement below is accepted by the grammar
(a missing table or a missing DETERMINISTIC clause is a later error, not a parse error).
"""

import json
from pathlib import Path

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts


def mysql(sql):
    return read_statement_facts(sql, dialect="mysql")


def objects(facts):
    return [(obj.name, obj.type, obj.role, obj.schema) for obj in facts.objects]


@pytest.mark.parametrize(
    ("sql", "name", "kind", "schema"),
    [
        ("CREATE FUNCTION f() RETURNS INT BEGIN RETURN 1; END", "f", SqlObjectType.FUNCTION, None),
        (
            "CREATE DEFINER=`root`@`%` FUNCTION my_func() RETURNS INT BEGIN RETURN 1; END",
            "my_func",
            SqlObjectType.FUNCTION,
            None,
        ),
        (
            "CREATE FUNCTION mydb.test_func() RETURNS INT BEGIN RETURN 1; END",
            "test_func",
            SqlObjectType.FUNCTION,
            "mydb",
        ),
        (
            "CREATE FUNCTION `test_func`() RETURNS INTEGER LANGUAGE SQL BEGIN RETURN 1; END",
            "test_func",
            SqlObjectType.FUNCTION,
            None,
        ),
        (
            "CREATE EVENT e ON SCHEDULE EVERY 1 HOUR DO BEGIN SELECT 1; END",
            "e",
            SqlObjectType.EVENT,
            None,
        ),
        (
            "CREATE EVENT ev ON SCHEDULE EVERY 1 DAY DO DELETE FROM t",
            "ev",
            SqlObjectType.EVENT,
            None,
        ),
        ("DROP EVENT ev", "ev", SqlObjectType.EVENT, None),
        (
            "CREATE OR REPLACE TRIGGER my_trigger AFTER INSERT ON t FOR EACH ROW BEGIN END",
            "my_trigger",
            SqlObjectType.TRIGGER,
            None,
        ),
        (
            "CREATE OR REPLACE PROCEDURE GetEmployeeCount(OUT total INTEGER) LANGUAGE SQL BEGIN SELECT 1; END",
            "GetEmployeeCount",
            SqlObjectType.PROCEDURE,
            None,
        ),
    ],
)
def test_stored_programs_name_the_program(sql, name, kind, schema):
    facts = mysql(sql)

    role = "dropped" if sql.startswith("DROP") else "created"
    assert (facts.operation, facts.kind) == (("DROP" if role == "dropped" else "CREATE"), "DDL")
    assert (name, kind, role, schema) in objects(facts)
    assert all(obj.role != "created" or obj.name == name for obj in facts.objects)


def test_a_statement_inside_a_trigger_body_is_not_an_object_of_its_own():
    facts = mysql(
        "CREATE TRIGGER tg AFTER INSERT ON u FOR EACH ROW BEGIN CREATE INDEX i ON u (c); END"
    )

    assert ("tg", SqlObjectType.TRIGGER, "created", None) in objects(facts)
    assert all(obj.name != "i" for obj in facts.objects)


@pytest.mark.parametrize(
    ("sql", "trigger", "table", "schema"),
    [
        (
            "CREATE TRIGGER users_bi BEFORE INSERT ON users FOR EACH ROW EXECUTE FUNCTION f()",
            "users_bi",
            "users",
            None,
        ),
        (
            "CREATE TRIGGER trg BEFORE INSERT ON s.t FOR EACH ROW EXECUTE FUNCTION audit('a;b')",
            "trg",
            "t",
            "s",
        ),
        ("CREATE TRIGGER tr BEFORE INSERT ON t FOR EACH ROW SET NEW.a = 1", "tr", "t", None),
        (
            "CREATE TRIGGER `Tg` AFTER UPDATE ON `T` FOR EACH ROW BEGIN SET NEW.a = 1; END",
            "Tg",
            "T",
            None,
        ),
    ],
)
def test_create_trigger_names_the_trigger_and_its_table(sql, trigger, table, schema):
    facts = mysql(sql)

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert (trigger, SqlObjectType.TRIGGER, "created", None) in objects(facts)
    assert (table, SqlObjectType.TABLE, "referenced", schema) in objects(facts)
    assert [obj for obj in facts.objects if obj.role == "created"] == [
        next(obj for obj in facts.objects if obj.name == trigger)
    ]


def test_the_word_after_create_index_is_the_index_name():
    # MySQL has no CONCURRENTLY: ``CREATE INDEX CONCURRENTLY ON orders (email)`` creates an index
    # named CONCURRENTLY on ``orders`` (the engine answers "Table 'orders' doesn't exist").
    facts = mysql("CREATE INDEX CONCURRENTLY ON orders (email)")

    assert objects(facts) == [
        ("CONCURRENTLY", SqlObjectType.INDEX, "created", None),
        ("orders", SqlObjectType.TABLE, "referenced", None),
    ]
    assert facts.indexed_table == "orders"


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE INDEX CONCURRENTLY ix ON t (c)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix ON t (c)",
    ],
)
def test_a_name_after_concurrently_is_not_an_index(sql):
    # The engine reads CONCURRENTLY as the index name and rejects what follows (error 1064).
    facts = mysql(sql)

    assert all(obj.name != "ix" for obj in facts.objects)


def test_a_nameless_create_index_names_no_index():
    # ``CREATE INDEX ON orders (email)`` is rejected by MySQL (error 1064): ``ON`` is not a name.
    facts = mysql("CREATE INDEX ON orders (email)")

    assert all(obj.type != SqlObjectType.INDEX for obj in facts.objects)


OTHER = json.loads(
    Path(__file__).with_name("mysql_facts_programs_other_dialects.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    ("dialect", "sql"), [(d, s) for d in sorted(OTHER) for s in sorted(OTHER[d])]
)
def test_other_dialects_keep_their_reading_of_the_same_forms(dialect, sql):
    facts = read_statement_facts(sql, dialect=dialect)
    assert {
        "operation": facts.operation,
        "kind": facts.kind,
        "opaque": facts.opaque,
        "objects": [[o.name, o.type.value, o.role, o.schema] for o in facts.objects],
        "indexed_table": facts.indexed_table,
        "diagnostic": facts.diagnostic,
    } == OTHER[dialect][sql]
