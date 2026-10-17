"""How the shared tokenizer reads the lexemes, comments and shell command lines of a DuckDB script."""

import warnings
from dataclasses import replace
from typing import List, Tuple

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
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
        [kw("PREPARE"), kw("p"), kw("AS"), kw("SELECT"), sym("$a"), dl()]
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


@pytest.mark.parametrize("blank", ENGINE_BLANKS + list(" \t\n\f\r"))
def test_the_engine_blanks_separate_words(blank):
    assert shape(f"a{blank}b") == [kw("a"), kw("b")]


@pytest.mark.parametrize("char", [LS, NEL, chr(0x2029), chr(0x1680), ZWNJ, E_ACUTE, EURO, SQUARED])
def test_a_non_blank_non_ascii_character_is_a_word_character(char):
    assert shape(f"a{char}b;") == [kw(f"a{char}b"), dl()]


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
    assert shape("$1 $n $") == [sym("$1"), sym("$n"), sym("$")]
    assert shape("$1a$") == [sym("$1a"), sym("$")]
    assert shape("$a b$") == [sym("$a"), kw("b$")]
    assert shape("1x 12_a .5") == [ident("1x"), ident("12_a"), sym("."), ident("5")]
    assert shape("${a;b}") == [sym("$"), sym("{"), kw("a"), dl(), kw("b"), sym("}")]
    assert shape("$1$a;b$1$") == [sym("$1"), sym("$a"), dl(), kw("b$1$")]


def test_a_parameter_swallows_the_letters_after_its_digits():
    one_dollar = f"SELECT $1{E_ACUTE}$$x;y$$; SELECT 2;"
    assert shape("SELECT $1a$$x;y$$; SELECT 2 AS b;") == [
        kw("SELECT"),
        sym("$1a"),
        st("$$x;y$$"),
        dl(),
    ] + [kw("SELECT"), ident("2"), kw("AS"), kw("b"), dl()]
    assert [t for t in shape(one_dollar) if t == dl()] == [dl(), dl()]
    ascii_parameter = replace(DUCKDB_RULES, parameter=r"\$[A-Za-z0-9_]*")
    assert [
        t
        for t in shape(one_dollar, replace(DUCKDB_SPEC, segment_script=ascii_parameter))
        if t == dl()
    ] == [dl(), dl(), dl()]
    assert shape("SELECT $1E'a\\';b'; SELECT 2;") == [
        kw("SELECT"),
        sym("$1E"),
        st("'a\\'"),
        dl(),
        kw("b"),
        st("'; SELECT 2;"),
    ]


def test_words_and_numbers_are_data():
    no_dollar = replace(DUCKDB_RULES, word=r"[A-Za-z_][A-Za-z0-9_]*")
    assert shape("a$$b", replace(DUCKDB_SPEC, segment_script=no_dollar)) == [kw("a"), st("$$b")]
    no_letters = replace(DUCKDB_RULES, number=r"[0-9]+")
    assert shape("12ab", replace(DUCKDB_SPEC, segment_script=no_letters)) == [ident("12"), kw("ab")]
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
        f"${EURO}"
    )


@pytest.mark.parametrize(
    "script,expected",
    [
        ("E'a\\';b'", [kw("E"), st("'a\\';b'")]),
        ("e'a\\';b'", [kw("e"), st("'a\\';b'")]),
        ("xE'a\\';b'", [kw("xE"), st("'a\\'"), dl(), kw("b"), st("'")]),
        ("(1)E'a\\';b'", [sym("("), ident("1"), sym(")"), kw("E"), st("'a\\';b'")]),
        ("'a'E'b\\';c'", [st("'a'"), kw("E"), st("'b\\';c'")]),
        ("1E'b\\';c'", [ident("1E"), st("'b\\';c'")]),
        ("12e'b\\';c'", [ident("12e"), st("'b\\';c'")]),
        ("1xE'b\\';c'", [ident("1xE"), st("'b\\'"), dl(), kw("c"), st("'")]),
        (SQUARED + "E'b\\';c'", [kw(SQUARED + "E"), st("'b\\';c'")]),
        (ARABIC_THREE + "E'b\\';c'", [kw(ARABIC_THREE + "E"), st("'b\\';c'")]),
        ("E 'a\\';b'", [kw("E"), st("'a\\'"), dl(), kw("b"), st("'")]),
        ("$$q$$E'a\\';b'", [st("$$q$$"), kw("E"), st("'a\\';b'")]),
        ("$1E'a\\';b'", [sym("$1E"), st("'a\\'"), dl(), kw("b"), st("'")]),
    ],
)
def test_escape_rule(script, expected):
    assert shape(script) == expected


def test_escape_letters_are_data():
    upper_only = replace(DUCKDB_SPEC, segment_script=replace(DUCKDB_RULES, escape_letters="E"))
    assert shape("e'a\\';b'", upper_only) == [kw("e"), st("'a\\'"), dl(), kw("b"), st("'")]
    assert shape("E'a\\';b'", upper_only) == [kw("E"), st("'a\\';b'")]


ESCAPE_THEN = "SELECT E'a'{gap}'b\\'' AS x; SELECT 2;"
CONTINUED = [kw("SELECT"), kw("E"), st("'a'")]


@pytest.mark.parametrize("gap", [" ", "\n", "\r", "\r\n", " -- c\n", "\t", NBSP, "  -- c\n  "])
def test_escape_mode_continues_across_blanks_and_line_comments(gap):
    items = shape(ESCAPE_THEN.format(gap=gap))
    assert [i for i in items if i[0] == "STRING"] == [st("'a'"), st("'b\\''")]


@pytest.mark.parametrize(
    "gap", [" /* c */\n", ' "q" ', " $1 ", "; ", " x ", " + ", " (", " $$q$$ ", " 1 "]
)
def test_escape_mode_ends_at_any_other_token(gap):
    items = shape(ESCAPE_THEN.format(gap=gap))
    assert st("'b\\'") in items
    assert st("'b\\''") not in items


def test_escape_mode_in_the_reference_cases():
    same_line = shape("SELECT E'a' 'b\\'; SELECT 1 AS y; SELECT 'z';")
    assert same_line == CONTINUED + [st("'b\\'; SELECT 1 AS y; SELECT '"), kw("z"), st("';")]
    assert shape("SELECT E'a'\n'b\\'; SELECT 1 AS y; SELECT 'z';") == same_line
    assert shape("SELECT E'a' /* c */\n'b\\'' AS x; SELECT 2 AS y;")[3:] == [
        cm("/* c */"),
        st("'b\\'"),
        st("' AS x; SELECT 2 AS y;"),
    ]
    assert shape("SELECT E'a' 'p' 'b\\'' AS x;")[2:5] == [st("'a'"), st("'p'"), st("'b\\''")]


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
    assert read(script)[1]


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
