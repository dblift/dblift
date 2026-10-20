"""How the shared tokenizer reads the lexemes, comments and shell command lines of a DuckDB script."""

import warnings
from dataclasses import replace
from typing import List, Tuple

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import Token
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_RULES, DUCKDB_SPEC

BOM, NBSP, LS, NEL, ZWNJ = chr(0xFEFF), chr(0xA0), chr(0x2028), chr(0x85), chr(0x200C)
E_ACUTE, EURO, SQUARED, ARABIC_THREE = chr(0xE9), chr(0x20AC), chr(0xB2), chr(0x663)
ENGINE_BLANKS = (
    [chr(0xA0)]
    + [chr(c) for c in range(0x2000, 0x200C)]
    + [chr(0x202F), chr(0x205F), chr(0x2060), chr(0x3000), chr(0xFEFF)]
)
Item = Tuple[str, str]


def kw(text: str) -> Item:
    return ("KEYWORD", text)


def st(text: str) -> Item:
    return ("STRING", text)


def ident(text: str) -> Item:
    return ("IDENTIFIER", text)


def sym(text: str) -> Item:
    return ("SYMBOL", text)


def dl() -> Item:
    return ("DELIMITER", ";")


def cm(text: str) -> Item:
    return ("COMMENT", text)


def read(script: str, spec: LexicalSpec = DUCKDB_SPEC) -> Tuple[LexicalTokenizer, List[Token]]:
    tokenizer = LexicalTokenizer(script, spec=spec)
    return tokenizer, tokenizer.tokenize()


def shape(script: str, spec: LexicalSpec = DUCKDB_SPEC) -> List[Item]:
    return [(t.type.name, t.text) for t in read(script, spec)[1]]


def comments(script: str, spec: LexicalSpec = DUCKDB_SPEC) -> List[str]:
    tokenizer, _ = read(script, spec)
    return [tokenizer.sql[start:end] for start, end in tokenizer.comments]


def refusal(script: str, spec: LexicalSpec = DUCKDB_SPEC) -> Tuple[str, str]:
    with pytest.raises((UnsafeStatementSplitError, UnsupportedMetaCommandError)) as caught:
        read(script, spec)
    return type(caught.value).__name__, str(caught.value)


