"""How the shared tokenizer reads the lexemes of a mysql or mariadb client script."""

from dataclasses import replace
from typing import List, Tuple

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_RULES, MYSQL_SPEC
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC

BOTH = pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
MYSQL_ONLY_HINTS = replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, hint_opener="/*#"))


def read(script: str, spec: LexicalSpec = MYSQL_SPEC) -> Tuple[LexicalTokenizer, List[Token]]:
    tokenizer = LexicalTokenizer(script, spec=spec)
    return tokenizer, tokenizer.tokenize()


def texts(tokens: List[Token], *types: TokenType) -> List[str]:
    return [t.text for t in tokens if t.type in types]


def code(tokens: List[Token]) -> List[str]:
    return [t.text for t in tokens if t.type not in (TokenType.COMMENT, TokenType.EOF)]


def comments(tokenizer: LexicalTokenizer) -> List[str]:
    return [tokenizer.sql[start:end] for start, end in tokenizer.comments]


def delimiters(tokens: List[Token]) -> int:
    return sum(1 for t in tokens if t.type == TokenType.DELIMITER)


def refusal(script: str, spec: LexicalSpec, error: type = UnsafeStatementSplitError) -> str:
    with pytest.raises(error) as caught:
        read(script, spec)
    return str(caught.value)


@BOTH
def test_double_quoted_strings_take_backslash_escapes(spec):
    _, tokens = read('SELECT "a\\"b;c" x', spec)
    assert texts(tokens, TokenType.STRING) == ['"a\\"b;c"']
    assert delimiters(tokens) == 0


@BOTH
@pytest.mark.parametrize(
    "script, type_, pieces, joined",
    [
        ("SELECT 'a''b'", TokenType.STRING, ["'a'", "'b'"], "'a''b'"),
        ('SELECT "a""b"', TokenType.STRING, ['"a"', '"b"'], '"a""b"'),
        ("SELECT `a``b`", TokenType.IDENTIFIER, ["`a`", "`b`"], "`a``b`"),
    ],
)
def test_doubled_quotes_close_and_reopen(spec, script, type_, pieces, joined):
    assert texts(read(script, spec)[1], type_) == pieces
    varied = replace(spec, string_quote_doubling=True, quoted_identifier_escape=True)
    assert texts(read(script, varied)[1], type_) == [joined]


def test_each_doubling_field_is_read_on_its_own():
    strings = replace(MYSQL_SPEC, string_quote_doubling=True)
    assert texts(read("SELECT `a``b`, 'a''b'", strings)[1], TokenType.IDENTIFIER) == ["`a`", "`b`"]
    assert texts(read("SELECT `a``b`, 'a''b'", strings)[1], TokenType.STRING) == ["'a''b'"]
    names = replace(MYSQL_SPEC, quoted_identifier_escape=True)
    assert texts(read("SELECT `a``b`, 'a''b'", names)[1], TokenType.IDENTIFIER) == ["`a``b`"]
    assert texts(read("SELECT `a``b`, 'a''b'", names)[1], TokenType.STRING) == ["'a'", "'b'"]


def test_escape_string_keeps_postgres():
    for script, expected in [("SELECT E'a\\'b'", "E'a\\'b'"), ("SELECT E'a''b'", "E'a''b'")]:
        assert texts(read(script, POSTGRESQL_SPEC)[1], TokenType.STRING) == [expected]


@BOTH
def test_backticks_have_no_backslash_escape(spec):
    _, tokens = read("SELECT 1 AS `a\\`; SELECT 2;", spec)
    assert texts(tokens, TokenType.IDENTIFIER) == ["`a\\`"]
    assert delimiters(tokens) == 2


@BOTH
@pytest.mark.parametrize(
    "script, spans, delimiter_count",
    [
        ("SELECT 1 # c ; x\n;", ["# c ; x"], 1),
        ("SELECT 1 -- c;\n;", ["-- c;"], 1),
        ("SELECT 1 --\tc;\n;", ["--\tc;"], 1),
        ("SELECT 1 --\x0bc;\n;", ["--\x0bc;"], 1),
        ("SELECT 1 --\n+ 1;", ["--"], 1),
        ("SELECT 1 --c\n;", [], 1),
        ("SELECT 1--1;", [], 1),
        ("SELECT 1 --\xa0c;\n;", [], 2),
        ("SELECT 1 --", ["--"], 0),
        ("SELECT 1 #", ["#"], 0),
        ("SELECT a#; x\nFROM t;", ["#; x"], 1),
    ],
)
def test_hash_and_dash_comments(spec, script, spans, delimiter_count):
    tokenizer, tokens = read(script, spec)
    assert comments(tokenizer) == spans
    assert delimiters(tokens) == delimiter_count


