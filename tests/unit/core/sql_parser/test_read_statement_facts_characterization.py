"""Characterization of ``read_statement_facts`` branches the dialect suites leave unexercised.

Each case pins the exact facts the reader returns today, so a restructuring of the reader
that changes the order of its checks or the facts of one branch is caught.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts


def _table(name, role):
    return NamedObject(name, SqlObjectType.TABLE, role, name_quoted=False)


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [("postgres", "-- only a comment"), ("mysql", "/* only a comment */")],
)
def test_a_statement_that_blanks_to_nothing_has_unknown_facts(dialect, sql):
    assert read_statement_facts(sql, dialect=dialect) == StatementFacts("UNKNOWN", "UNKNOWN")


@pytest.mark.parametrize(
    "sql",
    ["UPDATE STATISTICS dbo.t", "UPDATE STATISTICS dbo.t s1 WITH FULLSCAN"],
)
def test_tsql_update_statistics_with_provable_names_is_ddl(sql):
    assert read_statement_facts(sql, dialect="tsql") == StatementFacts("UPDATE STATISTICS", "DDL")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE STATISTICS",  # no argument literal
        "UPDATE STATISTICS dbo.t (s1, s2)",  # arguments do not match
        "UPDATE STATISTICS select",  # table is not a name
        "UPDATE STATISTICS t 1abc",  # statistics name is not a name
    ],
)
def test_tsql_update_statistics_with_an_unread_tail_is_opaque(sql):
    assert read_statement_facts(sql, dialect="tsql") == StatementFacts(
        "UPDATE STATISTICS", "UNKNOWN", diagnostic="tsql UPDATE STATISTICS tail is opaque"
    )


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [("mysql", "SET NAMES utf8mb4"), ("postgres", "SET search_path = public")],
)
def test_a_session_setting_without_effects_has_no_events(dialect, sql):
    assert read_statement_facts(sql, dialect=dialect) == StatementFacts(
        "SET", "UNKNOWN", events=frozenset()
    )


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("mysql", "SET @a = 1"),
        ("postgres", "SET work_mem = '4MB'"),
        ("postgres", "SET client_encoding = utf8"),
    ],
)
def test_another_single_setting_has_no_facts_mapping(dialect, sql):
    assert read_statement_facts(sql, dialect=dialect) == StatementFacts(
        "SET", "UNKNOWN", diagnostic=f"{dialect} Set has no statement facts mapping"
    )


def test_postgres_comment_on_an_unnamed_kind_has_no_facts_mapping():
    assert read_statement_facts(
        "COMMENT ON FUNCTION f() IS 'x'", dialect="postgres"
    ) == StatementFacts(
        "COMMENT", "DDL", diagnostic="postgres Comment has no statement facts mapping"
    )


def test_oracle_comment_on_a_column_without_table_has_no_facts_mapping():
    assert read_statement_facts("COMMENT ON COLUMN c IS 'x'", dialect="oracle") == StatementFacts(
        "COMMENT", "UNKNOWN", diagnostic="oracle Comment has no statement facts mapping"
    )


@pytest.mark.parametrize("value", ["$1", "?"])
def test_duckdb_comment_on_table_with_an_unread_value(value):
    assert read_statement_facts(
        f"COMMENT ON TABLE t IS {value}", dialect="duckdb"
    ) == StatementFacts("COMMENT", "DDL", diagnostic="duckdb COMMENT ON TABLE value is not read")


def test_mysql_modifier_word_read_as_the_update_table():
    assert read_statement_facts("UPDATE low_priority SET a = 1", dialect="mysql") == (
        StatementFacts("UPDATE", "DML", diagnostic="mysql modifier word read where a table belongs")
    )


def test_postgres_select_into_a_subquery_is_a_query():
    assert read_statement_facts(
        "SELECT * INTO (SELECT 1) FROM u", dialect="postgres"
    ) == StatementFacts("SELECT", "QUERY", (_table("u", "referenced"),), events=frozenset())