SELECT_2 = [kw("SELECT"), ident("2"), dl()]
EXTENTS = [
    ("SELECT 'a;b'; SELECT 2;", [kw("SELECT"), st("'a;b'"), dl()] + SELECT_2),
    ("SELECT E'a\\'b;c'; SELECT 2;", [kw("SELECT"), kw("E"), st("'a\\'b;c'"), dl()] + SELECT_2),
    ("SELECT 'a\\'; SELECT 2;", [kw("SELECT"), st("'a\\'"), dl()] + SELECT_2),
    ("SELECT $$a;'b$$; SELECT 2;", [kw("SELECT"), st("$$a;'b$$"), dl()] + SELECT_2),
    ("SELECT $x$ a $$ ; $x$; SELECT 2;", [kw("SELECT"), st("$x$ a $$ ; $x$"), dl()] + SELECT_2),
    (
        'CREATE TABLE "weird;name"(a INT); CREATE TABLE "a--b"(c INT);',
        [
            kw("CREATE"),
            kw("TABLE"),
            ident('"weird;name"'),
            sym("("),
            kw("a"),
            kw("INT"),
            sym(")"),
            dl(),
        ]
        + [
            kw("CREATE"),
            kw("TABLE"),
            ident('"a--b"'),
            sym("("),
            kw("c"),
            kw("INT"),
            sym(")"),
            dl(),
        ],
    ),
    ("/* a /* b */ ; */ SELECT 1;", [cm("/* a /* b */ ; */"), kw("SELECT"), ident("1"), dl()]),
    ("SELECT 'it''s;'; SELECT 2;", [kw("SELECT"), st("'it''s;'"), dl()] + SELECT_2),
    ("SELECT E'it''s;'; SELECT 2;", [kw("SELECT"), kw("E"), st("'it''s;'"), dl()] + SELECT_2),
    ("SELECT E'a\\\\'; SELECT 2;", [kw("SELECT"), kw("E"), st("'a\\\\'"), dl()] + SELECT_2),
    ("SELECT E'a''\\'b;c'; SELECT 2;", [kw("SELECT"), kw("E"), st("'a''\\'b;c'"), dl()] + SELECT_2),
    ("SELECT $$a\n;\nb$$; SELECT 2;", [kw("SELECT"), st("$$a\n;\nb$$"), dl()] + SELECT_2),
    ("SELECT $$$$; SELECT 2;", [kw("SELECT"), st("$$$$"), dl()] + SELECT_2),
    (
        "PREPARE p AS SELECT $1; EXECUTE p(5);",
        [kw("PREPARE"), kw("p"), kw("AS"), kw("SELECT"), sym("$1"), dl()]
        + [kw("EXECUTE"), kw("p"), sym("("), ident("5"), sym(")"), dl()],
    ),
    (
        "PREPARE p AS SELECT $a; SELECT 2;",
        [kw("PREPARE"), kw("p"), kw("AS"), kw("SELECT"), sym("$"), kw("a"), dl()]
        + [kw("SELECT"), ident("2"), dl()],
    ),
    (
        "SELECT 1 AS a$$; SELECT 'x$$';",
        [kw("SELECT"), ident("1"), kw("AS"), kw("a$$"), dl(), kw("SELECT"), st("'x$$'"), dl()],
    ),
    ("SELECT$$a;b$$;", [kw("SELECT$$a"), dl(), kw("b$$"), dl()]),
    ("SELECT ($$a;b$$);", [kw("SELECT"), sym("("), st("$$a;b$$"), sym(")"), dl()]),
    (
        'CREATE TABLE "a""b;c"(x INT);',
        [
            kw("CREATE"),
            kw("TABLE"),
            ident('"a""b;c"'),
            sym("("),
            kw("x"),
            kw("INT"),
            sym(")"),
            dl(),
        ],
    ),
    (
        "CREATE TABLE [a;b](x INT);",
        [
            kw("CREATE"),
            kw("TABLE"),
            sym("["),
            kw("a"),
            dl(),
            kw("b"),
            sym("]"),
            sym("("),
            kw("x"),
            kw("INT"),
            sym(")"),
            dl(),
        ],
    ),
    (
        "SELECT {'a': ';'};",
        [kw("SELECT"), sym("{"), st("'a'"), sym(":"), st("';'"), sym("}"), dl()],
    ),
    (
        "SELECT 1; */ SELECT 2;",
        [kw("SELECT"), ident("1"), dl(), sym("*"), sym("/"), kw("SELECT"), ident("2"), dl()],
    ),
    ("SELECT 'a'\n'b';", [kw("SELECT"), st("'a'"), st("'b'"), dl()]),
    ("SELECT\n.5;", [kw("SELECT"), sym("."), ident("5"), dl()]),
    (
        "SELECT 1;\n\\d t\nSELECT 2;",
        [
            kw("SELECT"),
            ident("1"),
            dl(),
            sym("\\"),
            kw("d"),
            kw("t"),
            kw("SELECT"),
            ident("2"),
            dl(),
        ],
    ),
    ("SELECT" + NBSP + "$$a;b$$;", [kw("SELECT"), st("$$a;b$$"), dl()]),
]


@pytest.mark.parametrize("script,expected", EXTENTS)
def test_lexeme_extents(script, expected):
    assert shape(script) == expected


