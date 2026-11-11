"""Spacing rules of ``BaseStatementParser._needs_space_between`` not pinned elsewhere."""

import pytest

from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.tokens import Token, TokenType

pytestmark = [pytest.mark.unit]


def _space(prev: Token, cur: Token) -> bool:
    return BaseStatementParser([])._needs_space_between(prev, cur)


@pytest.mark.parametrize(("gap", "expected"), [(0, False), (1, True)])
def test_open_paren_after_a_string_keeps_the_authors_spacing(gap, expected):
    """A '(' after a token that is neither keyword nor identifier is not a call."""
    prev = Token(TokenType.STRING, "'a'", 0, 1, 1)
    cur = Token(TokenType.SYMBOL, "(", 3 + gap, 1, 4 + gap)

    assert _space(prev, cur) is expected


@pytest.mark.parametrize("prev_type", [TokenType.KEYWORD, TokenType.IDENTIFIER])
def test_word_before_a_non_word_token_gets_a_space(prev_type):
    """A keyword or identifier is followed by a space before a token no other rule covers."""
    prev = Token(prev_type, "END", 0, 1, 1)
    cur = Token(TokenType.DELIMITER, "GO", 3, 1, 4)

    assert _space(prev, cur) is True


def test_string_before_a_non_word_token_gets_no_space():
    prev = Token(TokenType.STRING, "'a'", 0, 1, 1)
    cur = Token(TokenType.DELIMITER, "GO", 4, 1, 5)

    assert _space(prev, cur) is False


@pytest.mark.parametrize(("gap", "expected"), [(0, False), (1, True)])
def test_symbol_after_an_identifier_keeps_the_authors_spacing(gap, expected):
    """The symbol rule applies when only the current token is a symbol."""
    prev = Token(TokenType.IDENTIFIER, "a", 0, 1, 1)
    cur = Token(TokenType.SYMBOL, "+", 1 + gap, 1, 2 + gap)

    assert _space(prev, cur) is expected