def test_comment_openers_are_read_from_the_rules():
    percent = replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, hash_comment="%"))
    tokenizer, tokens = read("SELECT 1 % c ; x\n; # y ;", percent)
    assert comments(tokenizer) == ["% c ; x"]
    assert delimiters(tokens) == 2
    slashes = replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, dash_comment="//"))
    tokenizer, tokens = read("SELECT 1 // c ;\n; -- y ;", slashes)
    assert comments(tokenizer) == ["// c ;"]
    assert delimiters(tokens) == 2


@BOTH
@pytest.mark.parametrize("comment", ["# a\rb", "-- a\rb"])
def test_line_comment_with_a_lone_cr_is_refused(spec, comment):
    expected = (
        "comment on line 1 holds a carriage return that is not part of a line end: the "
        f"{spec.client_name} client reads the rest of the script as part of the comment and "
        "drops the statements in it"
    )
    assert refusal(f"SELECT 1 {comment}\n;", spec) == expected
    assert "on line 2" in refusal(f"SELECT 1;\n{comment}\n;", spec)
    read(comment.replace("\r", "\r\n") + "\n;", spec)  # a CRLF pair is a line end


@pytest.mark.parametrize(
    "spec, script, spans, words",
    [
        (MYSQL_SPEC, "SELECT /*! 2 */ x;", [], ["SELECT", "/*!", "2", "*/", "x", ";"]),
        (
            MYSQL_SPEC,
            "SELECT /*!50700 +1 */ x;",
            [],
            ["SELECT", "/*!", "50700", "+", "1", "*/", "x", ";"],
        ),
        (
            MARIADB_SPEC,
            "SELECT /*M!100500 +1 */ x;",
            [],
            ["SELECT", "/*M!", "100500", "+", "1", "*/", "x", ";"],
        ),
        (MYSQL_SPEC, "SELECT /*M!100500 +1 */ x;", ["/*M!100500 +1 */"], ["SELECT", "x", ";"]),
        (MYSQL_SPEC, "SELECT 1 */ 2;", [], ["SELECT", "1", "*", "/", "2", ";"]),
    ],
    ids=["mysql", "versioned", "mariadb", "mysql-reads-M-as-comment", "closer-outside-comment"],
)
def test_executable_comment_is_code(spec, script, spans, words):
    tokenizer, tokens = read(script, spec)
    assert comments(tokenizer) == spans
    assert code(tokens) == words


def test_executable_openers_are_read_from_the_rules():
    wider = replace(
        MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, executable_openers=("/*!", "/*M!"))
    )
    tokenizer, tokens = read("SELECT /*M!1 x */ y;", wider)
    assert comments(tokenizer) == []
    assert code(tokens) == ["SELECT", "/*M!", "1", "x", "*/", "y", ";"]
    narrower = replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, executable_openers=()))
    tokenizer, _ = read("SELECT /*! x */ y;", narrower)
    assert comments(tokenizer) == ["/*! x */"]


@BOTH
def test_comment_inside_an_executable_comment_is_refused(spec):
    expected = f"comment opens inside an executable comment on line 1: the {spec.client_name} client misreads it"
    assert refusal("SELECT 1 /*! , /* c */ 2 */ AS a;", spec) == expected
    assert refusal("SELECT /*! a /* b */ c */;", spec) == expected
    assert "on line 2" in refusal("SELECT 1;\nSELECT /*! a /*+ b */ c */;", spec)
    # the flag belongs to its line: a comment on the next line is a comment
    tokenizer, tokens = read("SELECT /*! x\n/* y */ */ 1;", spec)
    assert comments(tokenizer) == ["/* y */"]
    assert delimiters(tokens) == 1


