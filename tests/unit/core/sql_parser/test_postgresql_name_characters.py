"""A character the PostgreSQL family reads as part of a name never opens a lexeme.

docs/sql-parsing/postgresql.md section 2 and rows 30j to 30o: PostgreSQL, CockroachDB, YugabyteDB
and Redshift read every character above U+007F as a letter, so ``a<c>$x$`` is one name. U+001C is
an ASCII control character and is not part of a name.
"""

from __future__ import annotations

import warnings
from typing import Tuple

import pytest

from dblift.db.provider_registry import ProviderRegistry
from tests.support.splitter_spec.splitting import SplitOutcome, split_script
from tests.support.statement_list_parity import DIALECTS, PSQL_WIRE

#: no-break space, em space, ideographic space, next line, line separator, euro sign
NAME_CHARACTERS = ("\xa0", "\u2003", "\u3000", "\x85", "\u2028", "\u20ac")

#: Each lexeme opener written directly after a name that ends in the character.
AFTER_NAME = (
    "SELECT 1 AS a{c}$x$;\nSELECT 2 AS $x$;",
    "SELECT 1 AS a{c}$$;\nSELECT 2 AS $$;",
    "SELECT 1 AS a{c}E'\\';\nSELECT 2;",
    "SELECT 1 AS a{c}U&'\\';\nSELECT 2;",
    "SELECT 1 AS a{c}';\nSELECT 2 AS ';",
    'SELECT 1 AS a{c}";\nSELECT 2 AS ";',
    "SELECT 1 AS a{c}-- x\n, 2 AS b;\nSELECT 3;",
    "SELECT 1 AS a{c}/* ; */;\nSELECT 2;",
    "SELECT 1 AS {c}$x$;\nSELECT 2 AS $x$;",
    "SELECT 1 AS {c}E'\\';\nSELECT 2;",
    "CREATE TABLE t{c}$$ (x INT);\nSELECT 1;",
)


def _twin(dialect: str, script: str, char: str) -> Tuple[SplitOutcome, SplitOutcome]:
    """The outcome with ``char`` in the script, and the outcome with an underscore in its place."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        got = split_script(dialect, script.format(c=char))
        want = split_script(dialect, script.format(c="_"))
    kept = SplitOutcome(tuple(s.replace(char, "_") for s in got.statements), got.error)
    return kept, SplitOutcome(want.statements, want.error)


@pytest.mark.parametrize("dialect", PSQL_WIRE)
@pytest.mark.parametrize("char", NAME_CHARACTERS, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize("script", AFTER_NAME)
def test_the_character_continues_the_name_as_an_underscore_does(dialect, char, script):
    got, want = _twin(dialect, script, char)
    assert got == want


@pytest.mark.parametrize("dialect", PSQL_WIRE)
def test_a_dollar_quote_after_a_name_with_the_character_is_part_of_the_name(dialect):
    outcome = split_script(dialect, "SELECT 1 AS a\xa0$x$;\nSELECT 2 AS $x$;")
    assert outcome.error == "UnsafeStatementSplitError"
    assert "line 2" in (outcome.detail or "")


@pytest.mark.parametrize("dialect", PSQL_WIRE)
def test_a_control_character_is_not_part_of_a_name(dialect):
    script = "SELECT 1 AS a\x1c$x$;\nSELECT 2 AS $x$;"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        outcome = split_script(dialect, script)
    assert outcome.error is None
    assert len(outcome.statements) == 1


def test_only_the_engines_measured_to_read_them_as_name_characters_say_so():
    declared = {
        dialect
        for dialect in DIALECTS
        if (spec := ProviderRegistry.get_quirks(dialect).lexical_spec()) is not None
        and spec.non_ascii_names
    }
    assert declared == set(PSQL_WIRE)


@pytest.mark.parametrize("dialect", ("oracle", "mysql"))
def test_an_engine_not_measured_keeps_reading_the_character_as_it_did(dialect):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        outcome = split_script(dialect, "SELECT 1 AS a\xa0$x$ FROM dual;\nSELECT 2 FROM dual;")
    assert len(outcome.statements) == 2
