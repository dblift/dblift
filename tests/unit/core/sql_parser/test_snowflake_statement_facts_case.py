"""Snowflake stores an unquoted name in upper case and a quoted one as written.

Measured on Snowflake 10.38.100 with QUOTED_IDENTIFIERS_IGNORE_CASE = FALSE (the default):
``DBLIFT_QA.D2_QA_...`` and ``DBLIFT_QA."d2_qa_..."`` are two schemas, and so are the
materialized views ``LOG`` and ``"log"``. The names are compared as stored only under that
default.
"""

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts


def _facts(sql):
    return read_statement_facts(sql, dialect="snowflake")


def _objects(sql):
    return [(o.name, o.type.value, o.role, o.schema) for o in _facts(sql).objects]


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("CREATE SCHEMA app", [("APP", "SCHEMA", "created", None)]),
        ('CREATE SCHEMA "app"', [("app", "SCHEMA", "created", None)]),
        ("CREATE SCHEMA db.app", [("APP", "SCHEMA", "created", "DB")]),
        ('CREATE SCHEMA "db".app', [("APP", "SCHEMA", "created", "db")]),
        ("DROP SCHEMA app", [("APP", "SCHEMA", "dropped", None)]),
        ('DROP SCHEMA db."app"', [("app", "SCHEMA", "dropped", "DB")]),
        ("CREATE TABLE users (a int)", [("USERS", "TABLE", "created", None)]),
        ('CREATE TABLE "Users" (a int)', [("Users", "TABLE", "created", None)]),
        ("CREATE TABLE s.users (a int)", [("USERS", "TABLE", "created", "S")]),
        ('CREATE TABLE "s".Users (a int)', [("USERS", "TABLE", "created", "s")]),
        ('CREATE TABLE a."b".c (x int)', [("C", "TABLE", "created", "A.b")]),
        ("DROP TABLE IF EXISTS users", [("USERS", "TABLE", "dropped", None)]),
        ("ALTER TABLE users ADD COLUMN c int", [("USERS", "TABLE", "altered", None)]),
        (
            "CREATE TABLE t CLONE src",
            [("T", "TABLE", "created", None), ("SRC", "TABLE", "referenced", None)],
        ),
        (
            "CREATE MATERIALIZED VIEW log AS SELECT 1",
            [("LOG", "MATERIALIZED_VIEW", "created", None)],
        ),
        (
            'CREATE MATERIALIZED VIEW "log" AS SELECT 1',
            [("log", "MATERIALIZED_VIEW", "created", None)],
        ),
        ("SELECT * FROM users", [("USERS", "TABLE", "referenced", None)]),
        ("INSERT INTO app.users VALUES (1)", [("USERS", "TABLE", "altered", "APP")]),
        ('UPDATE "Users" SET a = 1 WHERE b = 2', [("Users", "TABLE", "altered", None)]),
        ("DELETE FROM users WHERE a = 1", [("USERS", "TABLE", "altered", None)]),
        ("ALTER TABLE customers", [("CUSTOMERS", "TABLE", "altered", None)]),
        ("ALTER TABLE sales.orders ADD CONSTRAINT x", [("ORDERS", "TABLE", "altered", "SALES")]),
    ],
)
def test_unquoted_names_are_upper_case_and_quoted_names_exact(sql, expected):
    assert _objects(sql) == expected


def test_an_unquoted_and_a_quoted_schema_are_two_objects():
    assert _objects("CREATE SCHEMA app") != _objects('CREATE SCHEMA "app"')


def test_a_mutation_target_is_folded_but_its_text_stays_as_written():
    facts = _facts("UPDATE app.users SET a = 1 WHERE b = 2")

    assert facts.target == "APP.USERS"
    assert facts.target_sql == "app.users"


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE éclair (a int)",
        "CREATE TABLE ıx (a int)",
        "CREATE TABLE µt (a int)",
        "CREATE TABLE aé.t (a int)",
        "CREATE TABLE s.éclair (a int)",
        "DROP TABLE éclair",
        "ALTER TABLE éclair ADD COLUMN c int",
        "UPDATE éclair SET a = 1 WHERE b = 2",
        "INSERT INTO éclair VALUES (1)",
        "CREATE SCHEMA aé",
        "CREATE TABLE straße (a int)",
        "DROP TABLE s.straße",
    ],
)
def test_an_unquoted_name_with_a_non_ascii_letter_is_unread(sql):
    """The engine rejects unquoted ``é``, ``aé`` and ``a©b`` (docs/sql-parsing/snowflake.md,
    section 2), so a statement holding one names no object."""
    facts = _facts(sql)

    assert facts.opaque
    assert facts.objects == ()
    assert facts.target is None
    assert facts.diagnostic


@pytest.mark.parametrize(
    "sql, expected",
    [
        ('CREATE TABLE "éclair" (a int)', [("éclair", "TABLE", "created", None)]),
        ('CREATE TABLE "aé".t (a int)', [("T", "TABLE", "created", "aé")]),
        ('CREATE TABLE "straße" (a int)', [("straße", "TABLE", "created", None)]),
        ('DROP TABLE "ıx"', [("ıx", "TABLE", "dropped", None)]),
    ],
)
def test_a_quoted_name_is_read_exactly_whatever_it_holds(sql, expected):
    assert _objects(sql) == expected


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("INSERT INTO app.t(a) VALUES (1) /*", [("T", "TABLE", "altered", "APP")]),
        ("INSERT INTO app.t(", [("T", "TABLE", "altered", "APP")]),
    ],
)
def test_the_head_of_an_unparsed_mutation_folds_its_target(sql, expected):
    facts = _facts(sql)

    assert facts.opaque
    assert _objects(sql) == expected


def test_a_subquery_table_in_a_predicate_keeps_the_written_spelling():
    facts = _facts("DELETE FROM app.users WHERE id IN (SELECT id FROM Other)")

    assert facts.predicate == "id IN (SELECT id FROM Other)"


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TRIGGER trë BEFORE INSERT ON t FOR EACH ROW EXECUTE FUNCTION f()",
        "INSERT INTO éx(",
        "INSERT INTO sé.t(a) VALUES (1) /*",
        "UPDATE sé.t SET a{c}b = 1",
        "UPDATE éx SET a = 1 WHERE b",
    ],
)
def test_the_head_of_an_unparsed_statement_never_folds_a_non_ascii_name(sql):
    facts = _facts(sql)

    assert facts.opaque
    assert facts.objects == ()
