"""How the shared tokenizer reads the lexemes of a Db2 command line processor script."""

import inspect
from dataclasses import replace
from typing import List, Tuple

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES, DB2_SPEC
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

BOM, NBSP, LS = chr(0xFEFF), chr(0xA0), chr(0x2028)
PLAIN_NESTED = LexicalSpec(name="plain", text_blanks=" ", nested_comments=True)


def read(script: str, spec: LexicalSpec = DB2_SPEC) -> Tuple[LexicalTokenizer, List[Token]]:
    tokenizer = LexicalTokenizer(script, spec=spec)
    return tokenizer, tokenizer.tokenize()


def code(tokens: List[Token]) -> List[Tuple[str, str]]:
    return [(t.type.name, t.text) for t in tokens if t.type != TokenType.COMMENT]


def comments(tokenizer: LexicalTokenizer) -> List[str]:
    return [tokenizer.sql[start:end] for start, end in tokenizer.comments]


def test_shared_handlers_read_db2_lexemes():
    _, tokens = read("VALUES 'it''s' \"a\"\"b\" X'3B' U&'\\0041;' GX'0041' 'a\\'")
    assert code(tokens) == [
        ("KEYWORD", "VALUES"),
        ("STRING", "'it''s'"),
        ("IDENTIFIER", '"a""b"'),
        ("KEYWORD", "X"),
        ("STRING", "'3B'"),
        ("KEYWORD", "U"),
        ("SYMBOL", "&"),
        ("STRING", "'\\0041;'"),
        ("KEYWORD", "GX"),
        ("STRING", "'0041'"),
        ("STRING", "'a\\'"),
    ]


def test_double_dash_is_string_text_inside_a_string_and_a_comment_outside():
    tokenizer, tokens = read("VALUES '--x' -- y\nz")
    assert code(tokens) == [("KEYWORD", "VALUES"), ("STRING", "'--x'"), ("KEYWORD", "z")]
    assert comments(tokenizer) == ["-- y"]


@pytest.mark.parametrize("depth", [1, 2, 3])
def test_block_comments_nest(depth):
    comment = "/* a " * depth + "x" + " */" * depth
    tokenizer, tokens = read(f"VALUES 1 {comment} y")
    assert comments(tokenizer) == [comment]
    assert code(tokens) == [("KEYWORD", "VALUES"), ("SYMBOL", "1"), ("KEYWORD", "y")]
    assert tokenizer.open_lexeme == -1


def test_nesting_is_a_spec_field():
    flat = replace(DB2_SPEC, nested_comments=False)
    tokenizer, tokens = read("VALUES /* a /* b */ c */ d", flat)
    assert comments(tokenizer) == ["/* a /* b */"]
    assert code(tokens)[-4:] == [
        ("KEYWORD", "c"),
        ("SYMBOL", "*"),
        ("SYMBOL", "/"),
        ("KEYWORD", "d"),
    ]


@pytest.mark.parametrize(
    "script, last",
    [
        ("VALUES 'open", ("STRING", "'open")),
        ("VALUES 'open\nstill", ("STRING", "'open\nstill")),
        ('VALUES "open', ("IDENTIFIER", '"open')),
        ("VALUES 'a''", ("STRING", "'a''")),
    ],
)
def test_unterminated_lexeme_runs_to_the_end(script, last):
    tokenizer, tokens = read(script)
    assert (tokens[-1].type.name, tokens[-1].text) == last
    assert tokenizer.open_lexeme == tokens[-1].pos


@pytest.mark.parametrize(
    "script", ["VALUES 'a'", 'VALUES "a"', "VALUES 'a'''", "VALUES /* a */", "VALUES 1 -- c"]
)
def test_closed_lexemes_leave_nothing_open(script):
    tokenizer, _ = read(script)
    assert tokenizer.open_lexeme == -1


@pytest.mark.parametrize(
    "script, open_depth",
    [("VALUES 1 /* open", 1), ("/* a /* b */ c", 1), ("/* a /* b", 2), ("/* a */", 0)],
)
def test_unterminated_comment_runs_to_the_end_and_reports_its_depth(script, open_depth):
    tokenizer, tokens = read(script)
    start, end = tokenizer.comments[-1]
    assert tokenizer.sql[start:end].startswith("/*") and end == len(script)
    assert tokenizer.open_lexeme == (start if open_depth else -1)


