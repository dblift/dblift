"""The DuckDB script cut: where a statement ends, what the shell would run itself, what is refused.

Every expectation was measured with the Python driver and ``duckdb.extract_statements``
(docs/sql-parsing/duckdb.md); the rows of its section 10 are pinned separately by the conformance
test, these tests state the rules behind them and the records the engine returns.
"""

from __future__ import annotations

import random

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import DuckDBFactsParser
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC


def records(script: str) -> list[Statement]:
    """The records the shared engine cuts ``script`` into."""
    return DuckDBFactsParser().split(script)


def texts(script: str) -> list[str]:
    return [unit.text for unit in records(script)]


# ---- the engine's own cut --------------------------------------------------------------------

_LEXEMES = [
    "1",
    "'a;b'",
    "'it''s;'",
    "'--;'",
    "'/*;'",
    "'$$;'",
    "'a\\'",
    "E'a\\'b;c'",
    "e'x;y'",
    "E'it''s;'",
    "E'a\\\\'",
    "$$ ; $$",
    "$$a\n;\nb$$",
    "$t$ ; $$ $t$",
    "$X$ ; $x$ $X$",
    "$a1$ ; $a1$",
    "$\xe9$ ; $\xe9$",
    "$ab$ $a$ ; $ab$",
    "'a'\n'b;'",
    "['a;b'][1]",
    "{'a': ';'}",
]
_ALIASES = ["", " AS x", ' AS "a;b"', ' AS "a--b"', ' AS "c/*d"', ' AS "it\'s;"']
#: The 18 non-ASCII code points the engine reads as blanks (measured over U+0001 to U+10FFFF).
UNICODE_BLANKS = (
    "\u00a0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u200b"
    "\u202f\u205f\u2060\u3000\ufeff"
)
_JOINS = [" ", "\n", "\u00a0", "\u2003", "\u200b", "\u3000", "\ufeff"]
_GAPS = [
    "",
    " ",
    "\u00a0",
    "\u2003",
    "\ufeff",
    "\n",
    " -- c;\n",
    " /* c; /* n; */ ; */ ",
    " /* c */ ",
    "\r\n",
    "\t",
]


def _statement(rng: random.Random) -> str:
    parts = [rng.choice(_LEXEMES) for _ in range(rng.randint(1, 3))]
    return "SELECT" + rng.choice(_JOINS) + " || ".join(parts) + rng.choice(_ALIASES)


def _fold(text: str) -> str:
    """The engine's text keeps its leading blanks and its last statement its terminators, and shows
    a byte order mark as a space: compare with every blank folded to one."""
    return "".join(" " if char in UNICODE_BLANKS else char for char in text).strip(" \t\r\n;")


def test_the_scanner_cuts_where_the_engine_cuts() -> None:
    """The engine's own splitter is the oracle (2 000 derandomised scripts of valid SELECTs)."""
    duckdb = pytest.importorskip("duckdb")
    rng = random.Random(11)
    evaluated = 0
    for _ in range(2000):
        statements = [_statement(rng) for _ in range(rng.randint(1, 5))]
        script = ""
        for index, statement in enumerate(statements):
            script += statement
            if index < len(statements) - 1 or rng.random() < 0.7:
                script += rng.choice([";", ";;", " ;"])
            if index < len(statements) - 1:
                script += rng.choice(_GAPS)

        try:
            oracle = [_fold(s.query) for s in duckdb.extract_statements(script)]
        except duckdb.Error:
            continue  # the engine rejects the text: no cut to compare
        evaluated += 1
        ours = [_fold(text) for text in texts(script)]
        assert ours == [text for text in oracle if text], script
    assert (
        evaluated > 1500
    )  # measured: 1701; the rest holds a unicode blank the engine rejects, evaluated