@BOTH
@pytest.mark.parametrize("lexeme", ["'a\nb'", "`a\nb`"])
def test_a_lexeme_spanning_lines_ends_the_executable_comment_flag(spec, lexeme):
    tokenizer, tokens = read(f"SELECT /*! {lexeme} /* c */ 1 */;", spec)
    assert comments(tokenizer) == ["/* c */"]
    assert delimiters(tokens) == 1
    assert "executable comment" in refusal("SELECT /*! 'a' /* c */ 1 */;", spec)


@BOTH
def test_each_comment_ends_at_its_own_line(spec):
    tokenizer, tokens = read("SELECT 1 # a\nSELECT 2 # b\n;\nSELECT /*+ x */ 3 -- c\n;", spec)
    assert comments(tokenizer) == ["# a", "# b", "/*+ x */", "-- c"]
    assert delimiters(tokens) == 2
    tokenizer, _ = read("# a\n# b\n# c", MYSQL_SPEC)
    assert comments(tokenizer) == ["# a", "# b", "# c"]


HINT_ROWS = [
    # script, mysql comment spans, mariadb comment spans, mysql delimiters, mariadb delimiters
    ("SELECT 1 /*+ ; */ + 1; SELECT 2;", ["/*+ ; */"], ["/*+ ; */"], 2, 2),
    (
        "SELECT /*+\n NO_BKA(t1) ;\n*/ 1 AS a;\nSELECT 2 AS b;",
        ["/*+"],
        ["/*+\n NO_BKA(t1) ;\n*/"],
        3,
        2,
    ),
    (
        "SELECT /*+\n NO_BKA(t1)\n*/ 1 AS a;\nSELECT 2 AS b;",
        ["/*+"],
        ["/*+\n NO_BKA(t1)\n*/"],
        2,
        2,
    ),
    (
        "SELECT /*+ ;\n NO_BKA(t1) */ 1 AS a;\nSELECT 2 AS b;",
        ["/*+ ;"],
        ["/*+ ;\n NO_BKA(t1) */"],
        2,
        2,
    ),
]


@pytest.mark.parametrize(
    "script, mysql_spans, mariadb_spans, mysql_count, mariadb_count", HINT_ROWS
)
def test_hint_reading_per_dialect(script, mysql_spans, mariadb_spans, mysql_count, mariadb_count):
    tokenizer, tokens = read(script, MYSQL_SPEC)
    assert (comments(tokenizer), delimiters(tokens)) == (mysql_spans, mysql_count)
    tokenizer, tokens = read(script, MARIADB_SPEC)
    assert (comments(tokenizer), delimiters(tokens)) == (mariadb_spans, mariadb_count)
    # the same client rules with the other reading of a hint give the other result
    as_block = replace(
        MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, hint_opening_line_only=False)
    )
    tokenizer, tokens = read(script, as_block)
    assert (comments(tokenizer), delimiters(tokens)) == (mariadb_spans, mariadb_count)
    as_hint = replace(
        MARIADB_SPEC,
        delimiter_script=replace(MARIADB_SPEC.delimiter_script, hint_opening_line_only=True),
    )
    tokenizer, tokens = read(script, as_hint)
    assert (comments(tokenizer), delimiters(tokens)) == (mysql_spans, mysql_count)


def test_the_hint_closer_after_the_opening_line_is_code():
    _, tokens = read("SELECT /*+\n NO_BKA(t1)\n*/ 1 AS a;", MYSQL_SPEC)
    assert code(tokens) == ["SELECT", "NO_BKA", "(", "t1", ")", "*/", "1", "AS", "a", ";"]


def test_hint_opener_is_read_from_the_rules():
    script = "SELECT /*+ x ;\n y */ 1;"
    tokenizer, tokens = read(script, MYSQL_ONLY_HINTS)
    assert comments(tokenizer) == ["/*+ x ;\n y */"]
    assert delimiters(tokens) == 1
    tokenizer, tokens = read("SELECT /*# x ;\n y */ 1;", MYSQL_ONLY_HINTS)
    assert comments(tokenizer) == ["/*# x ;"]
    assert delimiters(tokens) == 1


