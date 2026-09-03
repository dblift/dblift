"""Unit tests for MySQL tokenizer empty delimiter bug fix.

Tests for the fix of the infinite loop bug when DELIMITER statement
is followed by whitespace/newline without an actual delimiter string.
"""

import pytest

from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.mysql.parser.mysql_statement_parser import MySQLStatementParser
from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer


class TestMySQLEmptyDelimiterFix:
    """Test empty delimiter handling."""

    def test_delimiter_with_no_delimiter_at_end(self):
        """Test DELIMITER with no delimiter at end of file."""
        sql = "DELIMITER"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should keep default semicolon delimiter
        assert tokenizer.current_delimiter == ";"

        # Should have one NEW_DELIMITER token
        new_delimiter_tokens = [t for t in tokens if t.type == TokenType.NEW_DELIMITER]
        assert len(new_delimiter_tokens) == 1
        assert new_delimiter_tokens[0].text == ";"

    def test_delimiter_with_only_spaces(self):
        """Test DELIMITER followed by only spaces."""
        sql = "DELIMITER   "
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should keep default semicolon delimiter
        assert tokenizer.current_delimiter == ";"

    def test_delimiter_with_only_tab(self):
        """Test DELIMITER followed by only tab."""
        sql = "DELIMITER\t"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should keep default semicolon delimiter
        assert tokenizer.current_delimiter == ";"

    def test_delimiter_then_newline_then_sql(self):
        """Test DELIMITER followed by newline and then SQL."""
        sql = "DELIMITER\nSELECT 1;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should keep default semicolon delimiter
        assert tokenizer.current_delimiter == ";"

        # Should parse SELECT statement normally
        keyword_tokens = [t for t in tokens if t.type == TokenType.KEYWORD]
        assert any(t.text.upper() == "SELECT" for t in keyword_tokens)

    def test_delimiter_with_spaces_then_newline(self):
        """Test DELIMITER with spaces then newline."""
        sql = "DELIMITER   \nSELECT 1;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should keep default semicolon delimiter
        assert tokenizer.current_delimiter == ";"

        # Should parse SELECT statement normally
        keyword_tokens = [t for t in tokens if t.type == TokenType.KEYWORD]
        assert any(t.text.upper() == "SELECT" for t in keyword_tokens)

    def test_normal_delimiter_then_empty_delimiter(self):
        """Test normal DELIMITER followed by empty DELIMITER."""
        sql = "DELIMITER //\nSELECT 1//\nDELIMITER\nSELECT 2;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should keep // delimiter (not change to empty)
        assert tokenizer.current_delimiter == "//"

        # Should have two NEW_DELIMITER tokens
        new_delimiter_tokens = [t for t in tokens if t.type == TokenType.NEW_DELIMITER]
        assert len(new_delimiter_tokens) == 2
        assert new_delimiter_tokens[0].text == "//"
        assert new_delimiter_tokens[1].text == "//"  # Kept // instead of empty

    def test_statement_parsing_with_empty_delimiter(self):
        """Test statement parsing doesn't break with empty DELIMITER."""
        sql = "DELIMITER\nCREATE TABLE test (id INT);"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should successfully parse statements
        assert len(statements) > 0
        assert any("CREATE TABLE" in s.upper() for s in statements)

    def test_delimiter_prevents_infinite_loop(self):
        """Test that empty delimiter doesn't cause infinite loop."""
        sql = "DELIMITER   \nSELECT 1;"

        # This should complete without hanging
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should complete successfully
        assert len(tokens) > 0
        assert tokenizer.current_delimiter == ";"