def test_blanks_inside_a_line_are_unicode_wide():
    _, tokens = read(f"VALUES{NBSP}1{LS}2\x0b3\x0c4")
    assert code(tokens) == [
        ("KEYWORD", "VALUES"),
        ("SYMBOL", "1"),
        ("SYMBOL", "2"),
        ("SYMBOL", "3"),
        ("SYMBOL", "4"),
    ]


def test_word_alphabet_comes_from_the_spec():
    _, tokens = read("BEGIN@x t#1 a$b 1abc " + chr(0xE9))
    assert [t.text for t in tokens if t.type == TokenType.KEYWORD] == [
        "BEGIN@x",
        "t#1",
        "a$b",
        "abc",
    ]
    without_at = replace(
        DB2_SPEC, terminator_script=replace(DB2_RULES, word=r"[A-Za-z_][A-Za-z0-9_$#]*")
    )
    _, narrowed = read("BEGIN@x", without_at)
    assert code(narrowed) == [("KEYWORD", "BEGIN"), ("SYMBOL", "@"), ("KEYWORD", "x")]


def test_every_other_character_is_a_one_character_symbol():
    _, tokens = read("a.b,(c)=1; x")
    assert [t.text for t in tokens if t.type == TokenType.SYMBOL] == [
        ".",
        ",",
        "(",
        ")",
        "=",
        "1",
        ";",
    ]


def test_a_byte_order_mark_is_dropped_and_its_offset_kept():
    tokenizer, tokens = read(BOM + "--#SET TERMINATOR @\nVALUES 1@\n")
    assert tokenizer.terminator_script.origin == 1
    assert tokenizer.sql.startswith("--#SET") and comments(tokenizer) == ["--#SET TERMINATOR @"]
    assert read("VALUES 1;")[0].terminator_script.origin == 0
    kept = replace(DB2_SPEC, leading_bom_is_blank=False)
    assert read(BOM + "VALUES 1;", kept)[0].terminator_script.origin == 0


def test_line_pass_results_are_exposed_to_the_assembly():
    tokenizer, _ = read("--#SET TERMINATOR @\nVALUES 1@\nVALUES 2;\n")
    assert [ln.kind for ln in tokenizer.terminator_script.lines] == ["directive", "code", "code"]
    assert tokenizer.terminator_script.malformed is None
    assert read("--#SET TERMINATOR\nx")[0].terminator_script.malformed == 1


@pytest.mark.parametrize(
    "terminator, script, lexemes",
    [
        ("--", "VALUES 1 --\nVALUES 2\n", 1),
        ("/*", "VALUES 1 /*\nVALUES 2\n", 1),
    ],
)
def test_masked_terminators_do_not_open_lexemes(terminator, script, lexemes):
    tokenizer, tokens = read(f"--#SET TERMINATOR {terminator}\n{script}")
    assert len(tokenizer.comments) == lexemes  # only the directive line is a comment
    assert tokenizer.open_lexeme == -1
    assert [t.text for t in tokens if t.type == TokenType.KEYWORD] == ["VALUES", "VALUES"]


def test_masked_quote_terminators_leave_the_line_open_not_closed():
    _, tokens = read("--#SET TERMINATOR '\nVALUES 'a'\nVALUES 2\n")
    assert [(t.type.name, t.text) for t in tokens if t.type == TokenType.STRING] == [
        ("STRING", "'a \nVALUES 2\n")
    ]
    _, tokens = read('--#SET TERMINATOR "\nVALUES "a"\nVALUES 2\n')
    assert [(t.type.name, t.text) for t in tokens if t.type == TokenType.IDENTIFIER] == [
        ("IDENTIFIER", '"a \nVALUES 2\n')
    ]


def test_masked_comment_closer_leaves_the_comment_open():
    tokenizer, _ = read("--#SET TERMINATOR */\nVALUES 1 /* a\nb */\n")
    assert tokenizer.open_lexeme >= 0


# --- the shared block comment reader ---------------------------------------------------------------------


def block(text: str, stops: Tuple[int, ...] = (), first: int = 0, spec: LexicalSpec = PLAIN_NESTED):
    tokenizer = LexicalTokenizer(text, spec=spec)
    tokenizer.read(2)  # the caller has just read the opener
    marks: dict = {}
    result = tokenizer._read_block_comment(stops, first, marks)
    return result, marks, tokenizer.pos


