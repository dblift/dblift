"""Statement records carry the verbatim text, its line, its terminator and its kind."""

from __future__ import annotations

from dblift.core.sql_parser import Statement
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.db.plugins.postgresql.parser.postgresql_statement_parser import (
    PostgreSQLStatementParser,
)
from dblift.db.plugins.postgresql.parser.postgresql_tokenizer import PostgreSQLTokenizer


def _parser(script: str) -> PostgreSQLStatementParser:
    tokens = PostgreSQLTokenizer(script).tokenize()
    return PostgreSQLStatementParser(tokens, ParserContext(), source=script)


def _split(script: str) -> list[Statement]:
    return _parser(script).split()


def test_terminator_is_recorded_and_excluded_from_text() -> None:
    records = _split("CREATE TABLE t(a int);\nINSERT INTO t VALUES (1)")
    assert records == [
        Statement(text="CREATE TABLE t(a int)", line=1, terminator=";"),
        Statement(text="INSERT INTO t VALUES (1)", line=2, terminator=None),
    ]


def test_leading_comment_is_not_part_of_the_statement_but_the_line_is_the_statement_s() -> None:
    records = _split("-- header\n/* more */\nSELECT 1;")
    assert records == [Statement(text="SELECT 1", line=3, terminator=";")]


def test_split_statements_keeps_the_semicolon_for_now() -> None:
    parser = _parser("SELECT 1; SELECT 2")
    assert parser.split_statements() == ["SELECT 1;", "SELECT 2"]
    assert [s.text for s in parser.split()] == ["SELECT 1", "SELECT 2"]


def test_safe_meta_command_is_a_directive_record_hidden_from_split_statements() -> None:
    parser = _parser("\\restrict abc\nSELECT 1;")
    assert [(s.kind, s.text) for s in parser.split()] == [
        ("directive", "\\restrict abc"),
        ("sql", "SELECT 1"),
    ]
    assert parser.split_statements() == ["SELECT 1;"]