# ---- strings, identifiers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 'a;b'; SELECT 2", ["SELECT 'a;b'", "SELECT 2"]),
        ("SELECT 'it''s;'; SELECT 2", ["SELECT 'it''s;'", "SELECT 2"]),
        ("SELECT 'a\\'; SELECT 2", ["SELECT 'a\\'", "SELECT 2"]),
        ('SELECT "a;b"; SELECT 2', ['SELECT "a;b"', "SELECT 2"]),
        ('SELECT "a""b;c"; SELECT 2', ['SELECT "a""b;c"', "SELECT 2"]),
        ('SELECT "it\'s;"; SELECT 2', ['SELECT "it\'s;"', "SELECT 2"]),
        ("SELECT 'a;\nb'; SELECT 2", ["SELECT 'a;\nb'", "SELECT 2"]),
        ("SELECT [a; SELECT 2", ["SELECT [a", "SELECT 2"]),
        ("SELECT `a; SELECT 2", ["SELECT `a", "SELECT 2"]),
        ("SELECT x'3B3B'; SELECT 2", ["SELECT x'3B3B'", "SELECT 2"]),
    ],
)
def test_a_semicolon_inside_a_lexeme_ends_nothing(script: str, expected: list[str]) -> None:
    assert texts(script) == expected


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 'abc;", ["SELECT 'abc;"]),
        ('SELECT "abc;', ['SELECT "abc;']),
        ("SELECT $$abc;", ["SELECT $$abc;"]),
        ("SELECT $t$abc; $$", ["SELECT $t$abc; $$"]),
        ("SELECT E'abc\\';", ["SELECT E'abc\\';"]),
        ("SELECT 1; SELECT 'abc;\nSELECT 2;", ["SELECT 1", "SELECT 'abc;\nSELECT 2;"]),
    ],
)
def test_an_unterminated_lexeme_is_the_last_statement(script: str, expected: list[str]) -> None:
    assert texts(script) == expected


# ---- escape strings -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "literal",
    ["E'a\\'b;c'", "e'a\\'b;c'", "E'a''b;c'", "E'a\\\\'", "E'a''\\'b;c'", "E'\\\\\\'b;c'"],
)
def test_an_escape_string_reads_the_backslash(literal: str) -> None:
    assert texts(f"SELECT {literal}; SELECT 2") == [f"SELECT {literal}", "SELECT 2"]


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT xE'a\\'; SELECT 2", ["SELECT xE'a\\'", "SELECT 2"]),
        ("SELECT a$E'a\\'; SELECT 2", ["SELECT a$E'a\\'", "SELECT 2"]),
        ("SELECT E 'a\\'; SELECT 2", ["SELECT E 'a\\'", "SELECT 2"]),
        ("SELECT (1)E'a\\'b;c'; SELECT 2", ["SELECT (1)E'a\\'b;c'", "SELECT 2"]),
        ("SELECT 1E'a\\'b;c'; SELECT 2", ["SELECT 1E'a\\'b;c'", "SELECT 2"]),
        ("SELECT 'x'E'a\\'b;c'; SELECT 2", ["SELECT 'x'E'a\\'b;c'", "SELECT 2"]),
        ("SELECT $$x$$e'a\\'b;c'; SELECT 2", ["SELECT $$x$$e'a\\'b;c'", "SELECT 2"]),
    ],
)
def test_an_e_opens_an_escape_string_unless_it_ends_a_word(
    script: str, expected: list[str]
) -> None:
    assert texts(script) == expected


# ---- dollar quotes and parameters ---------------------------------------------------------------


@pytest.mark.parametrize(
    "literal",
    [
        "$$a;b$$",
        "$$a;'b$$",
        '$$a;"b$$',
        "$$a -- ; /* b$$",
        "$x$ a $$ ; $x$",
        "$X$ a $x$ ; $X$",
        "$a1$ ; $a1$",
        "$_t$ ; $_t$",
        "$\xe9$ ; $\xe9$",
        "$a$ x $b$ ; $b$ y ; $a$",
        "$ab$ $a$ ; $ab$",
        "$a$ $ab$ ; $a$",
        "$a$ x$ $a$",
        "$a$ $1 $a$",
        "$a$x$a$",
        "$$a\n;\nb$$",
        "$$$$",
    ],
)
def test_a_dollar_quoted_string_closes_only_on_its_own_tag(literal: str) -> None:
    assert texts(f"SELECT {literal}; SELECT 2") == [f"SELECT {literal}", "SELECT 2"]


