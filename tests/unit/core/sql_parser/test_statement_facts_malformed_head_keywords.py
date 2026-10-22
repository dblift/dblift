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
