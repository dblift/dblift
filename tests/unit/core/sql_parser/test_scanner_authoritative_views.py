"""The dialect scanner governs execution and extraction of the same script."""

from __future__ import annotations

import subprocess
import sys

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.db2.parser.db2_regex_parser import DB2RegexParser
from dblift.db.plugins.db2.parser.parser_config import DB2Config
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser
from dblift.db.plugins.mariadb.regex_parser import MariaDbRegexParser
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig
from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser


@pytest.mark.parametrize("parser_class", [MySqlRegexParser, MariaDbRegexParser])
def test_mysql_custom_delimiter_unit_exposes_each_plain_statement(parser_class: type) -> None:
    script = "DELIMITER //\nSELECT 1; DROP TABLE users; SELECT 2//\nDELIMITER ;"
    parser = parser_class()

    assert parser.split_statements(script) == ["SELECT 1; DROP TABLE users; SELECT 2"]
    assert [
        statement.statement_type.value for statement in parser.parse_sql(script).statements
    ] == [
        "QUERY",
        "DDL",
        "QUERY",
    ]


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_mysql_analysis_sees_drop_inside_custom_delimiter_unit(dialect: str) -> None:
    script = "DELIMITER //\nSELECT 1; DROP TABLE users; SELECT 2//\nDELIMITER ;"

    analysis = analyse_script(script, dialect)

    assert [statement.operation for statement in analysis.statements] == [
        "SELECT",
        "DROP",
        "SELECT",
    ]
    assert any(caution.level == "destroys" for caution in analysis.cautions)
    assert SqlAnalyzer(dialect).split_statements_for_analysis(script) == [
        "SELECT 1",
        "DROP TABLE users",
        "SELECT 2",
    ]


def test_mysql_delimiter_command_suffix_has_bounded_cost() -> None:
    probe = (
        "from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser\n"
        "MySqlRegexParser().split_statements('DELIMITER ;;\\nSTATUS' + ';' * 45 + 'x')\n"
    )
    try:
        subprocess.run([sys.executable, "-c", probe], check=True, timeout=8)
    except subprocess.TimeoutExpired:
        pytest.fail("delimiter suffix scan exceeded the 8-second bound")


@pytest.mark.parametrize("delimiter", [";$", ";x"])
def test_mysql_command_suffix_prefers_the_full_active_delimiter(delimiter: str) -> None:
    parser = MySqlRegexParser()

    with pytest.raises(UnsupportedMetaCommandError):
        parser.split_statements(f"DELIMITER {delimiter}\nSTATUS{delimiter}\n")


def test_mysql_custom_delimiter_skips_comment_only_fragment() -> None:
    parser = MySqlRegexParser()
    script = "DELIMITER //\nSELECT 1; /* comment */; DROP TABLE users; SELECT 2//\nDELIMITER ;"

    assert [
        statement.statement_type.value for statement in parser.parse_sql(script).statements
    ] == [
        "QUERY",
        "DDL",
        "QUERY",
    ]


def test_mysql_executable_comment_wrapper_stays_whole_in_analysis() -> None:
    parser = MySqlRegexParser()
    script = (
        "DELIMITER //\n/*!50100 SELECT 1; DROP TABLE hidden */; "
        "DROP TABLE visible; SELECT 2//\nDELIMITER ;"
    )

    assert parser.split_for_extraction(script) == [
        "/*!50100 SELECT 1; DROP TABLE hidden */",
        "DROP TABLE visible",
        "SELECT 2",
    ]


def test_mysql_multiline_executable_comment_wrapper_stays_whole_in_analysis() -> None:
    parser = MySqlRegexParser()
    script = (
        "DELIMITER //\n/*!50100 SELECT 1;\nDROP TABLE hidden; SELECT 2 */; "
        "DROP TABLE visible//\nDELIMITER ;"
    )

    assert parser.split_for_extraction(script) == [
        "/*!50100 SELECT 1;\nDROP TABLE hidden; SELECT 2 */",
        "DROP TABLE visible",
    ]