def test_token_positions_are_source_offsets():
    tokens = read(BOM + "SELECT 1;\nSELECT 'x';")[1]
    assert [(t.text, t.pos, t.line, t.col) for t in tokens] == [
        ("SELECT", 1, 1, 1),
        ("1", 8, 1, 8),
        (";", 9, 1, 9),
        ("SELECT", 11, 2, 1),
        ("'x'", 18, 2, 8),
        (";", 21, 2, 11),
    ]
    assert shape("SELECT 1;" + BOM + "SELECT 2;") == [
        kw("SELECT"),
        ident("1"),
        dl(),
        kw("SELECT"),
        ident("2"),
        dl(),
    ]


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 1; SELECT 'open;x",
        'SELECT 1; "open;x',
        "SELECT 1; E'open\\';x",
        "SELECT 1; $$open;x",
        "SELECT 1; $t$open;x$$",
        "SELECT 1; /* open;x",
        "SELECT 1; /* /* open */ ;x",
    ],
)
def test_unterminated_lexemes_run_to_the_end(script):
    tokenizer, tokens = read(script)
    assert tokens
    last = tokens[-1]
    assert last.pos + len(last.text) == len(script)
    assert last.text.endswith(("open;x", "open */ ;x", "open\\';x", "$$"))
    assert [t.text for t in tokens].count(";") == 1  # only the first statement's terminator
    assert comments(script) == []


def test_unterminated_block_comment_is_code_not_a_comment():
    assert shape("SELECT 1; /* open") == [kw("SELECT"), ident("1"), dl(), sym("/* open")]
    assert comments("SELECT 1; /* open") == []
    assert shape("SELECT 1; /* /* a */ b") == [kw("SELECT"), ident("1"), dl(), sym("/* /* a */ b")]


@pytest.mark.parametrize(
    "script, where",
    [
        ("SELECT 1; /* open", "line 1, column 11"),
        ("SELECT 1;\n/* /* a */ b", "line 2, column 1"),
        ("/* a /* b */", "line 1, column 1"),
        ("SELECT 1" + NBSP + "/* open", "line 1, column 10"),
        ("SELECT 1; SELECT 2 -- /* x\n/* open;", "line 2, column 1"),
    ],
)
def test_the_split_refuses_an_unterminated_block_comment(script, where):
    with pytest.raises(UnsafeStatementSplitError) as raised:
        LexicalEngine(DUCKDB_SPEC).split(script)
    assert str(raised.value) == f"unterminated block comment opened at {where}"


@pytest.mark.parametrize(
    "script",
    [
        "/* a /* b */ */ SELECT 1",
        "SELECT '/* x'; SELECT 1 AS \"/* y\"; SELECT 2 -- /* z\n",
        "SELECT $t$ /* x",
        "SELECT 1 /*/ x */",
    ],
)
def test_the_split_does_not_refuse_what_opens_no_open_comment(script):
    assert LexicalEngine(DUCKDB_SPEC).split(script)


@pytest.mark.parametrize("blank", ENGINE_BLANKS + list(" \t\n\f\r"))
def test_the_engine_blanks_separate_words(blank):
    assert shape(f"a{blank}b") == [kw("a"), kw("b")]


@pytest.mark.parametrize("char", [LS, NEL, chr(0x2029), chr(0x1680), ZWNJ, E_ACUTE, EURO, SQUARED])
def test_a_non_blank_non_ascii_character_is_a_word_character(char):
    assert shape(f"a{char}b;") == [kw(f"a{char}b"), dl()]


@pytest.mark.parametrize("blank", ENGINE_BLANKS)
def test_a_blank_after_a_dollar_inside_a_word_continues_the_word(blank):
    assert shape(f"a${blank}b;") == [kw(f"a${blank}b"), dl()]
    assert shape(f"a$b{blank}c;") == [kw(f"a$b{blank}c"), dl()]
    assert shape(f"{E_ACUTE}${blank}{blank}b;") == [kw(f"{E_ACUTE}${blank}{blank}b"), dl()]


@pytest.mark.parametrize("blank", ENGINE_BLANKS)
def test_a_dollar_tag_after_a_blank_inside_a_word_opens_nothing(blank):
    script = f"SELECT 1 AS a$${blank}$t$x; DROP TABLE t; SELECT 3 AS y$t$;"
    assert [t for t in shape(script) if t == dl()] == [dl(), dl(), dl()]
    assert shape(f"a$${blank}$t$x;y$t$") == [kw(f"a$${blank}$t$x"), dl(), kw("y$t$")]