def test_backslash_in_a_hint_opening_line():
    expected = "backslash inside an optimizer hint on line 1: the mysql client runs it as a command"
    assert refusal("SELECT /*+ a \\ b */ 1;", MYSQL_SPEC, UnsupportedMetaCommandError) == expected
    assert refusal("SELECT /*+ a \\ b", MYSQL_SPEC, UnsupportedMetaCommandError) == expected
    tokenizer, _ = read("SELECT /*+ a \\ b */ 1;", MARIADB_SPEC)
    assert comments(tokenizer) == ["/*+ a \\ b */"]


def test_open_hint_refusal_precedes_block_comment():
    hint = "unterminated optimizer hint starting at line 1, column 8"
    assert refusal("SELECT /*+ x\n/* y", MYSQL_SPEC) == hint
    assert refusal("SELECT /*+ x", MYSQL_SPEC) == hint
    assert (
        refusal("SELECT /*+ x\n/* y", MARIADB_SPEC)
        == "unterminated block comment opened at line 1, column 8"
    )
    assert (
        refusal("SELECT /*+ x", MARIADB_SPEC)
        == "unterminated block comment opened at line 1, column 8"
    )
    # an unterminated literal after the hint is met first, as the old end-of-script order has it
    assert (
        refusal("SELECT /*+ x\n'abc", MYSQL_SPEC)
        == "unterminated string opened at line 2, column 1"
    )
    assert (
        refusal('SELECT /*+ x\n"abc', MYSQL_SPEC)
        == "unterminated string opened at line 2, column 1"
    )
    assert (
        refusal("SELECT /*+ x\n`abc", MYSQL_SPEC)
        == "unterminated quoted identifier opened at line 2, column 1"
    )
    # a closed hint raises nothing; a closed block comment does not close an open hint
    read("SELECT /*+ x\n*/ 1;", MYSQL_SPEC)
    assert refusal("SELECT /*+ x\n/* y */", MYSQL_SPEC) == hint


@BOTH
@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 'abc", "unterminated string opened at line 1, column 8"),
        ('SELECT "abc', "unterminated string opened at line 1, column 8"),
        ("SELECT `abc", "unterminated quoted identifier opened at line 1, column 8"),
        ("SELECT /* x", "unterminated block comment opened at line 1, column 8"),
        ("SELECT 'a''b", "unterminated string opened at line 1, column 11"),
        ('SELECT "a""b', "unterminated string opened at line 1, column 11"),
        ("SELECT 1 AS `a``b", "unterminated quoted identifier opened at line 1, column 16"),
        ("SELECT 'a\\'", "unterminated string opened at line 1, column 8"),
        ("SELECT 1;\nSELECT\n  'x", "unterminated string opened at line 3, column 3"),
    ],
)
def test_unterminated_lexemes_at_eof(spec, script, expected):
    assert refusal(script, spec) == expected


@BOTH
@pytest.mark.parametrize(
    "script, line",
    [
        ("SELECT 1\x00;", 1),
        ("SELECT 'abc\x00", 1),
        ("a\nb\r\nSELECT 'x\x00", 3),
        ("SELECT /* x\x00", 1),
    ],
)
def test_nul_is_refused_before_anything(spec, script, line):
    expected = f"NUL byte on line {line}: the {spec.client_name} client refuses it unless --binary-mode is set"
    assert refusal(script, spec) == expected


@BOTH
def test_crlf_is_read_as_lf(spec):
    tokenizer, tokens = read("SELECT 1;\r\nSELECT 'a\r\nb';\r\n", spec)
    assert tokenizer.sql == "SELECT 1;\nSELECT 'a\nb';\n"
    assert texts(tokens, TokenType.STRING) == ["'a\nb'"]
    assert tokenizer.delimiter_script.removed == [9, 19, 23]
    lone, _ = read("SELECT 1;\rSELECT 2;", spec)
    assert lone.sql == "SELECT 1;\rSELECT 2;"
    assert lone.delimiter_script.removed == []


@BOTH
def test_bom_columns(spec):
    assert refusal("\ufeffSELECT 'a", spec) == "unterminated string opened at line 1, column 8"
    assert (
        refusal("\ufeffSELECT 1;\nSELECT 'a", spec)
        == "unterminated string opened at line 2, column 8"
    )
    assert texts(read("\ufeffSELECT 'a'", spec)[1], TokenType.STRING) == ["'a'"]


