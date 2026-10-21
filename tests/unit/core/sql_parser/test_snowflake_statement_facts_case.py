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


@pytest.mark.parametrize("sql", ["CREATE TABLE straße (a int)", "DROP TABLE s.straße"])
def test_a_letter_with_no_one_character_upper_case_form_leaves_the_name_unread(sql):
    facts = _facts(sql)

    assert facts.opaque
    assert facts.objects == ()
    assert "upper-case form" in facts.diagnostic


def test_a_quoted_name_with_such_a_letter_is_read_as_written():
    assert _objects('CREATE TABLE "straße" (a int)') == [("straße", "TABLE", "created", None)]
