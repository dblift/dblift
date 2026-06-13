"""Unit tests for Oracle-specific tokenization."""

import pytest

from core.sql_parser.parser_context import ParserContext
from core.sql_parser.tokens import TokenType
from db.plugins.oracle.parser.oracle_statement_parser import OracleStatementParser
from db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer


class TestOracleTokenizer:
    """Test Oracle-specific tokenization features."""

    def test_q_quote_braces(self):
        """Test Q-quote with braces."""
        sql = "SELECT q'{Hello 'World'}' FROM dual;"
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) == 1

    def test_q_quote_brackets(self):
        """Test Q-quote with brackets."""
        sql = "SELECT q'[Hello [World]]' FROM dual;"
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) == 1

    def test_q_quote_custom_delimiter(self):
        """Test Q-quote with custom delimiter."""
        sql = "SELECT q'!Hello; World!' FROM dual;"
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) == 1

    def test_double_quoted_identifier(self):
        """Test double-quoted identifiers."""
        sql = 'SELECT "MyColumn" FROM "MyTable";'
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert [t.text for t in identifier_tokens] == ['"MyColumn"', '"MyTable"']

    def test_slash_delimiter_detection(self):
        """Test slash delimiter at start of line."""
        sql = """CREATE PROCEDURE test_proc AS
BEGIN
  NULL;
END;
/"""
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        delimiter_tokens = [t for t in tokens if t.type == TokenType.DELIMITER]
        # Should have / delimiter
        assert any(t.text == "/" for t in delimiter_tokens)

    def test_slash_not_delimiter_in_expression(self):
        """Test that slash in expression is not a delimiter."""
        sql = "SELECT 10 / 2 FROM dual;"
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        # The / should be a symbol, not delimiter
        symbol_tokens = [t for t in tokens if t.type == TokenType.SYMBOL and t.text == "/"]
        delimiter_tokens = [t for t in tokens if t.type == TokenType.DELIMITER and t.text == "/"]

        assert len(symbol_tokens) == 1
        assert len(delimiter_tokens) == 0


class TestOracleStatementParser:
    """Test Oracle-specific statement parsing."""

    def test_simple_sql_split(self):
        """Test simple SQL statement splitting."""
        sql = "SELECT * FROM table1; SELECT * FROM table2;"
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = OracleStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 2

    def test_plsql_block_with_slash(self):
        """Test PL/SQL block terminated by slash."""
        sql = """CREATE PROCEDURE test_proc AS
BEGIN
  NULL;
END;
/"""
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = OracleStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement (procedure with slash)
        assert len(statements) == 1

    def test_plsql_block_with_nested_begin_end(self):
        """Test nested BEGIN/END blocks."""
        sql = """CREATE PROCEDURE test_proc AS
BEGIN
  IF true THEN
    BEGIN
      NULL;
    END;
  END IF;
END;
/"""
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = OracleStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement
        assert len(statements) == 1

    def test_end_if_not_block_terminator(self):
        """Test that END IF doesn't close a BEGIN block."""
        sql = """BEGIN
  IF true THEN
    NULL;
  END IF;
  NULL;
END;
/"""
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = OracleStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement
        assert len(statements) == 1

    def test_multiple_ddl_with_slash(self):
        """Test multiple DDL statements with slash delimiters."""
        sql = """CREATE TABLE test1 (id NUMBER);
/
CREATE TABLE test2 (id NUMBER);
/"""
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = OracleStatementParser(tokens)
        statements = parser.split_statements()

        # Should be two statements
        assert len(statements) == 2

    def test_package_body_with_nested_procedures(self):
        """Test package body with nested procedures."""
        sql = """CREATE OR REPLACE PACKAGE BODY test_pkg AS
  PROCEDURE proc1 AS
  BEGIN
    NULL;
  END proc1;
  
  PROCEDURE proc2 AS
  BEGIN
    NULL;
  END proc2;
END test_pkg;
/"""
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = OracleStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement (entire package body)
        assert len(statements) == 1

    def test_sql_with_q_quotes(self):
        """Test SQL with Q-quotes containing semicolons."""
        sql = """SELECT q'[This; has; semicolons]' FROM dual;"""
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = OracleStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement
        assert len(statements) == 1
