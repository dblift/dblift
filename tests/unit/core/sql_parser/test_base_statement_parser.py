"""Tests for BaseStatementParser — token-based SQL statement splitting."""

import pytest

from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.tokens import Token, TokenType


def make_token(type, text, pos=0, line=1, col=1, parens_depth=0):
    return Token(type=type, text=text, pos=pos, line=line, col=col, parens_depth=parens_depth)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstructor:

    def test_stores_tokens(self):
        tokens = [make_token(TokenType.KEYWORD, "SELECT")]
        parser = BaseStatementParser(tokens)
        assert parser.tokens is tokens

    def test_creates_context_when_none(self):
        parser = BaseStatementParser([])
        assert isinstance(parser.context, ParserContext)

    def test_uses_provided_context(self):
        ctx = ParserContext(delimiter="/")
        parser = BaseStatementParser([], context=ctx)
        assert parser.context is ctx
        assert parser.context.delimiter == "/"

    def test_current_idx_starts_at_zero(self):
        parser = BaseStatementParser([])
        assert parser.current_idx == 0


# ---------------------------------------------------------------------------
# split_statements
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSplitStatements:

    def test_simple_two_statements(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "1"),
            make_token(TokenType.DELIMITER, ";"),
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "2"),
            make_token(TokenType.DELIMITER, ";"),
        ]
        result = BaseStatementParser(tokens).split_statements()
        assert result == ["SELECT 1;", "SELECT 2;"]

    def test_empty_tokens(self):
        assert BaseStatementParser([]).split_statements() == []

    def test_eof_tokens_skipped(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "1"),
            make_token(TokenType.DELIMITER, ";"),
            make_token(TokenType.EOF, ""),
        ]
        result = BaseStatementParser(tokens).split_statements()
        assert result == ["SELECT 1;"]

    def test_whitespace_only_filtered(self):
        """Remaining tokens that are whitespace-only are not emitted."""
        tokens = [
            make_token(TokenType.IDENTIFIER, "   "),
        ]
        result = BaseStatementParser(tokens).split_statements()
        assert result == []

    def test_remaining_tokens_without_delimiter(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "1"),
        ]
        result = BaseStatementParser(tokens).split_statements()
        assert result == ["SELECT 1"]

    def test_block_prevents_split(self):
        tokens = [
            make_token(TokenType.KEYWORD, "BEGIN"),
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "1"),
            make_token(TokenType.DELIMITER, ";"),
            make_token(TokenType.KEYWORD, "END"),
            make_token(TokenType.DELIMITER, ";"),
        ]
        result = BaseStatementParser(tokens).split_statements()
        assert len(result) == 1
        assert "BEGIN" in result[0]
        assert "END" in result[0]

    def test_nested_blocks(self):
        tokens = [
            make_token(TokenType.KEYWORD, "BEGIN"),
            make_token(TokenType.KEYWORD, "BEGIN"),
            make_token(TokenType.KEYWORD, "NULL"),
            make_token(TokenType.DELIMITER, ";"),
            make_token(TokenType.KEYWORD, "END"),
            make_token(TokenType.DELIMITER, ";"),
            make_token(TokenType.KEYWORD, "END"),
            make_token(TokenType.DELIMITER, ";"),
        ]
        result = BaseStatementParser(tokens).split_statements()
        assert len(result) == 1

    def test_go_delimiter_stripped(self):
        tokens = [
            make_token(TokenType.KEYWORD, "CREATE"),
            make_token(TokenType.KEYWORD, "TABLE"),
            make_token(TokenType.IDENTIFIER, "t"),
            make_token(TokenType.DELIMITER, "GO"),
        ]
        result = BaseStatementParser(tokens).split_statements()
        assert len(result) == 1
        assert "GO" not in result[0]

    def test_go_case_insensitive(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "1"),
            make_token(TokenType.DELIMITER, "go"),
        ]
        result = BaseStatementParser(tokens).split_statements()
        assert len(result) == 1
        assert "go" not in result[0].lower()


