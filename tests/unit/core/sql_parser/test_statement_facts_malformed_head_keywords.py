"""A keyword or template brace in a name position is never published as an object name."""

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.db.plugins.db2.parser.statement_facts import Db2StatementFactsReader

DIALECTS = ["postgres", "mysql", "oracle", "tsql", "redshift", "sqlite", "duckdb"]

MALFORMED = [
    ("ALTER TABLE ADD COLUMN x int", "ALTER"),
    ("DROP TABLE IF", "DROP"),
    ("DROP TABLE CASCADE", "DROP"),
    ("DROP TABLE RESTRICT", "DROP"),
    ("DROP INDEX IF", "DROP"),
    ("CREATE TABLE IF", "CREATE"),
    ("CREATE TABLE CLONE x", "CREATE"),
    ("CREATE TABLE s{c}.t (a int)", "CREATE"),
    ("CREATE TABLE s{c} (a int)", "CREATE"),
    ("CREATE TABLE a{c}b (a int)", "CREATE"),
]

WELL_FORMED = [
    ("CREATE TABLE t (a int)", "t"),
    ("CREATE TABLE IF NOT EXISTS t (a int)", "t"),
    ("DROP TABLE IF EXISTS t", "t"),
    ("DROP TABLE t CASCADE", "t"),
    ("ALTER TABLE t ADD COLUMN x int", "t"),
]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "operation"), MALFORMED)
def test_a_keyword_or_brace_is_not_read_as_an_object_name(dialect, sql, operation):
    facts = read_statement_facts(sql, dialect=dialect)

    assert facts.operation == operation
    assert facts.objects == ()
    assert facts.target is None
    assert facts.diagnostic


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(("sql", "name"), WELL_FORMED)
def test_the_well_formed_form_still_names_its_object(dialect, sql, name):
    facts = read_statement_facts(sql, dialect=dialect)

    assert [o.name.lower() for o in facts.objects][:1] == [name]


DB2_MALFORMED = [
    "ALTER TABLE ADD COLUMN x int",
    "DROP TABLE CASCADE",
    "DROP TABLE ADD",
    "CREATE TABLE NOT",
    "CREATE TABLE EXISTS",
    "CREATE TABLE CLONE x",
    "CREATE TABLE s{c}.t (a int)",
]


@pytest.mark.parametrize("sql", DB2_MALFORMED)
def test_db2_does_not_read_a_keyword_as_an_object_name(sql):
    facts = Db2StatementFactsReader(None).read(sql)

    assert facts.objects == ()
    assert facts.target is None
    assert facts.diagnostic


# A program name that is not a reserved word of its engine stays readable when a parameter list or
# a trigger timing word follows it (reserved words per tests/support/facts_corpus/reserved).
PROGRAMS = [
    ("oracle", "CREATE OR REPLACE PROCEDURE restrict(a NUMBER) AS BEGIN NULL; END;", "RESTRICT"),
    (
        "oracle",
        "CREATE OR REPLACE FUNCTION cascade(a NUMBER) RETURN NUMBER AS BEGIN RETURN 1; END;",
        "CASCADE",
    ),
    ("oracle", "CREATE OR REPLACE PROCEDURE clone(a NUMBER) AS BEGIN NULL; END;", "CLONE"),
    (
        "oracle",
        "CREATE TRIGGER restrict BEFORE INSERT ON t FOR EACH ROW BEGIN NULL; END;",
        "RESTRICT",
    ),
    ("mysql", "CREATE PROCEDURE clone(a INT) BEGIN SELECT 1; END", "clone"),
    ("mysql", "CREATE FUNCTION only(a INT) RETURNS INT RETURN 1", "only"),
    ("mysql", "CREATE TRIGGER clone BEFORE INSERT ON t FOR EACH ROW SET NEW.a = 1", "clone"),
    ("postgres", "CREATE PROCEDURE clone(a int) BEGIN SELECT 1; END", "clone"),
    ("postgres", "CREATE FUNCTION restrict(a int) RETURNS int AS $$ SELECT 1 $$", "restrict"),
    ("redshift", "CREATE PROCEDURE cascade(a int) BEGIN SELECT 1; END", "cascade"),
]


@pytest.mark.parametrize(("dialect", "sql", "name"), PROGRAMS)
def test_a_program_named_with_a_non_reserved_clause_word_is_read(dialect, sql, name):
    facts = read_statement_facts(sql, dialect=dialect)

    assert [o.name for o in facts.objects][:1] == [name]


UNREAD_PROGRAMS = [
    ("oracle", "CREATE FUNCTION add(a NUMBER) RETURN NUMBER AS BEGIN RETURN 1; END;"),
    ("oracle", "CREATE PROCEDURE cascade"),
    ("mysql", "CREATE FUNCTION add(a INT) RETURNS INT RETURN 1"),
    ("mysql", "CREATE PROCEDURE restrict(a INT) BEGIN SELECT 1; END"),
    ("postgres", "CREATE FUNCTION only(a int) RETURNS int AS $$ SELECT 1 $$"),
    ("postgres", "CREATE FUNCTION IF"),
    ("oracle", "CREATE PROCEDURE clone"),
]


@pytest.mark.parametrize(("dialect", "sql"), UNREAD_PROGRAMS)
def test_a_reserved_word_or_a_bare_clause_word_is_not_a_program_name(dialect, sql):
    facts = read_statement_facts(sql, dialect=dialect)

    assert facts.objects == ()


DB2_PROGRAMS = [
    ("CREATE PROCEDURE clone(a INT) BEGIN END", "CLONE"),
    ("CREATE FUNCTION clone(a INT) RETURNS INT RETURN 1", "CLONE"),
    ("CREATE TRIGGER clone BEFORE INSERT ON t FOR EACH ROW BEGIN END", "CLONE"),
    ("CREATE INDEX clone ON t (a)", "CLONE"),
]


@pytest.mark.parametrize(("sql", "name"), DB2_PROGRAMS)
def test_db2_reads_a_program_named_clone(sql, name):
    facts = Db2StatementFactsReader(None).read(sql)

    assert [o.name for o in facts.objects][:1] == [name]


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE FUNCTION add(a INT) RETURNS INT RETURN 1",
        "CREATE PROCEDURE clone",
    ],
)
def test_db2_refuses_a_reserved_or_bare_clause_word_as_a_program_name(sql):
    assert Db2StatementFactsReader(None).read(sql).objects == ()
