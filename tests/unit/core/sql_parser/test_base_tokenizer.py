"""Tests for BaseTokenizer — streaming character-by-character SQL tokenizer."""

import warnings

import pytest

from core.sql_parser.base_tokenizer import BaseTokenizer, TokenizerWarning
from core.sql_parser.tokens import Token, TokenType

# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstructor:
    def test_initial_state(self):
        t = BaseTokenizer("SELECT 1")
        assert t.sql == "SELECT 1"
        assert t.pos == 0
        assert t.line == 1
        assert t.col == 1
        assert t.parens_depth == 0

    def test_empty_sql(self):
        t = BaseTokenizer("")
        assert t.sql == ""
        assert t.pos == 0


# ---------------------------------------------------------------------------
# peek / read
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPeekRead:
    def test_peek_single_char(self):
        t = BaseTokenizer("ABC")
        assert t.peek() == "A"
        assert t.pos == 0  # not consumed

    def test_peek_multiple_chars(self):
        t = BaseTokenizer("ABCDEF")
        assert t.peek(3) == "ABC"
        assert t.pos == 0

    def test_peek_beyond_end(self):
        t = BaseTokenizer("AB")
        assert t.peek(5) == "AB"

    def test_read_single_char(self):
        t = BaseTokenizer("ABC")
        assert t.read() == "A"
        assert t.pos == 1
        assert t.col == 2

    def test_read_multiple_chars(self):
        t = BaseTokenizer("ABCDEF")
        assert t.read(3) == "ABC"
        assert t.pos == 3

    def test_read_newline_tracking(self):
        t = BaseTokenizer("A\nB")
        t.read()  # A -> line=1, col=2
        t.read()  # \n -> line=2, col=1
        assert t.line == 2
        assert t.col == 1
        t.read()  # B -> line=2, col=2
        assert t.line == 2
        assert t.col == 2

    def test_read_multiple_newlines(self):
        t = BaseTokenizer("A\n\nB")
        t.read(3)  # A \n \n
        assert t.line == 3
        assert t.col == 1


# ---------------------------------------------------------------------------
# _skip_whitespace
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkipWhitespace:
    def test_skips_spaces(self):
        t = BaseTokenizer("   X")
        t._skip_whitespace()
        assert t.peek() == "X"

    def test_skips_tabs_and_newlines(self):
        t = BaseTokenizer("\t\n  Y")
        t._skip_whitespace()
        assert t.peek() == "Y"

    def test_noop_on_non_whitespace(self):
        t = BaseTokenizer("Z")
        t._skip_whitespace()
        assert t.pos == 0


# ---------------------------------------------------------------------------
# Boolean checks
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBooleanChecks:
    def test_is_comment_start_single_line(self):
        t = BaseTokenizer("-- comment")
        assert t._is_comment_start() is True

    def test_is_comment_start_multi_line(self):
        t = BaseTokenizer("/* comment */")
        assert t._is_comment_start() is True

    def test_is_comment_start_false(self):
        t = BaseTokenizer("SELECT")
        assert t._is_comment_start() is False

    def test_is_string_start(self):
        t = BaseTokenizer("'hello'")
        assert t._is_string_start() is True

    def test_is_string_start_false(self):
        t = BaseTokenizer("hello")
        assert t._is_string_start() is False

    def test_is_alternative_string_start_base(self):
        t = BaseTokenizer("q'[text]'")
        assert t._is_alternative_string_start() is False

    def test_is_delimiter_start(self):
        t = BaseTokenizer(";")
        assert t._is_delimiter_start() is True

    def test_is_delimiter_start_false(self):
        t = BaseTokenizer("X")
        assert t._is_delimiter_start() is False

    def test_is_keyword_start_alpha(self):
        t = BaseTokenizer("S")
        assert t._is_keyword_start() is True

    def test_is_keyword_start_underscore(self):
        t = BaseTokenizer("_var")
        assert t._is_keyword_start() is True

    def test_is_keyword_start_digit(self):
        t = BaseTokenizer("9")
        assert t._is_keyword_start() is False

    def test_is_symbol_all_symbols(self):
        t = BaseTokenizer("")
        # Punctuation, plus every character SQL engines build operator names
        # from: modulo/bitwise (% & ^ #) and the jsonb/hstore family (@ ? #).
        for ch in "().,+-*/<>=![]{}:|~%&^#@?":
            assert t._is_symbol(ch) is True

    def test_is_symbol_letter(self):
        t = BaseTokenizer("")
        assert t._is_symbol("a") is False

    def test_is_symbol_digit(self):
        t = BaseTokenizer("")
        assert t._is_symbol("5") is False