@pytest.mark.parametrize("blank", [" ", "\n", "\t"])
def test_an_ascii_blank_after_a_dollar_ends_the_word_and_a_dollar_tag_opens(blank):
    assert shape(f"a${blank}$t$x;y$t$") == [kw("a$"), st("$t$x;y$t$")]


@pytest.mark.parametrize("blank", ENGINE_BLANKS)
def test_a_blank_before_any_dollar_ends_the_word_and_a_dollar_tag_opens(blank):
    assert shape(f"a{blank}$$x;y$$") == [kw("a"), st("$$x;y$$")]


def test_a_blank_continuing_a_word_hides_the_escape_letter_after_it():
    assert shape(f"a${NBSP}E'x\\';y'") == [kw(f"a${NBSP}E"), st("'x\\'"), dl(), kw("y"), st("'")]
    assert shape(f"a{NBSP}E'x\\';y'") == [kw("a"), kw("E"), st("'x\\';y'")]


def test_a_dollar_followed_by_a_digit_does_not_make_a_blank_continue_the_word():
    assert shape(f"a$1{NBSP}b;") == [kw("a$1"), kw("b"), dl()]
    assert shape(f"a$1$1{NBSP}b;") == [kw("a$1$1"), kw("b"), dl()]
    assert shape(f"a$1${NBSP}b;") == [kw(f"a$1${NBSP}b"), dl()]
    assert shape(f"a$$1{NBSP}b;") == [kw(f"a$$1{NBSP}b"), dl()]


def test_a_vertical_tab_is_a_symbol():
    assert shape("a\x0bb") == [kw("a"), sym("\x0b"), kw("b")]


def test_blanks_are_data():
    assert len(ENGINE_BLANKS) == 18
    assert shape(f";{NBSP};") == [dl(), dl()]
    assert shape(
        f";{NBSP};", replace(DUCKDB_SPEC, segment_script=replace(DUCKDB_RULES, blanks=" \t\n\f\r"))
    ) == [dl(), sym(NBSP), dl()]


def test_line_comment_ends():
    assert shape("SELECT 1; -- c\rSELECT 2;") == [kw("SELECT"), ident("1"), dl(), cm("-- c")] + [
        kw("SELECT"),
        ident("2"),
        dl(),
    ]
    assert comments("a -- c\nb -- d\r\ne -- f") == ["-- c", "-- d", "-- f"]
    lf_only = replace(DUCKDB_SPEC, segment_script=replace(DUCKDB_RULES, line_comment_ends="\n"))
    assert shape("SELECT 1; -- c\rSELECT 2;", lf_only) == [
        kw("SELECT"),
        ident("1"),
        dl(),
        cm("-- c\rSELECT 2;"),
    ]
    assert shape("a $$ -- b;$$ c") == [kw("a"), st("$$ -- b;$$"), kw("c")]


def test_comments_are_recorded():
    assert comments("a /* b */ c -- d\n/* e /* f /* g */ */ */ h /*/ x */") == [
        "/* b */",
        "-- d",
        "/* e /* f /* g */ */ */",
        "/*/ x */",
    ]
    assert comments("a /* b **/ c") == ["/* b **/"]
    assert comments("'/* x */' \"-- y\" $$ -- z$$") == []
    assert comments("SELECT 1 /* unclosed") == []
    assert comments("SELECT 1 -- to the end") == ["-- to the end"]


def test_words_numbers_and_parameters():
    assert shape("a$$b") == [kw("a$$b")]
    assert shape("1$$a;b$$") == [ident("1"), st("$$a;b$$")]
    assert shape(f"{EURO}$$a;b$$;") == [kw(f"{EURO}$$a"), dl(), kw("b$$"), dl()]
    assert shape("$1 $n $") == [sym("$1"), sym("$"), kw("n"), sym("$")]
    assert shape("$1a$") == [sym("$1"), kw("a$")]
    assert shape("$a b$") == [sym("$"), kw("a"), kw("b$")]
    assert shape("1x 12_a .5") == [ident("1"), kw("x"), ident("12"), kw("_a"), sym("."), ident("5")]
    assert shape("${a;b}") == [sym("$"), sym("{"), kw("a"), dl(), kw("b"), sym("}")]
    assert shape("$1$a;b$1$") == [sym("$1"), sym("$"), kw("a"), dl(), kw("b$1$")]


