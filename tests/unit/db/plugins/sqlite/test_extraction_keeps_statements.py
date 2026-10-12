"""SQLite execution, extraction and analysis use the shell scanner."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

PARSER = SQLiteRegexParser()


def test_the_parser_is_authoritative_and_returns_statement_records() -> None:
    assert SQLiteRegexParser.SPLITS_WITHOUT_FALLBACK is True
    assert PARSER.split("SELECT 1; SELECT 2") == [
        Statement(text="SELECT 1", line=1, terminator=";"),
        Statement(text="SELECT 2", line=1, terminator=None),
    ]


def test_each_record_carries_the_line_its_statement_starts_on() -> None:
    assert [r.line for r in PARSER.split("SELECT 1;\n\nSELECT 2;\nSELECT 3")] == [1, 3, 4]


def test_split_statements_is_the_text_of_the_records() -> None:
    script = "CREATE TABLE t(a);\nINSERT INTO t VALUES(1);\n-- end\n"
    assert PARSER.split_statements(script) == [r.text for r in PARSER.split(script)]


@pytest.mark.parametrize(
    "script, error",
    [
        (".mode csv\nSELECT 1;", UnsupportedMetaCommandError),
        ("SELECT 1; /* open", UnsafeStatementSplitError),
        ("SELECT 6\n/\n2;", UnsafeStatementSplitError),
    ],
)
def test_execution_and_extraction_refuse_the_same_script(script: str, error: type) -> None:
    with pytest.raises(error):
        PARSER.split_statements(script)
    with pytest.raises(error):
        PARSER.split_for_extraction(script)


def test_extraction_projects_each_shell_statement() -> None:
    script = "CREATE TABLE a(x); CREATE TABLE b(y);\nBEGIN; INSERT INTO a VALUES(1); COMMIT;"
    assert PARSER.split_for_extraction(script) == [
        "CREATE TABLE a(x)",
        "CREATE TABLE b(y)",
        "BEGIN",
        "INSERT INTO a VALUES(1)",
        "COMMIT",
    ]


def test_parse_sql_still_reports_one_statement_per_semicolon() -> None:
    result = PARSER.parse_sql("CREATE TABLE a(x); CREATE TABLE b(y);")
    assert [o.name.lower() for s in result.statements for o in s.objects] == ["a", "b"]


def test_parse_sql_reports_a_shell_command_refusal() -> None:
    result = PARSER.parse_sql(".mode csv\nCREATE TABLE a(x);")
    assert not result.success
    assert result.statements == []
    assert any(".mode" in error for error in result.errors)


def test_analysis_keeps_a_segment_of_comments_only_and_execution_drops_it() -> None:
    script = "CREATE TABLE t(a);\n-- SQLite cannot add this constraint; rebuild the table\n"
    assert PARSER.split_statements(script) == ["CREATE TABLE t(a)"]
    assert PARSER.split_for_analysis(script) == [
        "CREATE TABLE t(a)",
        "-- SQLite cannot add this constraint; rebuild the table",
    ]
    assert SqlAnalyzer("sqlite").split_statements_for_analysis(script) == PARSER.split_for_analysis(
        script
    )


def test_analysis_is_the_execution_split_when_a_script_has_no_comment_only_segment() -> None:
    script = "-- c\nCREATE TABLE t(a); INSERT INTO t VALUES(1); /* d */ SELECT 1;"
    assert PARSER.split_for_analysis(script) == PARSER.split_statements(script)


def test_analysis_refuses_what_execution_refuses() -> None:
    with pytest.raises(UnsupportedMetaCommandError):
        PARSER.split_for_analysis("CREATE TABLE t(a);\n.print x\n")