# ---------------------------------------------------------------------------
# _handle_number
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleNumber:
    def test_integer(self):
        tokens = BaseTokenizer("42").tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].text == "42"

    def test_decimal(self):
        tokens = BaseTokenizer("3.14").tokenize()
        assert tokens[0].text == "3.14"

    def test_scientific_notation(self):
        tokens = BaseTokenizer("1E10").tokenize()
        assert tokens[0].text == "1E10"

    def test_scientific_negative_exponent(self):
        tokens = BaseTokenizer("1E-5").tokenize()
        assert tokens[0].text == "1E-5"

    def test_scientific_positive_exponent(self):
        tokens = BaseTokenizer("2E+3").tokenize()
        assert tokens[0].text == "2E+3"


# ---------------------------------------------------------------------------
# _handle_comment
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleComment:
    def test_single_line_comment(self):
        tokens = BaseTokenizer("-- comment\nSELECT").tokenize()
        assert tokens[0].type == TokenType.COMMENT
        assert tokens[1].type == TokenType.KEYWORD
        assert tokens[1].text == "SELECT"

    def test_multi_line_comment(self):
        tokens = BaseTokenizer("/* multi\nline */").tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.COMMENT

    def test_comment_only(self):
        tokens = BaseTokenizer("-- just a comment").tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.COMMENT


# ---------------------------------------------------------------------------
# _handle_string
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleString:
    def test_simple_string(self):
        tokens = BaseTokenizer("'hello'").tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].text == "'hello'"

    def test_escaped_quotes(self):
        tokens = BaseTokenizer("'O''Reilly'").tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].text == "'O''Reilly'"

    def test_empty_string(self):
        tokens = BaseTokenizer("''").tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].text == "''"


# ---------------------------------------------------------------------------
# _handle_delimiter
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleDelimiter:
    def test_semicolon(self):
        tokens = BaseTokenizer(";").tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.DELIMITER
        assert tokens[0].text == ";"

    def test_two_statements(self):
        tokens = BaseTokenizer("SELECT 1; SELECT 2").tokenize()
        delims = [t for t in tokens if t.type == TokenType.DELIMITER]
        assert len(delims) == 1  # one ; between the two


# ---------------------------------------------------------------------------
# _handle_symbol / parens depth
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleSymbol:
    def test_simple_symbols(self):
        tokens = BaseTokenizer("(a + b)").tokenize()
        types = [(t.type, t.text) for t in tokens]
        assert types[0] == (TokenType.SYMBOL, "(")
        assert types[1] == (TokenType.IDENTIFIER, "a")
        assert types[2] == (TokenType.SYMBOL, "+")
        assert types[3] == (TokenType.IDENTIFIER, "b")
        assert types[4] == (TokenType.SYMBOL, ")")

    def test_parens_depth_increment(self):
        tokens = BaseTokenizer("(a (b))").tokenize()
        open1 = tokens[0]  # (
        open2 = tokens[2]  # (
        close1 = tokens[4]  # )
        close2 = tokens[5]  # )
        assert open1.parens_depth == 1
        assert open2.parens_depth == 2
        assert close1.parens_depth == 1
        assert close2.parens_depth == 0

    def test_parens_depth_floor_at_zero(self):
        t = BaseTokenizer(")")
        tokens = t.tokenize()
        assert tokens[0].parens_depth == 0
        assert t.parens_depth == 0