# ---------------------------------------------------------------------------
# _is_statement_end
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsStatementEnd:

    def test_delimiter_at_block_depth_zero(self):
        parser = BaseStatementParser([])
        token = make_token(TokenType.DELIMITER, ";")
        assert parser._is_statement_end(token) is True

    def test_delimiter_inside_block(self):
        parser = BaseStatementParser([])
        parser.context.block_depth = 1
        token = make_token(TokenType.DELIMITER, ";")
        assert parser._is_statement_end(token) is False

    def test_non_delimiter_token(self):
        parser = BaseStatementParser([])
        token = make_token(TokenType.KEYWORD, "SELECT")
        assert parser._is_statement_end(token) is False


# ---------------------------------------------------------------------------
# _adjust_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdjustContext:

    def test_appends_token(self):
        parser = BaseStatementParser([])
        token = make_token(TokenType.IDENTIFIER, "foo")
        parser._adjust_context(token)
        assert parser.context.tokens == [token]

    def test_keyword_adjusts_block_depth(self):
        parser = BaseStatementParser([])
        parser._adjust_context(make_token(TokenType.KEYWORD, "BEGIN"))
        assert parser.context.block_depth == 1

    def test_symbol_adjusts_parens_depth(self):
        parser = BaseStatementParser([])
        parser._adjust_context(make_token(TokenType.SYMBOL, "("))
        assert parser.context.parens_depth == 1


# ---------------------------------------------------------------------------
# _adjust_block_depth
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdjustBlockDepth:

    def test_begin_increments(self):
        parser = BaseStatementParser([])
        parser._adjust_block_depth(make_token(TokenType.KEYWORD, "BEGIN"))
        assert parser.context.block_depth == 1

    def test_end_decrements(self):
        parser = BaseStatementParser([])
        parser.context.increase_block_depth("BEGIN")
        parser._adjust_block_depth(make_token(TokenType.KEYWORD, "END"))
        assert parser.context.block_depth == 0

    def test_end_does_not_go_below_zero(self):
        parser = BaseStatementParser([])
        parser._adjust_block_depth(make_token(TokenType.KEYWORD, "END"))
        assert parser.context.block_depth == 0

    def test_case_insensitive(self):
        """BEGIN matching uses .upper(), so lowercase 'begin' also increments."""
        parser = BaseStatementParser([])
        parser._adjust_block_depth(make_token(TokenType.KEYWORD, "begin"))
        assert parser.context.block_depth == 1


# ---------------------------------------------------------------------------
# _adjust_delimiter (no-op in base)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdjustDelimiter:

    def test_noop(self):
        parser = BaseStatementParser([])
        parser._adjust_delimiter(make_token(TokenType.KEYWORD, "DELIMITER"))
        assert parser.context.delimiter == ";"


# ---------------------------------------------------------------------------
# _adjust_parens_depth
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdjustParensDepth:

    def test_open_increments(self):
        parser = BaseStatementParser([])
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, "("))
        assert parser.context.parens_depth == 1

    def test_close_decrements(self):
        parser = BaseStatementParser([])
        parser.context.parens_depth = 2
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, ")"))
        assert parser.context.parens_depth == 1

    def test_close_does_not_go_below_zero(self):
        parser = BaseStatementParser([])
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, ")"))
        assert parser.context.parens_depth == 0

    def test_nested_parens(self):
        parser = BaseStatementParser([])
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, "("))
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, "("))
        assert parser.context.parens_depth == 2
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, ")"))
        assert parser.context.parens_depth == 1


