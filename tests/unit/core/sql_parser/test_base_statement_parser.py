"""Tests for BaseStatementParser and the statement splitting it underlies."""

import pytest

from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC


def make_token(type, text, pos=0, line=1, col=1, parens_depth=0):
    return Token(type=type, text=text, pos=pos, line=line, col=col, parens_depth=parens_depth)


def make_parser(tokens=()):
    return BaseStatementParser(tokens, source="")


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstructor:

    def test_stores_tokens(self):
        tokens = [make_token(TokenType.KEYWORD, "SELECT")]
        parser = BaseStatementParser(tokens, source="SELECT")
        assert parser.tokens is tokens

    def test_creates_context_when_none(self):
        parser = make_parser()
        assert isinstance(parser.context, ParserContext)

    def test_uses_provided_context(self):
        ctx = ParserContext(block_depth=2)
        parser = BaseStatementParser([], context=ctx, source="")
        assert parser.context is ctx
        assert parser.context.block_depth == 2


# ---------------------------------------------------------------------------
# split_statements, through the engine every script is read by
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSplitStatements:

    def test_simple_two_statements(self):
        assert LexicalEngine(POSTGRESQL_SPEC).split_statements("SELECT 1; SELECT 2;") == [
            "SELECT 1;",
            "SELECT 2;",
        ]

    def test_empty_script(self):
        assert LexicalEngine(POSTGRESQL_SPEC).split_statements("") == []

    def test_whitespace_only_filtered(self):
        assert LexicalEngine(POSTGRESQL_SPEC).split_statements("   \n\n   \t   ") == []

    def test_remaining_tokens_without_delimiter(self):
        assert LexicalEngine(POSTGRESQL_SPEC).split_statements("SELECT 1") == ["SELECT 1"]

    def test_block_prevents_split(self):
        result = LexicalEngine(SQLSERVER_SPEC).split_statements("BEGIN SELECT 1; END;")
        assert result == ["BEGIN SELECT 1; END;"]

    def test_nested_blocks(self):
        result = LexicalEngine(SQLSERVER_SPEC).split_statements("BEGIN BEGIN NULL; END; END;")
        assert result == ["BEGIN BEGIN NULL; END; END;"]

    def test_go_delimiter_stripped(self):
        result = LexicalEngine(SQLSERVER_SPEC).split_statements("CREATE TABLE t (id INT)\nGO\n")
        assert result == ["CREATE TABLE t (id INT)"]

    def test_go_case_insensitive(self):
        assert LexicalEngine(SQLSERVER_SPEC).split_statements("SELECT 1\ngo\n") == ["SELECT 1"]


# ---------------------------------------------------------------------------
# _is_statement_end
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsStatementEnd:

    def test_delimiter_at_block_depth_zero(self):
        parser = make_parser()
        token = make_token(TokenType.DELIMITER, ";")
        assert parser._is_statement_end(token) is True

    def test_delimiter_inside_block(self):
        parser = make_parser()
        parser.context.block_depth = 1
        token = make_token(TokenType.DELIMITER, ";")
        assert parser._is_statement_end(token) is False

    def test_non_delimiter_token(self):
        parser = make_parser()
        token = make_token(TokenType.KEYWORD, "SELECT")
        assert parser._is_statement_end(token) is False


# ---------------------------------------------------------------------------
# _adjust_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdjustContext:

    def test_appends_token(self):
        parser = make_parser()
        token = make_token(TokenType.IDENTIFIER, "foo")
        parser._adjust_context(token)
        assert parser.context.tokens == [token]

    def test_keyword_adjusts_block_depth(self):
        parser = make_parser()
        parser._adjust_context(make_token(TokenType.KEYWORD, "BEGIN"))
        assert parser.context.block_depth == 1

    def test_symbol_adjusts_parens_depth(self):
        parser = make_parser()
        parser._adjust_context(make_token(TokenType.SYMBOL, "("))
        assert parser.context.parens_depth == 1


# ---------------------------------------------------------------------------
# _adjust_block_depth
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdjustBlockDepth:

    def test_begin_increments(self):
        parser = make_parser()
        parser._adjust_block_depth(make_token(TokenType.KEYWORD, "BEGIN"))
        assert parser.context.block_depth == 1

    def test_end_decrements(self):
        parser = make_parser()
        parser.context.increase_block_depth("BEGIN")
        parser._adjust_block_depth(make_token(TokenType.KEYWORD, "END"))
        assert parser.context.block_depth == 0

    def test_end_does_not_go_below_zero(self):
        parser = make_parser()
        parser._adjust_block_depth(make_token(TokenType.KEYWORD, "END"))
        assert parser.context.block_depth == 0

    def test_case_insensitive(self):
        """BEGIN matching uses .upper(), so lowercase 'begin' also increments."""
        parser = make_parser()
        parser._adjust_block_depth(make_token(TokenType.KEYWORD, "begin"))
        assert parser.context.block_depth == 1


# ---------------------------------------------------------------------------
# _adjust_parens_depth
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdjustParensDepth:

    def test_open_increments(self):
        parser = make_parser()
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, "("))
        assert parser.context.parens_depth == 1

    def test_close_decrements(self):
        parser = make_parser()
        parser.context.parens_depth = 2
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, ")"))
        assert parser.context.parens_depth == 1

    def test_close_does_not_go_below_zero(self):
        parser = make_parser()
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, ")"))
        assert parser.context.parens_depth == 0

    def test_nested_parens(self):
        parser = make_parser()
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, "("))
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, "("))
        assert parser.context.parens_depth == 2
        parser._adjust_parens_depth(make_token(TokenType.SYMBOL, ")"))
        assert parser.context.parens_depth == 1


def test_semicolon_inside_parentheses_ends_a_statement_unless_the_dialect_says_otherwise() -> None:
    script = "CREATE RULE r AS ON INSERT TO t DO ALSO (INSERT INTO u VALUES (1); INSERT INTO v VALUES (2)); SELECT 1;"
    assert len(LexicalEngine(DUCKDB_SPEC).split_statements(script)) == 3

    assert LexicalEngine(POSTGRESQL_SPEC).split_statements(script) == [
        "CREATE RULE r AS ON INSERT TO t DO ALSO (INSERT INTO u VALUES (1); INSERT INTO v VALUES (2));",
        "SELECT 1;",
    ]


def test_parenthesis_depth_ignores_what_strings_contain() -> None:
    from dblift.core.sql_parser.lexical_statement_parser import (
        LexicalStatementParser,
    )
    from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
    from dblift.core.sql_parser.parser_context import ParserContext

    script = "CREATE RULE r AS ON INSERT TO t DO ALSO (SELECT $$a;b)$$; SELECT ')');\nSELECT 1;"
    tokens = LexicalTokenizer(script, spec=POSTGRESQL_SPEC).tokenize()
    out = LexicalStatementParser(
        tokens, ParserContext(), source=script, spec=POSTGRESQL_SPEC
    ).split_statements()
    assert len(out) == 2 and out[1] == "SELECT 1;"
