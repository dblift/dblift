"""The statement dblift executes must be the statement the author wrote.

Statement splitting is tokenize-then-reserialize: the token stream is joined
back into text and *that* text is what reaches the driver. Any character the
tokenizer fails to claim, and any whitespace it invents or discards between
operator characters, therefore rewrites the executed SQL.

The failure mode is silent. ``SELECT a % b`` reserialized as ``SELECT a b`` is
still valid SQL (PostgreSQL reads it as ``a AS b``), so the migration succeeds
and writes the wrong data. There is no syntax error to catch.

Two invariants pin this down for any input, rather than one case per operator:

``test_no_character_is_lost``
    Ignoring whitespace and statement terminators, the concatenated output
    holds exactly the characters of the input. Catches deletions.

``test_splitting_is_a_fixpoint``
    Re-splitting the output reproduces it. Catches whitespace edits that change
    how the text lexes -- ``a - -b`` collapsed to ``a --b`` turns the rest of
    the line into a comment, which the character-level check cannot see.

The per-operator cases below are diagnostics: they name the operator that broke
when an invariant fails.
"""

from __future__ import annotations

import re
import warnings

import pytest

from tests.support.facts_parser import facts_parser

# Dialects whose splitting goes through a tokenizer. sqlite, duckdb and db2
# split by regex over the original text and never reserialize a token stream.

# Portable operator-bearing SQL: every statement below is valid in each dialect
# under test, or at least lexically ordinary there. The point is the character
# stream survives, not that the server would accept the semantics.
PORTABLE_CORPUS = [
    "SELECT id, a % b FROM t;",
    "SELECT id, a % b AS m FROM t;",
    "SELECT a & b FROM t;",
    "SELECT a ^ b FROM t;",
    "SELECT a - -b FROM t;",
    "SELECT a % -b FROM t;",
    "SELECT a || b FROM t;",
    "SELECT * FROM t WHERE name LIKE 'a%';",
    # "& " not "&d": an Oracle "&d" in a literal is a substitution variable (docs/sql-parsing/oracle.md section 6: substitution applies to the statement text).
    "SELECT * FROM t WHERE name LIKE '%a@b#c& d^e?f%';",
    "UPDATE t SET n = n % 7 WHERE id = 1;",
    "SELECT COUNT(*) % 3 FROM t;",
]

# PostgreSQL's jsonb / hstore / array operator family. Ordinary PostgreSQL, and
# every one of these operators is built from characters the base tokenizer used
# to drop.
POSTGRESQL_CORPUS = [
    """SELECT id FROM t WHERE j @> '{"a":1}';""",
    """SELECT id FROM t WHERE '{"a":1}' <@ j;""",
    "SELECT j #> '{a,b}' FROM t;",
    "SELECT j #>> '{a,b}' FROM t;",
    "SELECT id FROM t WHERE j ? 'k';",
    "SELECT id FROM t WHERE j ?| array['a','b'];",
    "SELECT id FROM t WHERE j ?& array['a','b'];",
    "SELECT id FROM t WHERE tags && ARRAY[1,2];",
    "SELECT j - 'k' FROM t;",
    "SELECT id FROM t WHERE c ~ '^x' AND d !~ 'y';",
    "SELECT id FROM t WHERE c ~* '^x';",
    "SELECT 2 ^ 10 AS p, 5 % 2 AS m, 6 & 3 AS b, 6 # 3 AS x;",
    "CREATE TABLE res AS SELECT id, a % b AS m FROM t;",
]

TERMINATOR_RE = re.compile(r"[;\s]+")


def _canonical(sql: str) -> str:
    """Character content of ``sql``, ignoring whitespace and terminators.

    Splitting legitimately normalises whitespace and statement terminators
    (MySQL drops the trailing ``;``); it must not touch anything else.
    """
    return TERMINATOR_RE.sub("", sql)


def _split(parser, sql: str) -> list[str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return parser.split_statements(sql)


def _cases(corpus: list[str], dialects: list[str]) -> list[tuple[str, str]]:
    return [(dialect, sql) for dialect in dialects for sql in corpus]


@pytest.mark.unit
def test_postgresql_two_character_operators_are_not_split_apart() -> None:
    """``@>`` must reach the driver as ``@>``, not ``@ >``.

    Character preservation alone is not enough: a space inserted between the
    two characters turns containment into a prefix operator applied to a
    comparison, which is a different expression.
    """
    parser = facts_parser("postgresql")
    for operator in ("@>", "<@", "#>", "#>>", "?|", "?&", "&&", "||", "!~", "~*"):
        sql = f"SELECT id FROM t WHERE a {operator} b;"
        out = "".join(_split(parser, sql))
        assert operator in out, f"{operator} was split apart: {out!r}"


@pytest.mark.unit
def test_author_separated_operators_are_not_merged() -> None:
    """``a - -b`` must not collapse into ``a --b``, which is a comment."""
    parser = facts_parser("postgresql")
    out = "".join(_split(parser, "SELECT a - -b FROM t;"))
    assert "--" not in out, f"unary minus merged into a comment marker: {out!r}"


@pytest.mark.unit
def test_unclaimed_character_is_preserved_not_deleted() -> None:
    """A character no dialect rule claims is passed through verbatim.

    This is the class-level guarantee. Widening the symbol set fixes the
    operators we know about; passing unclaimed characters through means the
    next gap surfaces as a database error or as working SQL, never as a
    statement that succeeds having quietly lost a character.
    """
    from dblift.core.sql_parser.base_tokenizer import BaseTokenizer, TokenizerWarning

    sql = "SELECT a \\ b;"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", TokenizerWarning)
        tokens = BaseTokenizer(sql).tokenize()

    assert any(t.text == "\\" for t in tokens), f"backslash dropped: {tokens!r}"
    assert any(
        issubclass(w.category, TokenizerWarning) for w in caught
    ), "unclaimed character must still be reported, not silently accepted"


@pytest.mark.unit
def test_strict_mode_still_rejects_unclaimed_characters() -> None:
    """``strict_unknown_chars`` remains an error in strict-tokenizer mode."""
    from dblift.core.sql_parser.base_tokenizer import BaseTokenizer, TokenizerError

    with pytest.raises(TokenizerError):
        BaseTokenizer("SELECT a \\ b;", strict_unknown_chars=True).tokenize()


# Only these three dialect parsers wire ``strict_tokenizer`` through to the
# tokenizer's ``strict_unknown_chars`` (and re-raise on failure); Oracle's
# `split_statements` ignores the flag and always falls back to regex.
STRICT_MODE_OPERATOR_CASES = [
    ("postgresql", "UPDATE t SET n = n % 7 WHERE id = 1;"),
    ("postgresql", """SELECT id FROM t WHERE j @> '{"a":1}';"""),
    ("postgresql", "SELECT a & b FROM t;"),
    ("postgresql", "SELECT a ^ b FROM t;"),
    ("mysql", "UPDATE t SET n = n % 7 WHERE id = 1;"),
    ("mysql", "SELECT a & b FROM t;"),
    ("mysql", "SELECT a ^ b FROM t;"),
    ("sqlserver", "UPDATE t SET n = n % 7 WHERE id = 1;"),
    ("sqlserver", "SELECT a & b FROM t;"),
    ("sqlserver", "SELECT a ^ b FROM t;"),
]
