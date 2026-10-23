"""A token is allocated once per lexeme, so it carries no per-instance dictionary."""

import dataclasses

import pytest

from dblift.core.sql_parser.tokens import Token, TokenType


def test_token_has_slots_and_no_instance_dict():
    token = Token(TokenType.KEYWORD, "SELECT", 0, 1, 1)
    assert not hasattr(token, "__dict__")
    with pytest.raises(AttributeError):
        token.extra = 1  # type: ignore[attr-defined]


def test_token_stays_mutable_and_comparable():
    token = Token(TokenType.STRING, "'a", 0, 1, 1)
    token.text = "'a'"
    assert token == Token(TokenType.STRING, "'a'", 0, 1, 1)
    assert dataclasses.replace(token, type=TokenType.COMMENT).type is TokenType.COMMENT