@pytest.mark.parametrize(
    "script, expected",
    [
        ("PREPARE p AS SELECT $1; EXECUTE p(5)", ["PREPARE p AS SELECT $1", "EXECUTE p(5)"]),
        ("PREPARE p AS SELECT $a; SELECT 2", ["PREPARE p AS SELECT $a", "SELECT 2"]),
        ("SELECT $1a$ ; $1a$; SELECT 2", ["SELECT $1a$", "$1a$", "SELECT 2"]),
        ("SELECT $a b$ ; $a b$; SELECT 2", ["SELECT $a b$", "$a b$", "SELECT 2"]),
        ("SELECT $; SELECT 2", ["SELECT $", "SELECT 2"]),
        (
            "SELECT 1 AS a$$; SELECT 'x$$'; SELECT 2",
            ["SELECT 1 AS a$$", "SELECT 'x$$'", "SELECT 2"],
        ),
        ("SELECT$$a;b$$; SELECT 2", ["SELECT$$a", "b$$", "SELECT 2"]),
        ("SELECT 1$$a;b$$; SELECT 2", ["SELECT 1$$a;b$$", "SELECT 2"]),
        ("SELECT ($$a;b$$); SELECT 2", ["SELECT ($$a;b$$)", "SELECT 2"]),
        ("SELECT 1,$$a;b$$; SELECT 2", ["SELECT 1,$$a;b$$", "SELECT 2"]),
        ('CREATE TABLE "$$"(a INT); SELECT 2', ['CREATE TABLE "$$"(a INT)', "SELECT 2"]),
        ("SELECT E'$$'; SELECT 2", ["SELECT E'$$'", "SELECT 2"]),
        ("SELECT '$x$ ;'; SELECT 2", ["SELECT '$x$ ;'", "SELECT 2"]),
        ("SELECT 1 -- $$\n; SELECT 2", ["SELECT 1 -- $$", "SELECT 2"]),
    ],
)
def test_a_dollar_that_opens_nothing_is_not_a_quote(script: str, expected: list[str]) -> None:
    assert texts(script) == expected


def test_a_statement_that_is_only_a_lexeme_is_code_not_a_comment() -> None:
    assert texts("'a'; \"b\"; $$c$$; $1; 1;") == ["'a'", '"b"', "$$c$$", "$1", "1"]


@pytest.mark.parametrize("blank", list(UNICODE_BLANKS), ids=lambda c: f"U+{ord(c):04X}")
def test_a_unicode_blank_is_a_blank_before_a_lexeme(blank: str) -> None:
    assert texts(f"SELECT{blank}$$a;b$$; SELECT 2") == [f"SELECT{blank}$$a;b$$", "SELECT 2"]
    assert texts(f"SELECT{blank}E'a\\'b;c'; SELECT 2") == [f"SELECT{blank}E'a\\'b;c'", "SELECT 2"]
    assert texts(f"SELECT{blank}$t$ ; $t${blank}AS x; SELECT 2") == [
        f"SELECT{blank}$t$ ; $t$" f"{blank}AS x",
        "SELECT 2",
    ]


@pytest.mark.parametrize("blank", list(UNICODE_BLANKS), ids=lambda c: f"U+{ord(c):04X}")
def test_a_segment_of_unicode_blanks_only_is_not_a_statement(blank: str) -> None:
    assert texts(f"SELECT 1;{blank}; SELECT 2") == ["SELECT 1", "SELECT 2"]


@pytest.mark.parametrize("letter", ["\u00e9", "\u200c", "\u00ad"])
def test_a_non_blank_non_ascii_character_belongs_to_the_word(letter: str) -> None:
    assert texts(f"SELECT{letter}$$a;b$$; SELECT 2") == [f"SELECT{letter}$$a", "b$$", "SELECT 2"]


# ---- comments ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script, expected",
    [
        ("/* a /* b */ ; */ SELECT 1; SELECT 2", ["/* a /* b */ ; */ SELECT 1", "SELECT 2"]),
        ("/* a /* b */ SELECT 1; */ SELECT 2;", ["/* a /* b */ SELECT 1; */ SELECT 2"]),
        ("/* a /* b /* c */ ; */ ; */ SELECT 1;", ["/* a /* b /* c */ ; */ ; */ SELECT 1"]),
        ("SELECT 1; */ SELECT 2;", ["SELECT 1", "*/ SELECT 2"]),
        ("SELECT 1 /*/ ; */ ; SELECT 2", ["SELECT 1 /*/ ; */", "SELECT 2"]),
    ],
)
def test_block_comments_nest(script: str, expected: list[str]) -> None:
    assert texts(script) == expected


@pytest.mark.parametrize(
    "script",
    ["SELECT 1; /* open", "/* open\nSELECT 1;", "SELECT 1 /* a /* b */ ; "],
)
def test_an_unterminated_block_comment_is_refused(script: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="unterminated block comment"):
        texts(script)


