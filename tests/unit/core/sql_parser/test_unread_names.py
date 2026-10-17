"""The shared rule that withholds object names an engine may read differently, and its sites."""

from __future__ import annotations

import logging

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.unread_names import names_unreadable, statement_sources
from dblift.db.dml_analysis import analyze_dml, statement_dml_table

NBSP, ZWSP, ZWJ, ACCENT = " ", "​", "‍", "́"
LEGACY = (
    "postgresql",
    "mysql",
    "mariadb",
    "sqlserver",
    "oracle",
    "db2",
    "snowflake",
    "redshift",
    "cockroachdb",
)


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
    assert names_unreadable("CREATE TABLE ét (id INT)", "postgres", ["t"])


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


@pytest.mark.parametrize(
    "dialect, sql",
    [
        ("mysql", "INSERT INTO t SELECT `té` FROM u"),
        ("tsql", "INSERT INTO t SELECT [té] FROM u"),
    ],
)
def test_a_quoted_identifier_is_not_a_name_cut_short(dialect, sql):
    assert not names_unreadable(sql, dialect, ["t"])


def test_the_analyzer_checks_the_names_it_extracted():
    assert SqlAnalyzer("postgresql").extract_objects(f"CREATE TABLE t{ZWJ}(id INT)") == []


def test_the_schema_part_of_a_name_is_checked_too():
    from dblift.core.sql_model.base import SqlObject, SqlObjectType
    from dblift.core.sql_parser.parser_factory import SqlParserFactory

    source = "CREATE TABLE sch\u00e9.t (id INT)"
    cut = SqlObject(name="t", schema="sch", object_type=SqlObjectType.TABLE)
    whole = SqlObject(name="t", schema="sch\u00e9", object_type=SqlObjectType.TABLE)
    for dialect in ("postgresql", "mysql"):
        parser = SqlParserFactory(dialect).get_parser()
        assert parser._names_unreadable(source, [cut])
        assert not parser._names_unreadable(source, [whole])
    sqlglot_parser = SqlParserFactory("snowflake").get_parser()
    assert sqlglot_parser._names_unreadable(source, [cut])
    assert not sqlglot_parser._names_unreadable(source, [whole])


@pytest.mark.parametrize("dialect", ("postgresql", "mysql", "snowflake"))
def test_a_statement_that_cannot_be_located_in_its_script_is_withheld(dialect):
    parser = SqlParserFactory(dialect).get_parser()
    assert parser._names_unreadable(None, [])
    scanner = SqlParserFactory("postgresql").get_parser().regex_parser
    script = "caf\u00e9; SELECT 1;"
    assert statement_sources(scanner, script, ["SELECT 2"]) == [None]
    assert statement_sources(scanner, script, ["SELECT 1"]) == ["SELECT 1;"]
    assert statement_sources(scanner, "SELECT 1", ["SELECT 2"]) == ["SELECT 2"]
    assert statement_sources(scanner, "-- SELECT 1\nSELECT 1\u00a0;", ["SELECT 1"]) == [
        "SELECT 1\u00a0;"
    ]


@pytest.mark.parametrize("dialect", LEGACY)
@pytest.mark.parametrize(
    "sql", ["CREATE SEQUENCE q{c};", "CREATE SEQUENCE q{c}", "DROP TABLE t{c};"]
)
def test_a_name_that_ends_its_statement_is_read_with_the_blank_the_split_trimmed(dialect, sql):
    script = sql.format(c=NBSP)
    assert SqlParserFactory(dialect).extract_objects(script) == []
    assert all(s.names_unread for s in SqlParserFactory(dialect).parse_sql(script).statements)


# The scanner's raw span for a name that ends the script: whether the script's last character is in it.
SPAN_SCANNERS = (
    "postgresql",
    "redshift",
    "cockroachdb",
    "mysql",
    "mariadb",
    "db2",
    "oracle",
    "sqlserver",
)


@pytest.mark.parametrize("dialect", SPAN_SCANNERS)
def test_the_scanner_span_of_a_name_that_ends_the_script_holds_the_blank_except_for_oracle(dialect):
    """Green pin: only Oracle's last record ends at its last token, which is why the extension stays."""
    script = f"DROP TABLE t{NBSP}"
    records = SqlParserFactory(dialect).get_parser().regex_parser.split(script)
    assert len(records) == 1
    span = script[records[0].source_start : records[0].source_end]
    assert span == ("DROP TABLE t" if dialect == "oracle" else script)


@pytest.mark.parametrize("dialect", SPAN_SCANNERS)
def test_statement_sources_returns_the_untrimmed_text_of_a_name_that_ends_the_script(dialect):
    """Green pin: the span is the whole script for every dialect, Oracle's through the extension."""
    script = f"DROP TABLE t{NBSP}"
    scanner = SqlParserFactory(dialect).get_parser().regex_parser
    statements = SqlAnalyzer(dialect).split_statements_for_analysis(script)
    assert statement_sources(scanner, script, statements) == [script]


@pytest.mark.parametrize(
    "dialect",
    [
        pytest.param(
            d,
            marks=pytest.mark.xfail(
                strict=True,
                reason="the record trims the blank, so the analysed text is shorter than its span",
            ),
        )
        for d in SPAN_SCANNERS
        if d != "oracle"
    ],
)
def test_the_analysed_text_equals_its_span_once_the_record_keeps_the_blank(dialect):
    script = f"DROP TABLE t{NBSP}"
    scanner = SqlParserFactory(dialect).get_parser().regex_parser
    statements = SqlAnalyzer(dialect).split_statements_for_analysis(script)
    assert statements == statement_sources(scanner, script, statements) == [script]
