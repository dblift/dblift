"""The shared rule that withholds object names an engine may read differently, and its sites."""

from __future__ import annotations

import logging

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.unread_names import names_unreadable
from dblift.db.dml_analysis import analyze_dml, statement_dml_table

NBSP, ZWSP, ZWJ, ACCENT = " ", "​", "‍", "́"
LEGACY = ("postgresql", "mysql", "mariadb", "sqlserver", "oracle", "db2")


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.mark.parametrize("char", [NBSP, ZWSP, " ", "　", "﻿", "⁠", "\u0085"])
def test_one_of_the_22_characters_outside_quotes_makes_the_names_unreadable(char):
    assert names_unreadable(f"CREATE TABLE t{char}(id INT)", "postgres")


@pytest.mark.parametrize(
    "sql",
    [
        f"CREATE TABLE t (id INT) -- a{NBSP}b",
        f"CREATE TABLE t (id INT) /* a{NBSP}b */",
        f"INSERT INTO t VALUES ('a{NBSP}b')",
        f'CREATE TABLE "t{NBSP}" (id INT)',
        "CREATE TABLE t (id INT)",
    ],
)
def test_the_character_inside_a_string_quote_or_comment_is_not_in_a_name(sql):
    assert not names_unreadable(sql, "postgres")


def test_a_name_cut_short_by_a_non_ascii_character_is_unreadable():
    assert names_unreadable(f"CREATE TABLE t{ZWJ}(id INT)", "postgres", ["t"])
    assert names_unreadable(f"CREATE TABLE t{ACCENT} (id INT)", "postgres", ["t"])
    assert names_unreadable("CREATE TABLE té (id INT)", "postgres", ["t"])


def test_a_name_read_whole_is_kept():
    sql = "CREATE TABLE tété (id INT)"
    assert not names_unreadable(sql, "postgres", ["tété"])
    assert not names_unreadable(sql, "oracle", ["TÉTÉ"])
    assert not names_unreadable("INSERT INTO t VALUES ('té')", "postgres", ["t"])


def test_an_unknown_dialect_name_is_tolerated():
    assert names_unreadable(f"CREATE TABLE t{NBSP}(id INT)", "no-such-dialect")
    assert names_unreadable(f"CREATE TABLE t{NBSP}(id INT)", None)


@pytest.mark.parametrize("dialect", LEGACY)
def test_parse_sql_names_nothing_and_says_so(dialect):
    result = SqlParserFactory(dialect).parse_sql(f"CREATE TABLE t{NBSP}(id INT);")
    (statement,) = result.statements
    assert statement.objects == [] and statement.affected_objects == []
    assert statement.names_unread


@pytest.mark.parametrize("dialect", LEGACY)
def test_parse_sql_keeps_naming_a_readable_statement(dialect):
    def read(sql):
        (statement,) = SqlParserFactory(dialect).parse_sql(sql).statements
        return [(o.name, o.schema) for o in statement.objects + statement.affected_objects]

    assert read(f"CREATE TABLE t (id INT);\n-- a{NBSP}b") == read("CREATE TABLE t (id INT);")
    assert read(f"INSERT INTO t VALUES ('a{NBSP}b');") == read("INSERT INTO t VALUES ('ab');")


@pytest.mark.parametrize("dialect", LEGACY)
def test_extract_objects_names_nothing_for_an_unreadable_statement(dialect):
    assert SqlParserFactory(dialect).extract_objects(f"CREATE TABLE t{NBSP}(id INT)") == []
    assert SqlParserFactory(dialect).extract_objects("CREATE TABLE t(id INT)") != []


@pytest.mark.parametrize("dialect", LEGACY)
def test_the_analyzer_names_nothing_for_an_unreadable_statement(dialect):
    analyzer = SqlAnalyzer(dialect)
    assert analyzer.extract_objects(f"CREATE TABLE t{NBSP}(id INT)") == []
    assert analyzer.extract_objects("CREATE TABLE t (id INT)") != []


@pytest.mark.parametrize("dialect", ("postgres", "mysql", "tsql", "oracle"))
def test_dml_analysis_names_no_table_for_an_unreadable_statement(dialect):
    statement = f"DELETE FROM t{NBSP}WHERE a = 1"
    assert statement_dml_table(statement, dialect) == ""
    mutation = analyze_dml(statement, sqlglot_dialect=dialect)
    assert mutation.table == "" and mutation.events is None and mutation.updated_columns == []
    assert statement_dml_table("DELETE FROM t WHERE a = 1", dialect) == "t"