# ---------------------------------------------------------------------------
# _tokens_to_string
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTokensToString:

    def test_empty_list(self):
        parser = BaseStatementParser([])
        assert parser._tokens_to_string([]) == ""

    def test_comments_stripped(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.COMMENT, "-- pick all"),
            make_token(TokenType.IDENTIFIER, "*"),
        ]
        parser = BaseStatementParser([])
        result = parser._tokens_to_string(tokens)
        assert "-- pick all" not in result
        assert "SELECT" in result

    def test_proper_spacing(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "col"),
            make_token(TokenType.KEYWORD, "FROM"),
            make_token(TokenType.IDENTIFIER, "t"),
        ]
        parser = BaseStatementParser([])
        assert parser._tokens_to_string(tokens) == "SELECT col FROM t"

    def test_preserves_space_before_path_slash(self):
        tokens = [
            make_token(TokenType.IDENTIFIER, "SPOOL", pos=0),
            make_token(TokenType.SYMBOL, "/", pos=6),
            make_token(TokenType.IDENTIFIER, "tmp", pos=7),
            make_token(TokenType.SYMBOL, "/", pos=10),
            make_token(TokenType.IDENTIFIER, "dblift_test", pos=11),
            make_token(TokenType.SYMBOL, ".", pos=22),
            make_token(TokenType.IDENTIFIER, "log", pos=23),
        ]

        parser = BaseStatementParser([])

        assert parser._tokens_to_string(tokens) == "SPOOL /tmp/dblift_test.log"


