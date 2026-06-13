"""Additional SQL Server tokenizer tests to reach 80%+ coverage."""

import pytest

from core.sql_parser.tokens import TokenType
from db.plugins.sqlserver.parser.sqlserver_tokenizer import SQLServerTokenizer


class TestSQLServerTokenizerCoverage:
    """Tests to cover remaining SQL Server tokenizer lines."""

    def test_handle_keyword_with_bracket(self):
        """Test _handle_keyword when it encounters bracket identifier."""
        sql = "SELECT [column_name] FROM [table_name];"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should call _handle_bracketed_identifier (lines 104)
        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_handle_keyword_with_double_quote(self):
        """Test _handle_keyword when it encounters double-quoted identifier."""
        sql = 'SELECT "column_name" FROM "table_name";'
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should call _handle_quoted_identifier (lines 107-108)
        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_bracketed_identifier_simple(self):
        """Test simple bracketed identifier (lines 119-138)."""
        sql = "SELECT [simple_column] FROM [simple_table];"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_bracketed_identifier_with_escaped_brackets(self):
        """Test bracketed identifier with escaped brackets (lines 129-131)."""
        sql = "SELECT [col]]name] FROM [tab]]le];"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_bracketed_identifier_reaching_end(self):
        """Test bracketed identifier that reaches end of string."""
        sql = "[incomplete"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should handle gracefully
        assert len(tokens) > 0

    def test_double_quoted_identifier_simple(self):
        """Test simple double-quoted identifier (lines 153-172)."""
        sql = 'SELECT "simple_column" FROM "simple_table";'
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_double_quoted_identifier_with_escaped_quotes(self):
        """Test double-quoted identifier with escaped quotes (lines 164-165)."""
        sql = 'SELECT "col""name" FROM "tab""le";'
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_double_quoted_identifier_reaching_end(self):
        """Test double-quoted identifier that reaches end of string."""
        sql = '"incomplete'
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should handle gracefully
        assert len(tokens) > 0

    def test_mixed_identifiers(self):
        """Test mix of bracket and double-quoted identifiers."""
        sql = 'SELECT [bracket_col], "quoted_col" FROM [bracket_table];'
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 3

    def test_bracketed_identifier_with_spaces(self):
        """Test bracketed identifier with spaces."""
        sql = "SELECT [column name with spaces] FROM [table name];"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_bracketed_identifier_with_special_chars(self):
        """Test bracketed identifier with special characters."""
        sql = "SELECT [col-name.special] FROM [tab@le#name];"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_double_quoted_identifier_with_spaces(self):
        """Test double-quoted identifier with spaces."""
        sql = 'SELECT "column name" FROM "table name";'
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_go_delimiter_at_end_of_file(self):
        """Test GO delimiter at end of file (lines 35-37)."""
        sql = "SELECT * FROM test\nGO"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should recognize GO at end of file
        delimiter_tokens = [t for t in tokens if t.type == TokenType.DELIMITER]
        assert len(delimiter_tokens) >= 1
        assert any(t.text.upper() == "GO" for t in delimiter_tokens)

    def test_go_delimiter_followed_by_whitespace(self):
        """Test GO delimiter followed by whitespace (lines 39-41, 58-60)."""
        sql = "SELECT * FROM test\nGO\nSELECT * FROM test2\nGO "
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should recognize GO followed by whitespace
        delimiter_tokens = [t for t in tokens if t.type == TokenType.DELIMITER]
        assert len(delimiter_tokens) >= 2
        go_delimiters = [t for t in delimiter_tokens if t.text.upper() == "GO"]
        assert len(go_delimiters) >= 2

    def test_single_quote_string_detection(self):
        """Test single-quoted string detection (line 90)."""
        sql = "SELECT 'test string' FROM table"
        tokenizer = SQLServerTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should recognize single-quoted strings
        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1
        assert any("test string" in t.text for t in string_tokens)
