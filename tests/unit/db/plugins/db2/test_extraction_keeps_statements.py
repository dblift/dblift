"""Object extraction reads a chunk of text one statement at a time and must not refuse it.

``split_statements`` now follows the command line processor and refuses what it cannot run;
``split_for_extraction`` is the previous splitter, unchanged, for ``parse_sql`` and the extractors.
"""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.db.plugins.db2.parser.db2_regex_parser import DB2RegexParser

PARSER = DB2RegexParser()


@pytest.mark.parametrize(
    "script, error",
    [
        ("CREATE TABLE a (id INT); CREATE TABLE b (id INT);", UnsafeStatementSplitError),
        ("CONNECT TO sample;\nCREATE TABLE a (id INT);", UnsupportedMetaCommandError),
        ("QUIT;\nCREATE TABLE a (id INT);", UnsupportedMetaCommandError),
    ],
)
def test_the_execution_split_refuses_and_extraction_does_not(script: str, error: type) -> None:
    with pytest.raises(error):
        PARSER.split_statements(script)
    assert any("CREATE TABLE" in s for s in PARSER.split_for_extraction(script))


def test_parse_sql_still_reports_one_statement_per_semicolon() -> None:
    result = PARSER.parse_sql("CREATE TABLE a (id INT); CREATE TABLE b (id INT);")
    assert [o.name.lower() for s in result.statements for o in s.objects] == ["a", "b"]


def test_parse_sql_reads_a_script_the_execution_split_refuses() -> None:
    result = PARSER.parse_sql("CONNECT TO sample;\nCREATE TABLE a (id INT);")
    assert any(o.name.lower() == "a" for s in result.statements for o in s.objects)


def test_hybrid_parse_sql_reports_a_refusal_it_cannot_extract_around() -> None:
    """A script with no extractable object and a refused line is reported, not turned into a failed parse."""
    result = HybridParser("db2").parse_sql("CONNECT TO sample;\nINSERT INTO t VALUES (1);")
    assert result.success
    assert any("CONNECT" in error for error in result.errors)