def test_backslash_outside_lexemes_consumes_the_next_character():
    tokenizer, tokens = read("SELECT \\' x;", MYSQL_SPEC)
    assert texts(tokens, TokenType.STRING) == []
    assert code(tokens) == ["SELECT", "\\'", "x", ";"]
    tilde = replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, escape="~"))
    assert code(read("SELECT ~' x;", tilde)[1]) == ["SELECT", "~'", "x", ";"]
    assert refusal("SELECT \\' x;", tilde) == "unterminated string opened at line 1, column 9"


def test_string_quotes_and_blanks_and_word_part_are_read_from_the_rules():
    single = replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, string_quotes="'"))
    assert texts(read('SELECT "a;b" x;', MYSQL_SPEC)[1], TokenType.STRING) == ['"a;b"']
    tokens = read('SELECT "a;b" x;', single)[1]
    assert texts(tokens, TokenType.STRING) == []
    assert delimiters(tokens) == 2
    tabs = replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, blanks=" \t"))
    assert code(read("SELECT\x0b1;", MYSQL_SPEC)[1]) == ["SELECT", "1", ";"]
    assert code(read("SELECT\x0b1;", tabs)[1]) == ["SELECT", "\x0b", "1", ";"]
    narrow = replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, word_part="A-Za-z0-9_"))
    assert code(read("SELECT a$b\xa0c;", MYSQL_SPEC)[1]) == ["SELECT", "a$b\xa0c", ";"]
    assert code(read("SELECT a$b\xa0c;", narrow)[1]) == ["SELECT", "a", "$", "b", "\xa0", "c", ";"]


def test_three_client_rules_are_exclusive():
    assert ORACLE_SPEC.client_script is not None and SQLSERVER_SPEC.batch_script is not None
    with pytest.raises(ValueError):
        replace(ORACLE_SPEC, delimiter_script=MYSQL_RULES)
    with pytest.raises(ValueError):
        replace(SQLSERVER_SPEC, delimiter_script=MYSQL_RULES)
    with pytest.raises(ValueError):
        replace(ORACLE_SPEC, batch_script=SQLSERVER_SPEC.batch_script)
    assert replace(MYSQL_SPEC, delimiter_script=MYSQL_RULES) == MYSQL_SPEC


def test_a_later_hint_replaces_an_open_hint():
    tokenizer, tokens = read("SELECT /*+ a\n/*+ b */ 1;\nSELECT 2;", MYSQL_SPEC)
    assert comments(tokenizer) == ["/*+ a", "/*+ b */"]
    assert delimiters(tokens) == 2
    read("SELECT /*+ a\n/*+ b */ 1;", MYSQL_SPEC)
    # a later hint that stays open replaces the earlier one: the refusal names the later line
    assert refusal("SELECT /*+ x\nSELECT /*+ y\n1", MYSQL_SPEC) == (
        "unterminated optimizer hint starting at line 2, column 8"
    )
    assert refusal("SELECT /*+ x\n/*! 1 */\n;", MYSQL_SPEC) == (
        "unterminated optimizer hint starting at line 1, column 8"
    )


@BOTH
def test_a_string_closes_only_on_its_own_quote(spec):
    for script in ['SELECT "a\'b;" AS x; SELECT 2;', "SELECT 'a\"b;' AS x; SELECT 2;"]:
        tokens = read(script, spec)[1]
        assert len(texts(tokens, TokenType.STRING)) == 1
        assert delimiters(tokens) == 2


def test_a_backslash_after_a_closed_hint_is_not_in_the_hint():
    tokenizer, tokens = read("SELECT /*+ a */ \\N AS x; SELECT 2;", MYSQL_SPEC)
    assert comments(tokenizer) == ["/*+ a */"]
    assert delimiters(tokens) == 2


def test_the_nul_line_ignores_lone_carriage_returns():
    expected = "NUL byte on line 1: the mysql client refuses it unless --binary-mode is set"
    assert refusal("SELECT 1;\rSELECT 2\x00;", MYSQL_SPEC) == expected