def test_mysql_custom_delimiter_preserves_stored_program_body_for_analysis() -> None:
    parser = MySqlRegexParser()
    script = (
        "DELIMITER //\n"
        "CREATE PROCEDURE p() BEGIN SELECT 1; DROP TABLE users; END//\n"
        "DELIMITER ;"
    )

    assert parser.split_for_extraction(script) == [
        "CREATE PROCEDURE p() BEGIN SELECT 1; DROP TABLE users; END"
    ]


def test_db2_extraction_refuses_clp_statement_that_would_lose_sql() -> None:
    parser = DB2RegexParser()
    script = "SELECT 1; SELECT 2;"

    with pytest.raises(UnsafeStatementSplitError):
        parser.split_for_extraction(script)


def test_dialect_configs_do_not_keep_alternate_script_splitters() -> None:
    assert not hasattr(DB2Config, "split_statements")
    assert not hasattr(DB2Config, "extract_sqlpl_blocks")
    assert not hasattr(DB2Config, "extract_trigger_blocks")
    assert not hasattr(MySqlConfig, "extract_delimiter_blocks")


@pytest.mark.parametrize("parser_class", [MySqlRegexParser, MariaDbRegexParser])
def test_mysql_source_spans_keep_original_delimiters_and_bom_crlf(parser_class: type) -> None:
    script = "\ufeffDELIMITER //\r\n  SELECT 1; DROP TABLE t//\r\nDELIMITER ;\r\n"
    records = parser_class().split(script)

    assert [script[record.source_start : record.source_end] for record in records] == [
        "DELIMITER //\r\n",
        "SELECT 1; DROP TABLE t//",
        "DELIMITER ;\r\n",
    ]


def test_db2_source_spans_keep_directive_and_terminated_lines() -> None:
    script = "\ufeff--#SET TERMINATOR @\r\n  SELECT 1@\r\nSELECT 2@\r\n"
    records = DB2RegexParser().split(script)

    assert [script[record.source_start : record.source_end] for record in records] == [
        "--#SET TERMINATOR @\r\n",
        "SELECT 1@\r\n",
        "SELECT 2@\r\n",
    ]


@pytest.mark.parametrize("parser_class", [SQLiteRegexParser, DuckDBRegexParser])
def test_engine_source_spans_keep_original_semicolons_and_bom_crlf(parser_class: type) -> None:
    script = "\ufeff  SELECT 1;\r\nSELECT 2;"
    records = parser_class().split(script)

    assert [script[record.source_start : record.source_end] for record in records] == [
        "SELECT 1;",
        "SELECT 2;",
    ]


def test_sqlite_extraction_refuses_shell_command() -> None:
    parser = SQLiteRegexParser()

    with pytest.raises(UnsupportedMetaCommandError):
        parser.split_for_extraction(".read other.sql\nSELECT 1;")


def test_duckdb_extraction_refuses_shell_command() -> None:
    parser = DuckDBRegexParser()

    with pytest.raises(UnsupportedMetaCommandError):
        parser.split_for_extraction(".read other.sql\nSELECT 1;")


def test_duckdb_continued_escape_string_keeps_embedded_semicolon() -> None:
    parser = DuckDBRegexParser()
    script = "SELECT E'a'\n'b\\'c;d'; SELECT 2;"

    assert parser.split_statements(script) == ["SELECT E'a'\n'b\\'c;d'", "SELECT 2"]
    assert parser.split_for_extraction(script) == ["SELECT E'a'\n'b\\'c;d'", "SELECT 2"]


def test_duckdb_line_comment_preserves_escape_string_continuation() -> None:
    parser = DuckDBRegexParser()
    script = "SELECT E'a'\n-- hi\n'b\\'c;d'; SELECT 2;"

    statements = parser.split_statements(script)
    assert statements == ["SELECT E'a'\n-- hi\n'b\\'c;d'", "SELECT 2"]

    duckdb = pytest.importorskip("duckdb")
    assert [duckdb.sql(statement).fetchall() for statement in statements] == [
        [("ab'c;d",)],
        [(2,)],
    ]
