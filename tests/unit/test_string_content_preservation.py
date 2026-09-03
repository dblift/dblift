"""Test that string content is preserved when reconstructing SQL statements.

This test verifies the fix for the issue where _handle_single_quoted_string
and _handle_double_quoted_string returned empty text fields, causing string
literals to be lost when _tokens_to_string reconstructed SQL.
"""

import pytest

from dblift.db.plugins.mysql.parser.mysql_statement_parser import MySQLStatementParser
from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer
from dblift.db.plugins.postgresql.parser.postgresql_statement_parser import (
    PostgreSQLStatementParser,
)
from dblift.db.plugins.postgresql.parser.postgresql_tokenizer import PostgreSQLTokenizer


class TestMySQLStringPreservation:
    """Test MySQL string content preservation."""

    def test_single_quoted_string_preserved(self):
        """Test that single-quoted strings are preserved in reconstructed SQL."""
        sql = "SELECT 'hello' FROM users;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert "'hello'" in statements[0]
        assert "FROM users" in statements[0]

    def test_double_quoted_string_preserved(self):
        """Test that double-quoted strings are preserved in reconstructed SQL."""
        sql = 'SELECT "world" FROM users;'
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert '"world"' in statements[0]
        assert "FROM users" in statements[0]

    def test_string_with_escaped_quotes_preserved(self):
        """Test that strings with escaped quotes are preserved."""
        sql = "SELECT 'O''Reilly' FROM authors;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert "'O''Reilly'" in statements[0]
        assert "FROM authors" in statements[0]

    def test_string_with_backslash_escapes_preserved(self):
        """Test that strings with backslash escapes are preserved."""
        sql = "SELECT 'Line1\\nLine2\\tTab' FROM dual;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert "'Line1\\nLine2\\tTab'" in statements[0]
        assert "FROM dual" in statements[0]

    def test_insert_with_string_values_preserved(self):
        """Test that INSERT statements with string values are preserved."""
        sql = "INSERT INTO users (name, email) VALUES ('John Doe', 'john@example.com');"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert "'John Doe'" in statements[0]
        assert "'john@example.com'" in statements[0]
        assert "INSERT INTO users" in statements[0]


class TestPostgreSQLStringPreservation:
    """Test PostgreSQL string content preservation."""

    def test_single_quoted_string_preserved(self):
        """Test that single-quoted strings are preserved in reconstructed SQL."""
        sql = "SELECT 'hello' FROM users;"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = PostgreSQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert "'hello'" in statements[0]
        assert "FROM users" in statements[0]

    def test_dollar_quoted_string_preserved(self):
        """Test that dollar-quoted strings are preserved in reconstructed SQL."""
        sql = "SELECT $$Hello World$$ FROM users;"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = PostgreSQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert "$$Hello World$$" in statements[0]
        assert "FROM users" in statements[0]

    def test_tagged_dollar_quote_preserved(self):
        """Test that tagged dollar-quoted strings are preserved."""
        sql = "SELECT $tag$Content with 'quotes'$tag$ FROM users;"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = PostgreSQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert "$tag$Content with 'quotes'$tag$" in statements[0]
        assert "FROM users" in statements[0]

    def test_double_quoted_identifier_preserved(self):
        """Test that double-quoted identifiers are preserved."""
        sql = 'SELECT "MyColumn" FROM "MyTable";'
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = PostgreSQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert '"MyColumn"' in statements[0]
        assert '"MyTable"' in statements[0]

    def test_function_with_dollar_quotes_preserved(self):
        """Test that function definitions with dollar quotes are preserved."""
        sql = """CREATE FUNCTION test_func() RETURNS TEXT AS $$
BEGIN
    RETURN 'Hello World';
END;
$$ LANGUAGE plpgsql;"""
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = PostgreSQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        # Check that the dollar quotes are preserved
        assert "$$" in statements[0]
        assert "RETURN 'Hello World'" in statements[0]
        assert "CREATE FUNCTION" in statements[0]

    def test_insert_with_string_values_preserved(self):
        """Test that INSERT statements with string values are preserved."""
        sql = "INSERT INTO users (name, email) VALUES ('Jane Doe', 'jane@example.com');"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = PostgreSQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1
        assert "'Jane Doe'" in statements[0]
        assert "'jane@example.com'" in statements[0]
        assert "INSERT INTO users" in statements[0]


class TestStringContentNotEmpty:
    """Test that token.text is not empty for string tokens."""

    def test_mysql_string_token_not_empty(self):
        """Test that MySQL string tokens have non-empty text."""
        sql = "SELECT 'test' FROM users;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type.name == "STRING"]
        assert len(string_tokens) == 1
        assert string_tokens[0].text != ""
        assert string_tokens[0].text == "'test'"

    def test_postgresql_string_token_not_empty(self):
        """Test that PostgreSQL string tokens have non-empty text."""
        sql = "SELECT 'test' FROM users;"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type.name == "STRING"]
        assert len(string_tokens) == 1
        assert string_tokens[0].text != ""
        assert string_tokens[0].text == "'test'"

    def test_postgresql_dollar_quote_token_not_empty(self):
        """Test that PostgreSQL dollar-quoted tokens have non-empty text."""
        sql = "SELECT $$test$$ FROM users;"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type.name == "STRING"]
        assert len(string_tokens) == 1
        assert string_tokens[0].text != ""
        assert string_tokens[0].text == "$$test$$"

    def test_postgresql_identifier_token_not_empty(self):
        """Test that PostgreSQL identifier tokens have non-empty text."""
        sql = 'SELECT "MyColumn" FROM users;'
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type.name == "IDENTIFIER"]
        # Should have "MyColumn" (quoted) and users (unquoted)
        assert len(identifier_tokens) == 2
        # Find the quoted identifier
        quoted_identifiers = [t for t in identifier_tokens if t.text.startswith('"')]
        assert len(quoted_identifiers) == 1
        assert quoted_identifiers[0].text == '"MyColumn"'
