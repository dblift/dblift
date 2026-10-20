"""A dollar-quote tag follows the rules of an unquoted identifier (spec §1)."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from tests.support.splitter_spec.splitting import normalize, split_script
from tests.support.statement_list_parity import PSQL_WIRE


def _types(script: str) -> list[tuple[str, str]]:
    return [
        (t.type.name, t.text)
        for t in LexicalTokenizer(script, spec=POSTGRESQL_SPEC).tokenize()
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


@pytest.mark.parametrize("tag", ["\xa0", "a\xa0", "\u2003", "\u00b7", "\u0661"])
def test_non_ascii_tag_characters_are_strings(tag: str) -> None:
    literal = f"${tag}$x;y${tag}$"
    assert ("STRING", literal) in _types(f"SELECT {literal}; SELECT 2;")


def test_unclosed_non_ascii_tag_is_refused() -> None:
    with pytest.raises(UnsafeStatementSplitError, match="unterminated dollar-quoted string"):
        _types("SELECT $a\xa0$x;y; SELECT 2;")


@pytest.mark.parametrize("dialect", PSQL_WIRE)
@pytest.mark.parametrize("tag", ["a b", "a\x1c", "a-b", "a.b"])
def test_a_tag_holding_a_non_name_character_is_refused(dialect: str, tag: str) -> None:
    outcome = split_script(dialect, f"SELECT ${tag}$x;y${tag}$; SELECT 2;")
    assert outcome.error == "UnsafeStatementSplitError"
    assert "malformed dollar-quote tag" in (outcome.detail or "")


@pytest.mark.parametrize("dialect", PSQL_WIRE)
@pytest.mark.parametrize("tag", ["\x80", "\ufeff", "\U0001f600"])
def test_a_tag_holding_a_non_ascii_name_character_is_a_string(dialect: str, tag: str) -> None:
    outcome = split_script(dialect, f"SELECT ${tag}$x;y${tag}$; SELECT 2;")
    assert outcome.error is None
    assert normalize(outcome.statements) == (f"SELECT ${tag}$x;y${tag}$", "SELECT 2")
