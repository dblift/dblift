"""A refused script yields no statements or objects in the public parse."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import ParserError
from dblift.core.sql_parser import SqlParserFactory
from dblift.core.sql_parser.parser_factory import SqlParserFactory

#: (dialect, a refused script without objects, the refusal message, a refused script with a table)
CASES = [
    (
        "oracle",
        "@@setup.sql\nSELECT 1 FROM dual;\n",
        "Unsupported SQL*Plus directive '@@' at line 1; dblift does not run it",
        "@@setup.sql\nCREATE TABLE a (id NUMBER);\n",
    ),
    (
        "sqlserver",
        ":setvar schema dbo\nSELECT 1\nGO\n",
        "sqlcmd command ':setvar' on line 1: dblift does not run client commands",
        ":setvar schema dbo\nCREATE TABLE a (id INT)\nGO\n",
    ),
    (
        "mysql",
        "SELECT 1;\n/* open\n",
        "unterminated block comment opened at line 2, column 1",
        "CREATE TABLE a (id INT);\n/* open\n",
    ),
]
POSTGRESQL = (
    "SELECT 1;\n\\set x 1\nSELECT 2;\n",
    "Unsupported psql meta-command '\\\\set' at line 2; dblift does not run it",
    "\\connect other\nCREATE TABLE a (id INT);\n",
)


@pytest.mark.parametrize("dialect,script,message,with_table", CASES)
def test_parse_sql_reports_the_refusal_and_keeps_the_parse(
    dialect: str, script: str, message: str, with_table: str
) -> None:
    parser = SqlParserFactory(dialect, "hybrid").get_parser()
    with pytest.raises(ParserError):
        parser.split_statements(script)
    result = parser.parse_sql(script)
    assert not result.success
    assert any(message in error for error in result.errors)
    assert result.statements == []
    assert result.tables == []


@pytest.mark.parametrize("dialect,script,message,with_table", CASES)
def test_parse_sql_reports_the_refusal_of_a_script_that_declares_objects(
    dialect: str, script: str, message: str, with_table: str
) -> None:
    result = SqlParserFactory(dialect, "hybrid").get_parser().parse_sql(with_table)
    assert not result.success
    assert any(message in error for error in result.errors)
    assert result.statements == []
    assert result.tables == []


@pytest.mark.parametrize("dialect,script,message,with_table", CASES)
def test_extract_objects_refuses_a_script_the_scanner_refuses(
    dialect: str, script: str, message: str, with_table: str
) -> None:
    parser = SqlParserFactory(dialect, "hybrid").get_parser()
    with pytest.raises(ParserError):
        parser.extract_objects(script)
    with pytest.raises(ParserError):
        parser.extract_objects(with_table)


def test_postgresql_extraction_refuses_a_refused_script_and_parse_reports_it() -> None:
    script, message, with_table = POSTGRESQL
    parser = SqlParserFactory("postgresql", "hybrid").get_parser()
    with pytest.raises(ParserError):
        parser.split_statements(script)
    with pytest.raises(ParserError):
        parser.extract_objects(script)
    with pytest.raises(ParserError):
        parser.extract_objects(with_table)
    # the parse reports the refusal with the message and the line
    result = parser.parse_sql(script)
    assert not result.success
    assert any(message in error for error in result.errors)
