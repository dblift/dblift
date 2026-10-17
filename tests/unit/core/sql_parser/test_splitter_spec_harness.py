"""The conformance harness has to be able to see a character at a statement edge."""

from __future__ import annotations

import pytest

from tests.support.splitter_spec.spec_tables import Expectation
from tests.support.splitter_spec.splitting import SplitOutcome, normalize

NBSP = chr(0xA0)
IDEOGRAPHIC_SPACE = chr(0x3000)


@pytest.mark.xfail(
    strict=True,
    reason="normalize() strips every Unicode space, so the harness cannot see the character",
)
def test_a_row_without_exact_text_distinguishes_a_trailing_no_break_space() -> None:
    expected = Expectation(statements=normalize((f"DROP TABLE t{NBSP}",)))
    assert not SplitOutcome(statements=("DROP TABLE t",)).matches(expected)


@pytest.mark.xfail(
    strict=True,
    reason="normalize() strips every Unicode space, so the harness cannot see the character",
)
@pytest.mark.parametrize("character", [NBSP, IDEOGRAPHIC_SPACE, chr(0x2028), chr(0x0B), chr(0x0C)])
def test_normalize_keeps_a_character_that_is_not_an_ascii_blank(character: str) -> None:
    assert normalize((f"{character}SELECT 1{character};",)) == (f"{character}SELECT 1{character}",)


def test_normalize_strips_the_ascii_blanks_and_one_terminator() -> None:
    assert normalize((" \t\r\nSELECT 1 ; \n",)) == ("SELECT 1",)


def test_an_exact_text_row_fails_when_the_splitter_differs_by_a_trailing_no_break_space() -> None:
    expected = Expectation(statements=(f"DROP TABLE t{NBSP}",), exact=True)
    assert not SplitOutcome(statements=("DROP TABLE t",)).matches(expected)
    assert SplitOutcome(statements=(f"DROP TABLE t{NBSP}",)).matches(expected)