def test_comment_marks_at_stops():
    text = "/* a\n/* b;\n*/ c;\n*/ x"
    (depth, nxt), marks, end = block(text, (text.index(";"), text.index(";", 12)))
    assert (depth, nxt) == (0, 2) and end == len("/* a\n/* b;\n*/ c;\n*/")
    assert marks == {9: (2, True), 15: (1, True)}


def test_the_character_before_an_opener_s_second_character_is_not_read_alone():
    (_, _), marks, _ = block("/*/ x", (2,))
    assert marks == {2: (1, False)}
    (_, _), marks, _ = block("/* /*/ x", (5,))
    assert marks == {5: (2, False)}
    (_, _), marks, _ = block("/* ** x", (5,))
    assert marks == {5: (1, True)}


def test_a_closer_that_reaches_depth_zero_at_a_stop_still_stores_a_mark():
    (depth, nxt), marks, end = block("/* a */ x", (7,))
    assert (depth, nxt, end) == (0, 1, 7) and marks == {7: (0, False)}


def test_stops_after_the_end_of_an_unterminated_comment_are_not_marked():
    (depth, nxt), marks, _ = block("/* a\n b", (3, 100))
    assert (depth, nxt) == (1, 1) and marks == {3: (1, True)}


def test_stops_before_first_are_left_alone():
    (depth, nxt), marks, _ = block("/* a; b; c */", (0, 4, 7), first=1)
    assert nxt == 3 and marks == {4: (1, True), 7: (1, True)} and depth == 0


def test_without_stops_nothing_is_recorded():
    (depth, nxt), marks, end = block("/* a /* b */ c */ d")
    assert (depth, nxt, marks, end) == (0, 0, {}, len("/* a /* b */ c */"))


def test_non_nested_dialects_close_at_the_first_closer():
    (depth, _), _, end = block(
        "/* a /* b */ c */ d", spec=LexicalSpec(name="flat", text_blanks=" ")
    )
    assert (depth, end) == (0, len("/* a /* b */"))


# --- the comment handler the other dialects use is untouched ---------------------------------------------

NESTING = [POSTGRESQL_SPEC]
FLAT = [SQLSERVER_SPEC, ORACLE_SPEC, SQLITE_SPEC, MYSQL_SPEC, MARIADB_SPEC]


def test_handle_comment_is_unchanged():
    assert list(inspect.signature(BaseTokenizer._handle_comment).parameters) == ["self"]
    assert list(inspect.signature(LexicalTokenizer._handle_comment).parameters) == ["self"]
    script = "SELECT 1 /* a /* b */ c */ ; /* d */ SELECT 2"
    for spec in NESTING:
        tokenizer = LexicalTokenizer(script, spec=spec)
        tokenizer.tokenize()
        assert tokenizer.comments == [(9, 26), (29, 36)], spec.name
    for spec in FLAT:
        tokenizer = LexicalTokenizer(script, spec=spec)
        tokenizer.tokenize()
        assert tokenizer.comments == [(9, 21), (29, 36)], spec.name


def test_handle_comment_still_refuses_an_unterminated_comment():
    for spec in NESTING + FLAT:
        with pytest.raises(UnsafeStatementSplitError) as error:
            LexicalTokenizer("SELECT 1 /* open", spec=spec).tokenize()
        assert (
            str(error.value) == "unterminated block comment opened at line 1, column 10"
        ), spec.name
    with pytest.raises(UnsafeStatementSplitError):
        LexicalTokenizer("SELECT 1 /* a /* b */ c", spec=POSTGRESQL_SPEC).tokenize()
    LexicalTokenizer("SELECT 1 /* a /* b */ c", spec=ORACLE_SPEC).tokenize()


def test_marks_are_stored_only_at_line_ends_that_fall_in_or_end_a_comment():
    script = "VALUES 1;\n/* a\nb;\n*/ c;\n/* d\n*/;\n"
    tokenizer, _ = read(script)
    inside = script.index("b;") + 1
    closing = script.rindex("*/;") + 2
    assert tokenizer.marks == {inside: (1, True), closing: (0, False)}