def test_a_parameter_ends_at_its_digits_and_the_letters_start_a_word():
    one_dollar = f"SELECT $1{E_ACUTE}$$x;y$$; SELECT 2;"
    assert shape("SELECT $1a$$x;y$$; SELECT 2 AS b;") == [
        kw("SELECT"),
        sym("$1"),
        kw("a$$x"),
        dl(),
        kw("y$$"),
        dl(),
    ] + [kw("SELECT"), ident("2"), kw("AS"), kw("b"), dl()]
    assert [t for t in shape(one_dollar) if t == dl()] == [dl(), dl(), dl()]
    assert (
        shape("SELECT $1E'a\\';b'; SELECT 2;")
        == [
            kw("SELECT"),
            sym("$1"),
            kw("E"),
            st("'a\\';b'"),
            dl(),
        ]
        + SELECT_2
    )


def test_a_parameter_is_digits_with_underscore_separators_or_a_name():
    assert shape("$1_0 $1_ $1__0") == [sym("$1_0"), sym("$1"), kw("_"), sym("$1"), kw("__0")]
    assert shape("$1$$x;y$$") == [sym("$1"), st("$$x;y$$")]
    assert shape("$1_0$$x;y$$") == [sym("$1_0"), st("$$x;y$$")]


NUMBER_THEN_WORD = [
    ("1a", [ident("1"), kw("a")]),
    ("1_000a", [ident("1_000"), kw("a")]),
    ("1_000_a", [ident("1_000"), kw("_a")]),
    ("1__0", [ident("1"), kw("__0")]),
    ("1.5a", [ident("1.5"), kw("a")]),
    ("1.5e3a", [ident("1.5e3"), kw("a")]),
    ("1e5a", [ident("1e5"), kw("a")]),
    ("1e+5a", [ident("1e+5"), kw("a")]),
    ("1e5e5", [ident("1e5"), kw("e5")]),
    ("1ea", [ident("1"), kw("ea")]),
    ("1e", [ident("1"), kw("e")]),
    ("0x1g", [ident("0"), kw("x1g")]),
]


@pytest.mark.parametrize("script,expected", NUMBER_THEN_WORD, ids=[c[0] for c in NUMBER_THEN_WORD])
def test_a_number_is_digits_fraction_and_exponent_and_the_letters_start_a_word(script, expected):
    assert shape(script) == expected


@pytest.mark.parametrize("number", ["1", "1_000", "1.5", "1e5", "1.5e3", "0"])
def test_a_dollar_pair_after_a_number_and_a_name_hides_nothing(number):
    script = f"SELECT {number}a$$x; DROP TABLE t; SELECT 3 AS y$$;"
    assert [t for t in shape(script) if t == dl()] == [dl(), dl(), dl()]


def test_a_dollar_tag_after_a_number_and_a_name_hides_nothing():
    script = "SELECT 1a$x$x; DROP TABLE t; SELECT 3 AS y$x$;"
    assert [t for t in shape(script) if t == dl()] == [dl(), dl(), dl()]


def test_a_dollar_string_straight_after_a_number_opens():
    for number in ("1", "1_000", "1.5", "1e5"):
        assert shape(f"{number}$$x;y$$")[-1] == st("$$x;y$$")


def test_words_and_numbers_are_data():
    no_dollar = replace(DUCKDB_RULES, word=r"[A-Za-z_][A-Za-z0-9_]*")
    assert shape("a$$b", replace(DUCKDB_SPEC, segment_script=no_dollar)) == [kw("a"), st("$$b")]
    letters_in_number = replace(DUCKDB_RULES, number=r"[0-9][0-9A-Za-z_]*")
    assert shape("12ab", replace(DUCKDB_SPEC, segment_script=letters_in_number)) == [ident("12ab")]
    assert shape(
        "$ x", replace(DUCKDB_SPEC, segment_script=replace(DUCKDB_RULES, parameter=r"\$[0-9]+"))
    ) == [sym("$"), kw("x")]


