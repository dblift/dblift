"""A dollar-quote tag follows the rules of an unquoted identifier (spec §1)."""

from __future__ import annotations

import pytest

from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.postgresql.parser.postgresql_tokenizer import PostgreSQLTokenizer


def _types(script: str) -> list[tuple[str, str]]:
    return [
        (t.type.name, t.text)
        for t in PostgreSQLTokenizer(script).tokenize()
        if t.type != TokenType.EOF
    ]


def test_positional_parameter_is_a_symbol_not_a_string() -> None:
    assert ("SYMBOL", "$1") in _types("SELECT $1;")
    assert all(t != "STRING" for t, _ in _types("SELECT $1; SELECT $2;"))


def test_a_lone_dollar_is_a_symbol() -> None:
    assert ("SYMBOL", "$") in _types("SELECT 1 $ 2;")


def test_dollar_inside_an_identifier_stays_in_the_identifier() -> None:
    kinds = _types("SELECT a$b FROM t;")
    assert not any(t == "STRING" for t, _ in kinds)
    assert any(text == "a$b" for _, text in kinds)


@pytest.mark.parametrize(
    "script", ["SELECT $$x;y$$;", "SELECT $tag$x;y$tag$;", "SELECT $_t1$x$_t1$;"]
)
def test_valid_tags_are_strings(script: str) -> None:
    assert _types(script)[1][0] == "STRING"
