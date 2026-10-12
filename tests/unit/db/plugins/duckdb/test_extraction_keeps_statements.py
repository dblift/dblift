"""Object extraction and script analysis read a script differently from execution.

``split_statements`` follows the engine and refuses what the ``duckdb`` shell would run itself;
``split_for_extraction`` is the previous splitter, unchanged, for ``parse_sql`` and the extractors;
``split_for_analysis`` is the execution split plus the segments of comments only.
"""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

PARSER = DuckDBRegexParser()


def test_the_parser_is_authoritative_and_returns_statement_records() -> None:
    assert DuckDBRegexParser.SPLITS_WITHOUT_FALLBACK is True
    assert PARSER.split("SELECT 1; SELECT 2") == [
        Statement(text="SELECT 1", line=1, terminator=";"),
        Statement(text="SELECT 2", line=1, terminator=None),
    ]


def test_split_statements_is_the_text_of_the_records() -> None:
    script = "CREATE TABLE t(a INT);\nINSERT INTO t VALUES (1);\n-- end\n"
    assert PARSER.split_statements(script) == [r.text for r in PARSER.split(script)]


def test_a_dollar_quoted_body_is_one_statement_in_every_seam() -> None:
    script = "CREATE MACRO m() AS $$a;b$$; SELECT m();"
    assert PARSER.split_statements(script) == ["CREATE MACRO m() AS $$a;b$$", "SELECT m()"]
    assert PARSER.split_for_analysis(script) == PARSER.split_statements(script)


@pytest.mark.parametrize(
    "script, error",
    [
        (".mode csv\nSELECT 1;", UnsupportedMetaCommandError),
        ("SELECT 1;\x00SELECT 2;", UnsafeStatementSplitError),
    ],
)
def test_the_execution_split_refuses_and_extraction_does_not(script: str, error: type) -> None:
    with pytest.raises(error):
        PARSER.split_statements(script)
    assert PARSER.split_for_extraction(script)


def test_split_for_extraction_is_the_previous_splitter() -> None:
    script = (
        "CREATE TABLE a(x INT); CREATE TABLE b(y INT);\nBEGIN; INSERT INTO a VALUES (1); COMMIT;"
    )
    assert PARSER.split_for_extraction(script) == [
        "CREATE TABLE a(x INT);",
        "CREATE TABLE b(y INT);",
        "BEGIN;",
        "INSERT INTO a VALUES (1);",
        "COMMIT;",
    ]


def test_parse_sql_still_reports_one_statement_per_semicolon() -> None:
    result = PARSER.parse_sql("CREATE TABLE a(x INT); CREATE TABLE b(y INT);")
    assert [o.name.lower() for s in result.statements for o in s.objects] == ["a", "b"]


def test_parse_sql_reads_a_script_the_execution_split_refuses() -> None:
    result = PARSER.parse_sql(".mode csv\nCREATE TABLE a(x INT);")
    assert any(o.name.lower() == "a" for s in result.statements for o in s.objects)


def test_analysis_keeps_a_segment_of_comments_only_and_execution_drops_it() -> None:
    script = "CREATE TABLE t(a INT);\n-- DuckDB cannot add this constraint; rebuild the table\n"
    assert PARSER.split_statements(script) == ["CREATE TABLE t(a INT)"]
    assert PARSER.split_for_analysis(script) == [
        "CREATE TABLE t(a INT)",
        "-- DuckDB cannot add this constraint; rebuild the table",
    ]
    assert SqlAnalyzer("duckdb").split_statements_for_analysis(script) == PARSER.split_for_analysis(
        script
    )


def test_analysis_is_the_execution_split_when_a_script_has_no_comment_only_segment() -> None:
    script = "-- c\nCREATE TABLE t(a INT); INSERT INTO t VALUES (1); /* d */ SELECT 1;"
    assert PARSER.split_for_analysis(script) == PARSER.split_statements(script)


def test_analysis_refuses_what_execution_refuses() -> None:
    with pytest.raises(UnsupportedMetaCommandError):
        PARSER.split_for_analysis("CREATE TABLE t(a INT);\n.mode csv\n")


def test_split_records_carry_the_line_of_each_statement() -> None:
    script = "SELECT 1;\nSELECT 2;\n/* a\nb */\nSELECT 3"
    assert PARSER.split(script) == [
        Statement(text="SELECT 1", line=1, terminator=";"),
        Statement(text="SELECT 2", line=2, terminator=";"),
        Statement(text="/* a\nb */\nSELECT 3", line=3, terminator=None),
    ]