def test_dollar_tags():
    for tag in ("X", "a1", E_ACUTE, EURO, SQUARED, ZWNJ, "_"):
        script = f"SELECT ${tag}$ a ; ${tag}$; SELECT 2;"
        assert shape(script)[:3] == [kw("SELECT"), st(f"${tag}$ a ; ${tag}$"), dl()]
    assert shape("SELECT $a$ x $b$ ; $b$ y ; $a$;")[1] == st("$a$ x $b$ ; $b$ y ; $a$")
    assert shape("SELECT $ab$ $a$ ; $ab$;")[1] == st("$ab$ $a$ ; $ab$")
    assert shape("SELECT $X$ a $x$ ; $X$;")[1] == st("$X$ a $x$ ; $X$")
    ascii_tag = replace(DUCKDB_RULES, dollar_tag=r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
    assert shape(f"${EURO}$a;b${EURO}$")[0] == st(f"${EURO}$a;b${EURO}$")
    assert shape(f"${EURO}$a;b${EURO}$", replace(DUCKDB_SPEC, segment_script=ascii_tag))[0] == sym(
        "$"
    )


@pytest.mark.parametrize(
    "script,expected",
    [
        ("E'a\\';b'", [kw("E"), st("'a\\';b'")]),
        ("e'a\\';b'", [kw("e"), st("'a\\';b'")]),
        ("xE'a\\';b'", [kw("xE"), st("'a\\'"), dl(), kw("b"), st("'")]),
        ("(1)E'a\\';b'", [sym("("), ident("1"), sym(")"), kw("E"), st("'a\\';b'")]),
        ("'a'E'b\\';c'", [st("'a'"), kw("E"), st("'b\\';c'")]),
        ("1E'b\\';c'", [ident("1"), kw("E"), st("'b\\';c'")]),
        ("12e'b\\';c'", [ident("12"), kw("e"), st("'b\\';c'")]),
        ("1xE'b\\';c'", [ident("1"), kw("xE"), st("'b\\'"), dl(), kw("c"), st("'")]),
        (SQUARED + "E'b\\';c'", [kw(SQUARED + "E"), st("'b\\'"), dl(), kw("c"), st("'")]),
        (ARABIC_THREE + "E'b\\';c'", [kw(ARABIC_THREE + "E"), st("'b\\'"), dl(), kw("c"), st("'")]),
        ("E 'a\\';b'", [kw("E"), st("'a\\'"), dl(), kw("b"), st("'")]),
        ("$$q$$E'a\\';b'", [st("$$q$$"), kw("E"), st("'a\\';b'")]),
        ("$1E'a\\';b'", [sym("$1"), kw("E"), st("'a\\';b'")]),
    ],
)
def test_escape_rule(script, expected):
    assert shape(script) == expected


def test_escape_letters_are_data():
    upper_only = replace(DUCKDB_SPEC, segment_script=replace(DUCKDB_RULES, escape_letters="E"))
    assert shape("e'a\\';b'", upper_only) == [kw("e"), st("'a\\'"), dl(), kw("b"), st("'")]
    assert shape("E'a\\';b'", upper_only) == [kw("E"), st("'a\\';b'")]


CONTINUED = [kw("SELECT"), kw("E"), st("'a'")]
ESCAPE_THEN = "SELECT E'a'{gap}'b\\'; SELECT 2;"


@pytest.mark.parametrize(
    "gap,continued",
    [
        (" ", False),
        ("\n", True),
        ("\r", True),
        ("\r\n", True),
        (" -- c\n", True),
        ("\t", False),
        (NBSP, False),
        ("  -- c\n  ", True),
    ],
)
def test_escape_mode_continues_only_across_line_breaks(gap, continued):
    items = shape(ESCAPE_THEN.format(gap=gap))
    assert [i for i in items if i[0] == "STRING"] == [
        st("'a'"),
        st("'b\\'; SELECT 2;") if continued else st("'b\\'"),
    ]
    assert (dl() not in items) == continued


@pytest.mark.parametrize(
    "gap", [" /* c */\n", ' "q" ', " $1 ", "; ", " x ", " + ", " (", " $$q$$ ", " 1 "]
)
def test_escape_mode_ends_at_any_other_token(gap):
    items = shape(ESCAPE_THEN.format(gap=gap))
    assert st("'b\\'") in items
    assert dl() in items


def test_escape_mode_in_the_reference_cases():
    same_line = shape("SELECT E'a' 'b\\'; SELECT 1 AS y; SELECT 'z';")
    assert same_line == CONTINUED + [
        st("'b\\'"),
        dl(),
        kw("SELECT"),
        ident("1"),
        kw("AS"),
        kw("y"),
        dl(),
        kw("SELECT"),
        st("'z'"),
        dl(),
    ]
    assert shape("SELECT E'a'\n'b\\'; SELECT 1 AS y; SELECT 'z';") == CONTINUED + [
        st("'b\\'; SELECT 1 AS y; SELECT '"),
        kw("z"),
        st("';"),
    ]
    assert shape("SELECT E'a' /* c */\n'b\\'' AS x; SELECT 2 AS y;")[3:] == [
        cm("/* c */"),
        st("'b\\'' AS x; SELECT 2 AS y;"),
    ]
    assert shape("SELECT E'a' 'p' 'b\\'' AS x;")[2:5] == [st("'a'"), st("'p'"), st("'b\\'' AS x;")]


def test_refusals_of_the_refused_character():
    message = "a NUL character on line {}: the engine reads the script up to it and silently drops the rest"
    assert refusal("SELECT 1;\n\x00SELECT 2;") == ("UnsafeStatementSplitError", message.format(2))
    assert refusal(".mode csv\n\x00") == ("UnsafeStatementSplitError", message.format(2))
    assert refusal(BOM + "\x00") == ("UnsafeStatementSplitError", message.format(1))
    assert refusal("'a\x00b'")[1] == message.format(1)
    assert refusal("/* a\n\n\x00 */")[1] == message.format(3)
    assert refusal('"a\x00" $$\x00$$')[1] == message.format(1)
    assert refusal("SELECT 1;\r\x00") == ("UnsafeStatementSplitError", message.format(1))


def test_refusals_of_shell_command_lines():
    text = "duckdb shell command {!r} on line {}: the shell runs it and the engine cannot; dblift does not run client commands"
    assert refusal(".mode csv\nSELECT 1;") == (
        "UnsupportedMetaCommandError",
        text.format(".mode", 1),
    )
    assert refusal("SELECT 1;\n.mode csv\nSELECT 2;")[1] == text.format(".mode", 2)
    assert refusal("-- c\n.mode csv\nSELECT 1;")[1] == text.format(".mode", 2)
    assert refusal("SELECT 1; -- c\n.print x\nSELECT 2;")[1] == text.format(".print", 2)
    assert refusal("SELECT 1 AS a;\r\n.print x\r\nSELECT 2;")[1] == text.format(".print", 2)
    assert refusal("SELECT 1 AS a;\n/* x\n*/\n.print hi\nSELECT 2;")[1] == text.format(".print", 4)
    assert refusal(BOM + ".print x\nSELECT 1;")[1] == text.format(".print", 1)
    assert refusal("SELECT 1;\n.\nSELECT 2;")[1] == text.format(".", 2)
    for tail in ("\tx", "\rx", NBSP + "x", NEL + "x", LS + "x", " x", ""):
        assert refusal(".print" + tail + "\nSELECT 1;")[1] == text.format(".print", 1)


@pytest.mark.parametrize(
    "script",
    [
        "SELECT 'a\n.mode csv\nb'; SELECT 2;",
        "/*\n.mode csv\n*/ SELECT 1;",
        "SELECT 1\n.mode csv\n;",
        "  .mode csv\nSELECT 1;",
        "SELECT\n.5;",
        'SELECT 1 AS "a\n.mode csv\nb"; SELECT 2;',
        "SELECT 1 AS a; .print x\nSELECT 2 AS b;",
        "SELECT 1 AS a;\r.print x\nSELECT 2 AS b;",
        "SELECT $$a\n.print x\nb$$ AS s;",
        "SELECT 1; \x0b.print x",
        "SELECT E'a\n.print x\nb'; SELECT 1;",
        "SELECT 1 /* open\n.print x",
    ],
)
def test_a_dot_that_is_not_a_command_line_is_text(script):
    tokens = read(script)[1]
    assert tokens
    end = 0
    for token in tokens:  # the tokens tile the script: only blanks lie between them
        assert set(script[end : token.pos]) <= set(DUCKDB_RULES.blanks)
        assert script[token.pos : token.pos + len(token.text)] == token.text
        end = token.pos + len(token.text)
    assert set(script[end:]) <= set(DUCKDB_RULES.blanks)


@pytest.mark.parametrize(
    "script,expected",
    [
        ('"a"\n.print x\n;', [ident('"a"'), sym("."), kw("print"), kw("x"), dl()]),
        ("'a'\n.print x\n;", [st("'a'"), sym("."), kw("print"), kw("x"), dl()]),
        ("$$a$$\n.print x\n;", [st("$$a$$"), sym("."), kw("print"), kw("x"), dl()]),
        ("SELECT $$a\n.x;y$$;", [kw("SELECT"), st("$$a\n.x;y$$"), dl()]),
        (
            "SELECT 1; -- $$ x\nSELECT 2;",
            [kw("SELECT"), ident("1"), dl(), cm("-- $$ x"), kw("SELECT"), ident("2"), dl()],
        ),
        ("SELECT $t$t$ ; $t$;", [kw("SELECT"), st("$t$t$ ; $t$"), dl()]),
    ],
)
def test_pending_code_and_bodies_around_dot_lines_and_dollars(script, expected):
    assert shape(script) == expected


def test_command_message_and_refusal_are_read_from_the_spec():
    renamed = replace(DUCKDB_SPEC, client_name="x shell")
    assert refusal(".mode\nSELECT 1;", renamed)[1].startswith("x shell command '.mode' on line 1:")
    bang = replace(
        DUCKDB_SPEC,
        segment_script=replace(
            DUCKDB_RULES, command_prefix="!", refused_character_name="X", refused_reason="r"
        ),
    )
    assert refusal("!print\nSELECT 1;", bang)[1].startswith(
        "duckdb shell command '!print' on line 1:"
    )
    assert shape(".mode\nSELECT 1;", bang)[0] == sym(".")
    assert refusal("a\x00", bang) == ("UnsafeStatementSplitError", "a X character on line 1: r")
    other_char = replace(DUCKDB_SPEC, segment_script=replace(DUCKDB_RULES, refused_character="@"))
    assert refusal("a\nb@", other_char)[1].startswith("a NUL character on line 2:")
    assert shape("a\x00b", other_char) == [kw("a"), sym("\x00"), kw("b")]


def test_nothing_is_refused_at_the_end_of_a_script():
    for script in (
        "SELECT 'x",
        'SELECT "x',
        "SELECT $$x",
        "SELECT /* x",
        "SELECT E'x\\",
        "SELECT -- x",
        "$$",
        "'",
        "E'",
    ):
        assert read(script)[1]


def test_strict_tokenizer_has_no_effect_for_duckdb():
    script = "SELECT @ # \\ ` ~ ^ % & | ? !;"
    tokenizer = LexicalTokenizer(script, spec=DUCKDB_SPEC)
    tokenizer.strict_unknown_chars = True
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        tokens = tokenizer.tokenize()
    assert [t.text for t in tokens if t.type.name == "SYMBOL"] == list("@#\\`~^%&|?!")


def test_the_byte_order_mark_is_dropped_only_when_the_spec_says_so():
    script = BOM + ".print x\nSELECT 1;"
    assert refusal(script)[0] == "UnsupportedMetaCommandError"
    kept = replace(DUCKDB_SPEC, leading_bom_is_blank=False)
    assert shape(script, kept)[:2] == [sym("."), kw("print")]
