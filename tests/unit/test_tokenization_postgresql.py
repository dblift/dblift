"""Unit tests for PostgreSQL-specific tokenization."""

import pytest

from dblift.core.sql_parser.lexical_statement_parser import (
    LexicalStatementParser,
)
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC


class TestLexicalTokenizer:
    """Test PostgreSQL-specific tokenization features."""

    def test_dollar_quoted_strings(self):
        """Test dollar-quoted string literals."""
        sql = "SELECT $$Hello World$$;"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1

    def test_tagged_dollar_quotes(self):
        """Test tagged dollar-quoted strings."""
        sql = "SELECT $tag$Hello World$tag$;"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1

    def test_double_quoted_identifiers(self):
        """Test double-quoted identifiers."""
        sql = 'SELECT "MyColumn" FROM "MyTable";'
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_migration_placeholder_not_dollar_quote(self):
        """${name} is Flyway-style placeholder, not PostgreSQL $tag$ string."""
        sql = "CREATE TABLE ${table_schema}.users (id INT);"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()
        texts = [t.text for t in tokens if t.type != TokenType.EOF]
        assert "${table_schema}" in texts
        assert any(t.text == "." for t in tokens)
        parser = LexicalStatementParser(tokens, spec=POSTGRESQL_SPEC)
        stmts = parser.split_statements()
        assert len(stmts) == 1
        assert "${table_schema}.users" in stmts[0]

    def test_dollar_quote_with_semicolons(self):
        """Test dollar quotes can contain semicolons."""
        sql = "SELECT $$Text with; semicolons; inside$$;"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1


class TestLexicalStatementParser:
    """Test PostgreSQL-specific statement parsing."""

    def test_simple_sql_split(self):
        """Test simple SQL statement splitting."""
        sql = "SELECT * FROM table1; SELECT * FROM table2;"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        parser = LexicalStatementParser(tokens, spec=POSTGRESQL_SPEC)
        statements = parser.split_statements()

        assert len(statements) == 2

    def test_function_with_dollar_quotes(self):
        """Test function definition with dollar quotes."""
        sql = """CREATE FUNCTION test_func() RETURNS INTEGER AS $$
BEGIN
    RETURN 42;
END;
$$ LANGUAGE plpgsql;"""
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        parser = LexicalStatementParser(tokens, spec=POSTGRESQL_SPEC)
        statements = parser.split_statements()

        # Should be one statement (entire function)
        assert len(statements) == 1

    def test_begin_atomic_block(self):
        """Test BEGIN ATOMIC block detection."""
        sql = """CREATE FUNCTION test() RETURNS INT
BEGIN ATOMIC
    SELECT 1;
    SELECT 2;
END;"""
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        parser = LexicalStatementParser(tokens, spec=POSTGRESQL_SPEC)
        statements = parser.split_statements()

        # Should be one statement (entire function with ATOMIC block)
        assert len(statements) == 1

    def test_transaction_compatibility(self):
        """Test transaction compatibility detection."""
        sql = "CREATE TABLE test (id INT);"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        context = ParserContext()
        parser = LexicalStatementParser(tokens, context, spec=POSTGRESQL_SPEC)
        statements = parser.split_statements()

        # Regular DDL can run in transaction
        from dblift.core.migration.sql.execution_statement import classify_execution_statement

        assert classify_execution_statement(sql, dialect="postgresql").can_execute_in_transaction

    def test_create_domain_preserves_regex_match_operator(self):
        """~ must tokenize as a symbol; otherwise CHECK (VALUE ~ '...') breaks DDL."""
        sql = (
            "CREATE DOMAIN email_domain AS VARCHAR(255) "
            "CHECK (VALUE ~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Z]{2,}$');"
        )
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        parser = LexicalStatementParser(tokenizer.tokenize(), spec=POSTGRESQL_SPEC)
        statements = parser.split_statements()
        assert len(statements) == 1
        assert "VALUE ~ '" in statements[0] or "VALUE ~'" in statements[0]
        assert "VALUE '" not in statements[0]

    def test_nested_dollar_quotes(self):
        """Test nested dollar quotes with different tags."""
        sql = """CREATE FUNCTION nested() RETURNS TEXT AS $$
DECLARE
    result TEXT;
BEGIN
    result := $body$Inner content$body$;
    RETURN result;
END;
$$ LANGUAGE plpgsql;"""
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        parser = LexicalStatementParser(tokens, spec=POSTGRESQL_SPEC)
        statements = parser.split_statements()

        # Should be one statement
        assert len(statements) == 1
