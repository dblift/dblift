r"""psql's ``\;`` combines the statements around it into one request (spec §4, row 16)."""

from __future__ import annotations

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser import Statement
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.db.plugins.postgresql.parser.postgresql_statement_parser import (
    PostgreSQLStatementParser,
)
from dblift.db.plugins.postgresql.parser.postgresql_tokenizer import PostgreSQLTokenizer


def _split(script: str) -> list[Statement]:
    tokens = PostgreSQLTokenizer(script).tokenize()
    return PostgreSQLStatementParser(tokens, ParserContext(), source=script).split()


def test_backslash_semicolon_combines_statements_and_marks_multi() -> None:
    records = _split(r"SELECT 1 \; SELECT 2; SELECT 3;")
    assert records[0].text == r"SELECT 1 ; SELECT 2"
    assert records[0].multi is True and records[0].terminator == ";"
    assert records[1] == Statement(text="SELECT 3", line=1, terminator=";")


def test_backslash_semicolon_inside_literals_is_not_a_combinator() -> None:
    records = _split(r"SELECT '\;'; SELECT $$\;$$;")
    assert [r.multi for r in records] == [False, False] and len(records) == 2


def test_split_statements_string_carries_the_substitution() -> None:
    assert SqlAnalyzer("postgresql").split_statements(r"SELECT 1 \; SELECT 2; SELECT 3;") == [
        r"SELECT 1 ; SELECT 2;",
        r"SELECT 3;",
    ]
