"""DB2 extraction follows the CLP scanner, including its refusals."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser import SqlParserFactory
from tests.support.facts_parser import facts_parser

PARSER = facts_parser("db2")


@pytest.mark.parametrize(
    "script, error",
    [
        ("CREATE TABLE a (id INT); CREATE TABLE b (id INT);", UnsafeStatementSplitError),
        ("CONNECT TO sample;\nCREATE TABLE a (id INT);", UnsupportedMetaCommandError),
        ("QUIT;\nCREATE TABLE a (id INT);", UnsupportedMetaCommandError),
    ],
)
def test_execution_and_extraction_refuse_the_same_script(script: str, error: type) -> None:
    with pytest.raises(error):
        PARSER.split_statements(script)
    with pytest.raises(error):
        PARSER.split_for_extraction(script)


def test_parse_sql_extracts_each_valid_clp_statement() -> None:
    result = PARSER.parse_sql("CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);")
    assert [o.name.lower() for s in result.statements for o in s.objects] == ["a", "b"]


def test_parse_sql_reports_a_client_command_refusal() -> None:
    result = PARSER.parse_sql("CONNECT TO sample;\nCREATE TABLE a (id INT);")
    assert not result.success
    assert result.statements == []
    assert any("CONNECT" in error for error in result.errors)


def test_hybrid_parse_sql_reports_a_refusal_without_extracted_statements() -> None:
    result = (
        SqlParserFactory("db2")
        .get_parser()
        .parse_sql("CONNECT TO sample;\nINSERT INTO t VALUES (1);")
    )
    assert not result.success
    assert result.statements == []
    assert any("CONNECT" in error for error in result.errors)
