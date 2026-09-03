"""Unit tests for basic SQL tokenization."""

import pytest

from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.tokens import Token, TokenType


class TestBaseTokenizer:
    """Test base tokenization functionality."""

    def test_simple_sql_tokenization(self):
        """Test tokenization of simple SQL."""
        sql = "SELECT * FROM users WHERE id = 1;"
        tokenizer = BaseTokenizer(sql)
        tokens = tokenizer.tokenize()

        assert len(tokens) > 0
        assert any(t.type == TokenType.KEYWORD for t in tokens)
        assert any(t.type == TokenType.DELIMITER for t in tokens)

    def test_comment_handling(self):
        """Test comment tokenization."""
        sql = "-- Comment\nSELECT * FROM table1; /* block comment */"
        tokenizer = BaseTokenizer(sql)
        tokens = tokenizer.tokenize()

        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_tokens) == 2

    def test_string_literal_tokenization(self):
        """Test string literal handling."""
        sql = "SELECT 'hello world' FROM table1;"
        tokenizer = BaseTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) == 1

    def test_string_with_escaped_quote(self):
        """Test string with escaped quotes."""
        sql = "SELECT 'O''Reilly' FROM table1;"
        tokenizer = BaseTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) == 1

    def test_parentheses_depth_tracking(self):
        """Test parentheses depth tracking."""
        sql = "SELECT * FROM table1 WHERE (col1 = 1 AND (col2 = 2));"
        tokenizer = BaseTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Find max parens depth
        max_depth = max(t.parens_depth for t in tokens)
        assert max_depth >= 2

    def test_line_and_column_tracking(self):
        """Test line and column position tracking."""
        sql = "SELECT *\nFROM users\nWHERE id = 1;"
        tokenizer = BaseTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Check that line numbers increase
        lines = [t.line for t in tokens if t.type == TokenType.KEYWORD]
        assert len(set(lines)) > 1  # Multiple lines
        assert max(lines) >= 3


class TestParserContext:
    """Test parser context state management."""

    def test_context_initialization(self):
        """Test context initial state."""
        context = ParserContext()

        assert context.block_depth == 0
        assert context.delimiter == ";"
        assert context.parens_depth == 0

    def test_block_depth_management(self):
        """Test block depth increase/decrease."""
        context = ParserContext()

        context.increase_block_depth("BEGIN")
        assert context.block_depth == 1
        assert context.block_initiator == "BEGIN"

        context.increase_block_depth("IF")
        assert context.block_depth == 2

        context.decrease_block_depth()
        assert context.block_depth == 1

    def test_context_reset(self):
        """Test context reset for new statement."""
        context = ParserContext()
        context.increase_block_depth("BEGIN")
        context.parens_depth = 2
        context.delimiter = "/"

        context.reset_for_new_statement()

        assert context.block_depth == 0
        assert context.parens_depth == 0
        assert context.delimiter == "/"  # Delimiter persists


class TestBaseStatementParser:
    """Test base statement parsing."""

    def test_simple_statement_split(self):
        """Test splitting simple statements."""
        sql = "SELECT * FROM table1; SELECT * FROM table2;"
        tokenizer = BaseTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = BaseStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 2

    def test_block_depth_prevents_split(self):
        """Test that statements in blocks aren't split."""
        sql = "BEGIN SELECT * FROM table1; SELECT * FROM table2; END;"
        tokenizer = BaseTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = BaseStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement (the entire BEGIN/END block)
        assert len(statements) == 1

    def test_empty_sql_handling(self):
        """Test handling of empty SQL."""
        tokenizer = BaseTokenizer("")
        tokens = tokenizer.tokenize()

        parser = BaseStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 0

    def test_whitespace_only_handling(self):
        """Test handling of whitespace-only SQL."""
        sql = "   \n\n   \t   "
        tokenizer = BaseTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = BaseStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 0