# ---------------------------------------------------------------------------
# _needs_space_between — comprehensive rule coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNeedsSpaceBetween:

    def _space(self, prev, cur):
        return BaseStatementParser([])._needs_space_between(prev, cur)

    # ( after control keywords
    def test_paren_after_when(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "WHEN"),
                make_token(TokenType.SYMBOL, "("),
            )
            is True
        )

    def test_paren_after_if(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "IF"),
                make_token(TokenType.SYMBOL, "("),
            )
            is True
        )

    def test_paren_after_while(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "WHILE"),
                make_token(TokenType.SYMBOL, "("),
            )
            is True
        )

    def test_paren_after_with(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "WITH"),
                make_token(TokenType.SYMBOL, "("),
            )
            is True
        )

    # ( after non-control keyword — no space (e.g. COUNT(...))
    def test_paren_after_other_keyword(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "COUNT"),
                make_token(TokenType.SYMBOL, "("),
            )
            is False
        )

    # ( after identifier — no space (function call)
    def test_paren_after_identifier(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "my_func"),
                make_token(TokenType.SYMBOL, "("),
            )
            is False
        )

    # After ( — no space
    def test_after_open_paren(self):
        assert (
            self._space(
                make_token(TokenType.SYMBOL, "("),
                make_token(TokenType.IDENTIFIER, "x"),
            )
            is False
        )

    # Before ), comma, semicolon — no space
    def test_before_close_paren(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "x"),
                make_token(TokenType.SYMBOL, ")"),
            )
            is False
        )

    def test_before_comma(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "x"),
                make_token(TokenType.SYMBOL, ","),
            )
            is False
        )

    def test_before_semicolon(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "x"),
                make_token(TokenType.SYMBOL, ";"),
            )
            is False
        )

    # After ) before non-closer/non-dot — space
    def test_after_close_paren_before_keyword(self):
        assert (
            self._space(
                make_token(TokenType.SYMBOL, ")"),
                make_token(TokenType.KEYWORD, "PRIMARY"),
            )
            is True
        )

    def test_after_close_paren_before_close_paren(self):
        assert (
            self._space(
                make_token(TokenType.SYMBOL, ")"),
                make_token(TokenType.SYMBOL, ")"),
            )
            is False
        )

    def test_after_close_paren_before_dot(self):
        assert (
            self._space(
                make_token(TokenType.SYMBOL, ")"),
                make_token(TokenType.SYMBOL, "."),
            )
            is False
        )

    # After comma — space
    def test_after_comma(self):
        assert (
            self._space(
                make_token(TokenType.SYMBOL, ","),
                make_token(TokenType.IDENTIFIER, "col"),
            )
            is True
        )

    # Before/after dot — no space
    def test_before_dot(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "schema"),
                make_token(TokenType.SYMBOL, "."),
            )
            is False
        )

    def test_after_dot(self):
        assert (
            self._space(
                make_token(TokenType.SYMBOL, "."),
                make_token(TokenType.IDENTIFIER, "table"),
            )
            is False
        )

    def test_before_slash_symbol_with_original_space(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "SPOOL", pos=0),
                make_token(TokenType.SYMBOL, "/", pos=6),
            )
            is True
        )

    def test_before_slash_symbol_without_original_space(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "tmp", pos=7),
                make_token(TokenType.SYMBOL, "/", pos=10),
            )
            is False
        )

    def test_after_slash_symbol(self):
        assert (
            self._space(
                make_token(TokenType.SYMBOL, "/", pos=6),
                make_token(TokenType.IDENTIFIER, "tmp", pos=7),
            )
            is False
        )

    def test_before_slash_delimiter(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "END"),
                make_token(TokenType.DELIMITER, "/"),
            )
            is False
        )

    def test_after_slash_delimiter(self):
        assert (
            self._space(
                make_token(TokenType.DELIMITER, "/"),
                make_token(TokenType.IDENTIFIER, "CREATE"),
            )
            is False
        )

    # Around = — no space
    def test_before_equals(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "ENGINE"),
                make_token(TokenType.SYMBOL, "="),
            )
            is False
        )

    def test_after_equals(self):
        assert (
            self._space(
                make_token(TokenType.SYMBOL, "="),
                make_token(TokenType.IDENTIFIER, "InnoDB"),
            )
            is False
        )

    # String prefixes N', E', X', B' — no space
    def test_string_prefix_n(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "N"),
                make_token(TokenType.STRING, "'hello'"),
            )
            is False
        )

    def test_string_prefix_e(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "E"),
                make_token(TokenType.STRING, "'escape'"),
            )
            is False
        )

    def test_string_prefix_x(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "X"),
                make_token(TokenType.STRING, "'FF'"),
            )
            is False
        )

    def test_string_prefix_b(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "B"),
                make_token(TokenType.STRING, "'101'"),
            )
            is False
        )

    # Keyword-keyword — space
    def test_keyword_keyword(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "CREATE"),
                make_token(TokenType.KEYWORD, "TABLE"),
            )
            is True
        )

    # Keyword-identifier — space
    def test_keyword_identifier(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "FROM"),
                make_token(TokenType.IDENTIFIER, "users"),
            )
            is True
        )

    # Keyword-string — space
    def test_keyword_string(self):
        assert (
            self._space(
                make_token(TokenType.KEYWORD, "VALUES"),
                make_token(TokenType.STRING, "'abc'"),
            )
            is True
        )

    # Identifier-string — space
    def test_identifier_string(self):
        assert (
            self._space(
                make_token(TokenType.IDENTIFIER, "col"),
                make_token(TokenType.STRING, "'val'"),
            )
            is True
        )

    # String-keyword — space
    def test_string_keyword(self):
        assert (
            self._space(
                make_token(TokenType.STRING, "'abc'"),
                make_token(TokenType.KEYWORD, "AND"),
            )
            is True
        )

    # String-identifier — space
    def test_string_identifier(self):
        assert (
            self._space(
                make_token(TokenType.STRING, "'abc'"),
                make_token(TokenType.IDENTIFIER, "col"),
            )
            is True
        )

    # Before keyword (from number/symbol) — space
    def test_number_before_keyword(self):
        assert (
            self._space(
                make_token(TokenType.STRING, "42"),
                make_token(TokenType.KEYWORD, "AS"),
            )
            is True
        )