def test_a_cr_ends_a_line_comment_as_a_lf_does() -> None:
    assert texts("SELECT 1; -- c\rSELECT 2;\nSELECT 3;") == [
        "SELECT 1",
        "-- c\rSELECT 2",
        "SELECT 3",
    ]


def test_a_semicolon_inside_a_line_comment_ends_nothing() -> None:
    assert texts("SELECT 1 -- ; \n+ 1; SELECT 2") == ["SELECT 1 -- ; \n+ 1", "SELECT 2"]


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 1; -- bye", ["SELECT 1"]),
        ("SELECT 1; /* bye */", ["SELECT 1"]),
        ("-- only\n/* here */", []),
        ("-- c\n;", []),
        (";;;", []),
        ("SELECT 1;; SELECT 2;", ["SELECT 1", "SELECT 2"]),
        ("SELECT 1; /* c */ ; SELECT 2", ["SELECT 1", "SELECT 2"]),
        ("", []),
        ("  \n\t\n", []),
    ],
)
def test_a_segment_of_comments_only_is_not_a_statement(script: str, expected: list[str]) -> None:
    assert texts(script) == expected


def test_a_comment_before_a_statement_stays_with_it() -> None:
    assert texts("-- c\nSELECT 1; /* d */ SELECT 2;") == ["-- c\nSELECT 1", "/* d */ SELECT 2"]


# ---- dot lines ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script, command, line",
    [
        (".mode csv\nSELECT 1;", ".mode", 1),
        ("SELECT 1;\n.mode csv\nSELECT 2;", ".mode", 2),
        ("-- c\n.read x.sql\nSELECT 1;", ".read", 2),
        ("/* a\n b */\n.exit\nSELECT 1;", ".exit", 3),
        ("SELECT 1;\n\n\n.shell echo hi", ".shell", 4),
        ("SELECT 1;\r\n.mode csv\r\nSELECT 2;", ".mode", 2),
        (".MODE csv", ".MODE", 1),
        (".5\nSELECT 1;", ".5", 1),
        (".\nSELECT 1;", ".", 1),
        (".mode csv;\nSELECT 1;", ".mode", 1),
        ("CREATE TABLE t(a INT);\n-- c;\n.open x.db", ".open", 3),
        ("\ufeff.mode csv\nSELECT 1;", ".mode", 1),
        ("SELECT 'a';\n.bail on", ".bail", 2),
    ],
)
def test_a_dot_line_with_nothing_pending_is_refused(script: str, command: str, line: int) -> None:
    with pytest.raises(UnsupportedMetaCommandError) as raised:
        records(script)
    assert command in str(raised.value) and f"line {line}" in str(raised.value)


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 1\n.mode csv\n;", ["SELECT 1\n.mode csv"]),
        ("SELECT\n.5;", ["SELECT\n.5"]),
        ("SELECT 'a\n.mode csv\nb'; SELECT 2", ["SELECT 'a\n.mode csv\nb'", "SELECT 2"]),
        ('SELECT 1 AS "a\n.mode csv\nb"; SELECT 2', ['SELECT 1 AS "a\n.mode csv\nb"', "SELECT 2"]),
        ("SELECT $$a\n.mode csv\nb$$; SELECT 2", ["SELECT $$a\n.mode csv\nb$$", "SELECT 2"]),
        ("/*\n.mode csv\n*/ SELECT 1;", ["/*\n.mode csv\n*/ SELECT 1"]),
        ("  .mode csv\nSELECT 1;", [".mode csv\nSELECT 1"]),
        ("\t.mode csv\nSELECT 1;", [".mode csv\nSELECT 1"]),
        ("SELECT 1; .mode csv\nSELECT 2;", ["SELECT 1", ".mode csv\nSELECT 2"]),
        ("/* c */ .mode csv\nSELECT 1;", ["/* c */ .mode csv\nSELECT 1"]),
        ("SELECT 1;\r.mode csv\rSELECT 2;", ["SELECT 1", ".mode csv\rSELECT 2"]),
    ],
)
def test_a_dot_line_is_text_when_it_is_not_where_the_shell_reads_a_command(
    script: str, expected: list[str]
) -> None:
    assert texts(script) == expected


@pytest.mark.parametrize("script", ["SELECT 1;\n\\q\nSELECT 2;", "\\d t", "SELECT 1\n\\\n;"])
def test_a_backslash_line_is_text_not_a_directive(script: str) -> None:
    assert len(texts(script)) >= 1 and any("\\" in text for text in texts(script))