# ---------------------------------------------------------------------------
# _handle_keyword
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleKeyword:
    def test_keyword_recognized(self):
        tokens = BaseTokenizer("SELECT").tokenize()
        assert tokens[0].type == TokenType.KEYWORD
        assert tokens[0].text == "SELECT"

    def test_identifier(self):
        tokens = BaseTokenizer("username").tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].text == "username"

    def test_keyword_case_insensitive(self):
        tokens = BaseTokenizer("select").tokenize()
        assert tokens[0].type == TokenType.KEYWORD

    def test_identifier_with_special_chars(self):
        tokens = BaseTokenizer("my$var#1").tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].text == "my$var#1"

    def test_multiple_keywords(self):
        tokens = BaseTokenizer("CREATE TABLE").tokenize()
        assert tokens[0].type == TokenType.KEYWORD
        assert tokens[0].text == "CREATE"
        assert tokens[1].type == TokenType.KEYWORD
        assert tokens[1].text == "TABLE"


# ---------------------------------------------------------------------------
# _read_until
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReadUntil:
    def test_reads_until_target(self):
        t = BaseTokenizer("abcXYZend")
        result = t._read_until("XYZ")
        assert result == "abc"
        assert t.peek(3) == "XYZ"

    def test_reads_to_end_if_no_target(self):
        t = BaseTokenizer("abcdef")
        result = t._read_until("ZZZ")
        assert result == "abcdef"
        assert t.pos == len(t.sql)


# ---------------------------------------------------------------------------
# Full tokenization scenarios
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFullTokenization:
    def test_select_star_from_users(self):
        tokens = BaseTokenizer("SELECT * FROM users").tokenize()
        expected = [
            (TokenType.KEYWORD, "SELECT"),
            (TokenType.SYMBOL, "*"),
            (TokenType.KEYWORD, "FROM"),
            (TokenType.IDENTIFIER, "users"),
        ]
        result = [(t.type, t.text) for t in tokens]
        assert result == expected

    def test_empty_sql(self):
        tokens = BaseTokenizer("").tokenize()
        assert tokens == []

    def test_whitespace_only(self):
        tokens = BaseTokenizer("   \t\n  ").tokenize()
        # Only an EOF token may appear, filter it out
        non_eof = [t for t in tokens if t.type != TokenType.EOF]
        assert non_eof == []

    def test_line_col_tracking(self):
        tokens = BaseTokenizer("A\nB").tokenize()
        assert tokens[0].line == 1
        assert tokens[0].col == 1
        assert tokens[1].line == 2
        assert tokens[1].col == 1

    def test_at_sign_is_a_symbol(self):
        # '@' opens PostgreSQL's jsonb operators (@>, @@) and Oracle db links.
        # It used to reach _handle_unknown_char and be deleted.
        tokens = BaseTokenizer("@SELECT").tokenize()
        assert [(t.type, t.text) for t in tokens] == [
            (TokenType.SYMBOL, "@"),
            (TokenType.KEYWORD, "SELECT"),
        ]

    def test_unclaimed_character_is_passed_through(self):
        # No rule claims '\'. It must still reach the token stream: that stream
        # is reserialized into the SQL that actually gets executed, so dropping
        # a character silently rewrites the user's statement.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", TokenizerWarning)
            tokens = BaseTokenizer("\\SELECT").tokenize()
        assert [(t.type, t.text) for t in tokens] == [
            (TokenType.SYMBOL, "\\"),
            (TokenType.KEYWORD, "SELECT"),
        ]

    def test_complex_sql(self):
        sql = "SELECT a, b FROM t WHERE a = 'x' AND b > 1; -- done"
        tokens = BaseTokenizer(sql).tokenize()
        types = [t.type for t in tokens]
        assert TokenType.KEYWORD in types
        assert TokenType.STRING in types
        assert TokenType.DELIMITER in types
        assert TokenType.COMMENT in types
        assert TokenType.SYMBOL in types
        assert TokenType.IDENTIFIER in types