# ---------------------------------------------------------------------------
# _last_token_is
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLastTokenIs:

    def test_matches_last_keyword(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [
            make_token(TokenType.KEYWORD, "CREATE"),
            make_token(TokenType.KEYWORD, "TABLE"),
        ]
        assert parser._last_token_is("TABLE") is True

    def test_no_match(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [make_token(TokenType.KEYWORD, "SELECT")]
        assert parser._last_token_is("FROM") is False

    def test_skips_comments(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [
            make_token(TokenType.KEYWORD, "TABLE"),
            make_token(TokenType.COMMENT, "-- note"),
        ]
        assert parser._last_token_is("TABLE") is True

    def test_stops_at_non_keyword_non_comment(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "col"),
        ]
        assert parser._last_token_is("SELECT") is False

    def test_parens_depth_filter(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [
            make_token(TokenType.KEYWORD, "CASE", parens_depth=1),
            make_token(TokenType.KEYWORD, "WHEN", parens_depth=0),
        ]
        # Without filter — last keyword is WHEN
        assert parser._last_token_is("WHEN") is True
        # With filter depth=1 — skips WHEN(depth=0), finds CASE(depth=1)
        assert parser._last_token_is("CASE", parens_depth=1) is True

    def test_empty_context(self):
        parser = BaseStatementParser([])
        assert parser._last_token_is("SELECT") is False

    def test_case_insensitive(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [make_token(TokenType.KEYWORD, "select")]
        assert parser._last_token_is("SELECT") is True


# ---------------------------------------------------------------------------
# _peek_next_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPeekNextToken:

    def test_returns_next_token(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "1"),
        ]
        parser = BaseStatementParser(tokens)
        parser.current_idx = 0
        assert parser._peek_next_token().text == "1"

    def test_skips_comments(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.COMMENT, "-- x"),
            make_token(TokenType.IDENTIFIER, "1"),
        ]
        parser = BaseStatementParser(tokens)
        parser.current_idx = 0
        assert parser._peek_next_token().text == "1"

    def test_does_not_skip_comments_when_disabled(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.COMMENT, "-- x"),
            make_token(TokenType.IDENTIFIER, "1"),
        ]
        parser = BaseStatementParser(tokens)
        parser.current_idx = 0
        result = parser._peek_next_token(skip_comments=False)
        assert result.type == TokenType.COMMENT

    def test_returns_none_at_end(self):
        tokens = [make_token(TokenType.KEYWORD, "SELECT")]
        parser = BaseStatementParser(tokens)
        parser.current_idx = 0
        assert parser._peek_next_token() is None

    def test_returns_none_when_only_comments_remain(self):
        tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.COMMENT, "-- end"),
        ]
        parser = BaseStatementParser(tokens)
        parser.current_idx = 0
        assert parser._peek_next_token() is None


# ---------------------------------------------------------------------------
# _get_previous_tokens
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetPreviousTokens:

    def test_returns_last_token(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "col"),
        ]
        result = parser._get_previous_tokens(1)
        assert len(result) == 1
        assert result[0].text == "col"

    def test_returns_multiple(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.IDENTIFIER, "a"),
            make_token(TokenType.IDENTIFIER, "b"),
        ]
        result = parser._get_previous_tokens(2)
        assert [t.text for t in result] == ["a", "b"]

    def test_skips_comments(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [
            make_token(TokenType.KEYWORD, "SELECT"),
            make_token(TokenType.COMMENT, "-- note"),
            make_token(TokenType.IDENTIFIER, "col"),
        ]
        result = parser._get_previous_tokens(2)
        assert [t.text for t in result] == ["SELECT", "col"]

    def test_fewer_tokens_than_requested(self):
        parser = BaseStatementParser([])
        parser.context.tokens = [make_token(TokenType.KEYWORD, "SELECT")]
        result = parser._get_previous_tokens(5)
        assert len(result) == 1

    def test_empty_context(self):
        parser = BaseStatementParser([])
        assert parser._get_previous_tokens(1) == []