@pytest.mark.parametrize("script", ["SELECT 6\n/\n2;", "SELECT 1\ngo\n;", "SELECT 6\n/ -- c\n2;"])
def test_a_go_or_slash_line_is_part_of_the_statement(script: str) -> None:
    assert len(texts(script)) == 1


# ---- bytes --------------------------------------------------------------------------------------------


def test_a_nul_is_refused_with_its_line() -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 2"):
        records("SELECT 1;\nSELECT 2;\x00 SELECT 3;")


def test_a_nul_inside_a_literal_is_refused_too() -> None:
    with pytest.raises(UnsafeStatementSplitError):
        records("SELECT 'a\x00b;c'; SELECT 2;")


def test_a_byte_order_mark_is_a_blank_at_the_start_and_in_the_middle() -> None:
    assert texts("\ufeffSELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]
    assert texts("SELECT 1;\ufeffSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_only_the_blanks_of_the_engine_are_trimmed_from_a_statement() -> None:
    assert texts("SELECT 1;\u00a0SELECT 2;") == ["SELECT 1", "SELECT 2"]
    assert texts("SELECT 1;\u3000SELECT 2;") == ["SELECT 1", "SELECT 2"]
    assert texts("SELECT 1;\u0085SELECT 2;") == ["SELECT 1", "\u0085SELECT 2"]
    assert texts("SELECT 1;\x0bSELECT 2;") == ["SELECT 1", "\x0bSELECT 2"]
    assert texts("SELECT 1;\x0cSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_crlf_and_lone_cr_are_kept_in_the_text() -> None:
    assert texts("SELECT 1\r\n+ 1;\r\nSELECT 2;\r\n") == ["SELECT 1\r\n+ 1", "SELECT 2"]
    assert texts("SELECT 1\r+ 1;\rSELECT 2;\r") == ["SELECT 1\r+ 1", "SELECT 2"]


# ---- records ----------------------------------------------------------------------------------------------


def test_each_record_has_the_line_of_the_first_character_of_its_text() -> None:
    script = "SELECT 'a\nb';\n\n-- c\n/* d\ne */ SELECT\n1;\nSELECT 3"
    assert [(unit.line, unit.terminator) for unit in records(script)] == [
        (1, ";"),
        (4, ";"),
        (8, None),
    ]


def test_lines_are_counted_across_strings_comments_and_identifiers() -> None:
    script = 'SELECT $$a\nb$$;\n/* c\nd */ SELECT "e\nf";\nSELECT 3;'
    assert [unit.line for unit in records(script)] == [1, 3, 6]


def test_the_last_statement_has_no_terminator() -> None:
    assert [(u.text, u.terminator) for u in records("SELECT 1; SELECT 2")] == [
        ("SELECT 1", ";"),
        ("SELECT 2", None),
    ]


def test_comment_only_segments_are_not_units_in_either_projection() -> None:
    engine = LexicalEngine(DUCKDB_SPEC)
    for script, expected in (
        ("SELECT 1; -- bye", ["SELECT 1"]),
        ("-- only\n/* here */\n", []),
        ("/* a /* b */ c */", []),
    ):
        assert [u.text for u in records(script)] == expected
        assert engine.split_for_analysis(script) == expected
    assert records(";;;\n ; \n") == []


def test_the_refusals_do_not_depend_on_the_projection() -> None:
    for script, error in (
        (".mode csv\nSELECT 1;", UnsupportedMetaCommandError),
        ("SELECT 1;\x00", UnsafeStatementSplitError),
    ):
        with pytest.raises(error):
            LexicalEngine(DUCKDB_SPEC).split_for_analysis(script)


# ---- huge lexemes -----------------------------------------------------------------------------------------
# The cost of reading a script (the number of operations per character) is held by
# test_duckdb_splitting_cost_grows_linearly; these check the cut.


@pytest.mark.parametrize(
    "script",
    [
        "SELECT '" + "x;" * 200_000 + "';",
        "SELECT $t$" + "x;$ " * 200_000 + "$t$;",
        "/*" + " /* ; */ ;" * 100_000 + "*/ SELECT 1;",
        "SELECT E'" + "a\\'" * 200_000 + "';",
    ],
    ids=["string", "dollar string", "comment", "escape string"],
)
def test_a_huge_literal_and_a_huge_comment_are_one_statement(script: str) -> None:
    assert len(texts(script)) == 1
