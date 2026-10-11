"""A script the splitter refuses is reported, never raised, by parse_sql and extract_objects.

Both refusal classes (``UnsupportedMetaCommandError``, ``UnsafeStatementSplitError``) behave the
same on Oracle, SQL Server, MySQL and MariaDB (PostgreSQL's own parser reports it first): ``parse_sql`` keeps the parse and puts the refusal message in ``errors``;
``extract_objects`` reads the text as one statement (as it does for an already-split statement),
so it returns the objects found there, none when there are none. Execution still refuses.
"""

from __future__ import annotations

import pytest

from dblift.core.exceptions import ParserError
from dblift.core.sql_parser.hybrid_parser import HybridParser

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
        "unterminated block comment starting at line 2, column 1",
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
    parser = HybridParser(dialect)
    with pytest.raises(ParserError):
        parser.split_statements(script)
    result = parser.parse_sql(script)
    assert result.success
    assert result.errors == [message]


@pytest.mark.parametrize("dialect,script,message,with_table", CASES)
def test_extract_objects_reads_a_refused_script_as_one_statement(
    dialect: str, script: str, message: str, with_table: str
) -> None:
    parser = HybridParser(dialect)
    assert parser.extract_objects(script) == []
    assert [o.name.lower() for o in parser.extract_objects(with_table)] == ["a"]


def test_postgresql_extraction_reads_a_refused_script_and_its_parse_reports_the_refusal() -> None:
    script, message, with_table = POSTGRESQL
    parser = HybridParser("postgresql")
    with pytest.raises(ParserError):
        parser.split_statements(script)
    assert parser.extract_objects(script) == []
    assert [o.name.lower() for o in parser.extract_objects(with_table)] == ["a"]
    # the PostgreSQL regex parser fails its own parse first, with the message and the line
    result = parser.parse_sql(script)
    assert not result.success
    assert any(message in error for error in result.errors)
