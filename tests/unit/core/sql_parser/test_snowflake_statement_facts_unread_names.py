"""Snowflake names the reader cannot resolve are never published as an object."""

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts


def _facts(sql):
    return read_statement_facts(sql, dialect="snowflake")


DYNAMIC = [
    "CREATE TABLE IDENTIFIER($db || '.s.t') (a int)",
    "CREATE TABLE IDENTIFIER($t) (a int)",
    "CREATE VIEW IDENTIFIER($a || 'x') AS SELECT 1",
    "DROP TABLE IDENTIFIER($a || 'x')",
    "DROP TABLE IDENTIFIER($t)",
    "DROP VIEW IDENTIFIER('v')",
    "INSERT INTO IDENTIFIER($a || 'x') VALUES (1)",
    "INSERT INTO IDENTIFIER($t) VALUES (1)",
    "UPDATE IDENTIFIER($t) SET a = 1",
    "UPDATE IDENTIFIER($a || 'x') SET a = 1",
    "DELETE FROM IDENTIFIER($t)",
    "DELETE FROM IDENTIFIER($a || 'x')",
    "DELETE FROM s.IDENTIFIER($t) WHERE a = 1",
    "ALTER TABLE IDENTIFIER($t) RENAME TO x",
    "ALTER TABLE IDENTIFIER($t) SWAP WITH x",
    "ALTER TABLE IDENTIFIER($t) ADD COLUMN c int",
    "ALTER TABLE x RENAME TO IDENTIFIER($t)",
    "ALTER TABLE x SWAP WITH IDENTIFIER($t)",
    "ALTER TABLE IDENTIFIER($db).s.t ADD COLUMN c int",
    "SELECT * FROM TABLE(IDENTIFIER($t))",
    "SELECT * FROM IDENTIFIER($t)",
    "SELECT * FROM IDENTIFIER('s.t')",
    "CREATE TABLE IDENTIFIER($db).s.t (a int)",
    "CREATE TABLE s.IDENTIFIER($t) (a int)",
    "CREATE TABLE IDENTIFIER($db).IDENTIFIER($s).t (a int)",
    "CREATE TABLE IDENTIFIER('db.sch.t') (a int)",
    "CREATE TABLE IDENTIFIER('\"a b\"') (a int)",
    "CREATE TABLE t CLONE IDENTIFIER($src)",
    "CREATE TABLE t CLONE s.IDENTIFIER($src)",
    "DROP SCHEMA IDENTIFIER('s1')",
    "DROP SCHEMA IDENTIFIER($s) CASCADE",
    "CREATE SCHEMA IDENTIFIER($s)",
    "CREATE SCHEMA IDENTIFIER($db).s",
    "DROP TABLE $t",
    "CREATE TABLE $t (a int)",
    "DROP TABLE $db.s.t",
    "DROP TABLE s.$t",
    "INSERT INTO $t VALUES (1)",
]


@pytest.mark.parametrize("sql", DYNAMIC)
def test_a_name_computed_at_run_time_is_not_read(sql):
    facts = _facts(sql)

    assert facts.opaque
    assert facts.error is None
    assert facts.objects == ()
    assert facts.target is None
    assert "IDENTIFIER() names are not read" in facts.diagnostic


@pytest.mark.parametrize(
    "sql, operation",
    [
        ("DROP TABLE IDENTIFIER", "DROP"),
        ("ALTER TABLE ADD COLUMN x int", "ALTER"),
        ("CREATE TABLE CLONE x", "CREATE"),
        ("DROP TABLE IF", "DROP"),
        ("DROP TABLE CASCADE", "DROP"),
        ("CREATE TABLE IF", "CREATE"),
        ("CREATE TABLE s{c}.t (a int)", "CREATE"),
    ],
)
def test_a_keyword_is_not_read_as_an_object_name(sql, operation):
    facts = _facts(sql)

    assert facts.operation == operation
    assert facts.opaque
    assert facts.error is None
    assert facts.objects == ()
    assert facts.diagnostic


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("DROP TABLE t", [("T", "dropped")]),
        ("DROP TABLE IF EXISTS t", [("T", "dropped")]),
        ("CREATE TABLE IF NOT EXISTS t (a int)", [("T", "created")]),
        ("CREATE TABLE t CLONE s.src", [("T", "created"), ("SRC", "referenced")]),
        ("ALTER TABLE t ADD COLUMN c int", [("T", "altered")]),
        ("DROP TABLE t CASCADE", [("T", "dropped")]),
        ("INSERT INTO t VALUES (1)", [("T", "altered")]),
        ("SELECT $1 FROM t", [("T", "referenced")]),
    ],
)
def test_a_plain_name_is_still_read(sql, expected):
    facts = _facts(sql)

    assert not facts.opaque
    assert [(obj.name, obj.role) for obj in facts.objects] == expected


@pytest.mark.parametrize("sql", ["DROP ROLE r", "DROP ROLE IF EXISTS r"])
def test_drop_role_is_unread_like_create_role(sql):
    created = _facts("CREATE ROLE r")
    dropped = _facts(sql)

    assert created.opaque and created.objects == ()
    assert dropped.opaque and dropped.objects == ()
    assert dropped.operation == "DROP"


def test_no_recorded_statement_is_read_as_naming_nothing_without_saying_so():
    from tests.support.facts_corpus import family_file, read_rows

    silent = [
        row["sql"]
        for row in read_rows(family_file("snowflake"))
        if (facts := _facts(row["sql"])).operation
        in {"CREATE", "DROP", "ALTER", "INSERT", "UPDATE", "DELETE"}
        and not facts.opaque
        and not facts.objects
        and not facts.error
    ]

    assert silent == []


@pytest.mark.parametrize("sql", ["INSERT INTO {} VALUES (1)", "UPDATE {} SET a = 1"])
def test_a_mutation_whose_target_has_no_name_is_opaque(sql):
    facts = _facts(sql.format("IDENTIFIER($a || 'x')"))

    assert facts.opaque
    assert facts.target in (None,)
    assert facts.affected_objects == ()
