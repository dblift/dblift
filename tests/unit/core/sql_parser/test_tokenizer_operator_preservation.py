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

from db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser
from db.plugins.oracle.parser.oracle_parser import OracleParser
from db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser
from db.plugins.sqlserver.parser.sqlserver_regex_parser import SqlServerRegexParser

# Dialects whose splitting goes through a tokenizer. sqlite, duckdb and db2
# split by regex over the original text and never reserialize a token stream.
TOKENIZING_PARSERS = {
    "postgresql": PostgreSqlRegexParser,
    "mysql": MySqlRegexParser,
    "sqlserver": SqlServerRegexParser,
    "oracle": OracleParser,
}

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
    "SELECT * FROM t WHERE name LIKE '%a@b#c&d^e?f%';",
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


ALL_CASES = _cases(PORTABLE_CORPUS, sorted(TOKENIZING_PARSERS)) + _cases(
    POSTGRESQL_CORPUS, ["postgresql"]
)


@pytest.mark.unit
@pytest.mark.parametrize("dialect,sql", ALL_CASES)
def test_no_character_is_lost(dialect: str, sql: str) -> None:
    """Every non-whitespace character of the input reaches the executed SQL."""
    parser = TOKENIZING_PARSERS[dialect]()
    out = "".join(_split(parser, sql))
    assert _canonical(out) == _canonical(sql), (
        f"{dialect}: statement splitting changed the SQL\n"
        f"  input : {sql!r}\n"
        f"  output: {out!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("dialect,sql", ALL_CASES)
def test_splitting_is_a_fixpoint(dialect: str, sql: str) -> None:
    """Feeding the output back in reproduces it.

    A statement that lexes differently the second time around lexes differently
    from what the author wrote -- e.g. ``a - -b`` rendered as ``a --b``, where
    the remainder of the line has become a comment.
    """
    parser = TOKENIZING_PARSERS[dialect]()
    once = _split(parser, sql)
    twice = _split(parser, "".join(once))
    assert twice == once, (
        f"{dialect}: reserialized SQL does not lex back to itself\n"
        f"  input : {sql!r}\n"
        f"  once  : {once!r}\n"
        f"  twice : {twice!r}"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "char", ["%", "&", "#", "?", "^", "@", "+", "-", "*", "/", "<", ">", "=", "!", "|", "~"]
)
@pytest.mark.parametrize("dialect", sorted(TOKENIZING_PARSERS))
def test_operator_character_survives(dialect: str, char: str) -> None:
    """Diagnostic: name the operator character that got dropped."""
    if dialect == "mysql" and char == "#":
        pytest.skip("# opens a comment in MySQL; consuming the rest of the line is correct")
    parser = TOKENIZING_PARSERS[dialect]()
    sql = f"SELECT a {char} b FROM t;"
    out = "".join(_split(parser, sql))
    assert char in out, f"{dialect}: {char!r} deleted from {sql!r}, got {out!r}"


@pytest.mark.unit
@pytest.mark.parametrize("dialect", sorted(TOKENIZING_PARSERS))
def test_percent_inside_string_literal_is_untouched(dialect: str) -> None:
    """LIKE patterns are string content, not operators, and already worked."""
    parser = TOKENIZING_PARSERS[dialect]()
    sql = "SELECT * FROM t WHERE name LIKE 'a%b%';"
    out = "".join(_split(parser, sql))
    assert "'a%b%'" in out, f"{dialect}: literal mangled, got {out!r}"


@pytest.mark.unit
@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "oracle"])
def test_concatenation_and_regex_operators_stay_intact(dialect: str) -> None:
    """``||`` and ``~`` were already claimed; they must not regress."""
    parser = TOKENIZING_PARSERS[dialect]()
    out = "".join(_split(parser, "SELECT a || b FROM t;"))
    assert "||" in out, f"{dialect}: || broken, got {out!r}"


@pytest.mark.unit
def test_postgresql_two_character_operators_are_not_split_apart() -> None:
    """``@>`` must reach the driver as ``@>``, not ``@ >``.

    Character preservation alone is not enough: a space inserted between the
    two characters turns containment into a prefix operator applied to a
    comparison, which is a different expression.
    """
    parser = PostgreSqlRegexParser()
    for operator in ("@>", "<@", "#>", "#>>", "?|", "?&", "&&", "||", "!~", "~*"):
        sql = f"SELECT id FROM t WHERE a {operator} b;"
        out = "".join(_split(parser, sql))
        assert operator in out, f"{operator} was split apart: {out!r}"


@pytest.mark.unit
def test_author_separated_operators_are_not_merged() -> None:
    """``a - -b`` must not collapse into ``a --b``, which is a comment."""
    parser = PostgreSqlRegexParser()
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
    from core.sql_parser.base_tokenizer import BaseTokenizer, TokenizerWarning

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
    """``strict_unknown_chars`` remains an error, for the validator's use."""
    from core.sql_parser.base_tokenizer import BaseTokenizer, TokenizerError

    with pytest.raises(TokenizerError):
        BaseTokenizer("SELECT a \\ b;", strict_unknown_chars=True).tokenize()


# core/sql_validator._sql_syntax_validator.validate_sql_syntax calls
# ``sql_analyzer.split_statements(script_content, strict_tokenizer=True)`` --
# the path behind `dblift validate-sql` / `migrate --strict`. Only these three
# dialect parsers actually wire ``strict_tokenizer`` through to the
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


@pytest.mark.unit
@pytest.mark.parametrize("dialect,sql", STRICT_MODE_OPERATOR_CASES)
def test_strict_tokenizer_accepts_widened_operator_characters(dialect: str, sql: str) -> None:
    """``validate-sql`` / ``migrate --strict`` must not choke on ordinary operator SQL.

    ``strict_tokenizer=True`` sets the dialect tokenizer's
    ``strict_unknown_chars=True``, where ``_handle_unknown_char`` raises
    ``TokenizerError`` instead of warning. If ``SYMBOL_CHARS`` ever lost the
    operator characters SQL engines build ``%``, ``&``, ``^`` and the jsonb
    family (``@>``) from, ``_is_symbol`` would stop claiming them and strict
    mode would start raising on ordinary SQL that uses them as operators --
    exactly the statements in this corpus, and exactly the path
    ``core/sql_validator`` uses to certify a migration script.
    """
    from core.sql_parser.base_tokenizer import TokenizerWarning

    parser = TOKENIZING_PARSERS[dialect]()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        statements = parser.split_statements(sql, strict_tokenizer=True)

    assert statements, f"{dialect}: strict-tokenizer split produced no statements for {sql!r}"
    assert not any(
        issubclass(w.category, TokenizerWarning) for w in caught
    ), f"{dialect}: strict-tokenizer split warned about an unclaimed character for {sql!r}"
