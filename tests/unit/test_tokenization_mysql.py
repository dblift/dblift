"""Unit tests for MySQL-specific tokenization."""

import pytest

from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.mysql.parser.mysql_statement_parser import MySQLStatementParser
from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer


class TestMySQLTokenizer:
    """Test MySQL-specific tokenization features."""

    def test_backtick_identifiers(self):
        """Test backtick-quoted identifiers."""
        sql = "SELECT `column_name` FROM `table_name`;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2
        assert any("`column_name`" in t.text for t in identifier_tokens)
        assert any("`table_name`" in t.text for t in identifier_tokens)

    def test_delimiter_statement(self):
        """Test DELIMITER statement parsing."""
        sql = "DELIMITER //\nSELECT 1//\nDELIMITER ;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        new_delimiter_tokens = [t for t in tokens if t.type == TokenType.NEW_DELIMITER]
        assert len(new_delimiter_tokens) >= 1

    def test_hash_comments(self):
        """Test hash-style comments."""
        sql = "# This is a comment\nSELECT * FROM table1;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        comment_tokens = [t for t in tokens if t.type == TokenType.COMMENT]
        assert len(comment_tokens) >= 1

    def test_comment_directives(self):
        """Test MySQL comment directives."""
        sql = "/*!50001 CREATE VIEW v1 AS SELECT 1 */;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        directive_tokens = [t for t in tokens if t.type == TokenType.COMMENT_DIRECTIVE]
        assert len(directive_tokens) >= 1

    def test_backslash_escapes_in_strings(self):
        """Test backslash escapes in strings."""
        sql = "SELECT 'Line1\\nLine2\\tTab' FROM dual;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1

    def test_double_quoted_strings(self):
        """Test double-quoted strings."""
        sql = 'SELECT "Hello World" FROM dual;'
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1


class TestMySQLStatementParser:
    """Test MySQL-specific statement parsing."""

    def test_simple_sql_split(self):
        """Test simple SQL statement splitting."""
        sql = "SELECT * FROM table1; SELECT * FROM table2;"
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 2

    def test_delimiter_changes(self):
        """Test DELIMITER statement handling."""
        sql = """DELIMITER //
CREATE PROCEDURE test_proc()
BEGIN
  SELECT 1;
END //
DELIMITER ;"""
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should have: DELIMITER //, CREATE PROCEDURE (with //), DELIMITER ;
        assert len(statements) >= 1
        assert any("CREATE PROCEDURE" in s.upper() for s in statements)

    def test_delimiter_dollar_preserves_inner_semicolons(self):
        """Semicolons inside routines must survive when DELIMITER is not ';'."""
        sql = """DELIMITER $$
CREATE PROCEDURE p(IN x INT)
BEGIN
  DECLARE t INT;
  SET t = x + 1;
  SELECT t;
END$$
DELIMITER ;"""
        tokenizer = MySQLTokenizer(sql)
        parser = MySQLStatementParser(tokenizer.tokenize())
        proc = next(s for s in parser.split_statements() if "CREATE PROCEDURE" in s.upper())
        assert "DECLARE" in proc and "INT;" in proc
        assert "SET" in proc and "SELECT" in proc and "t;" in proc
        assert "$$" not in proc

    def test_stored_procedure_with_begin_end(self):
        """Test stored procedure with BEGIN/END blocks."""
        sql = """CREATE PROCEDURE test()
BEGIN
  SELECT 1;
  SELECT 2;
END;"""
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement (entire procedure)
        assert len(statements) == 1

    def test_case_expression_in_select(self):
        """Test CASE expression in SELECT doesn't affect block depth."""
        sql = """SELECT 
  CASE WHEN status = 1 THEN 'active' 
       ELSE 'inactive' 
  END 
FROM users;"""
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement
        assert len(statements) == 1

    def test_nested_begin_end_in_procedure(self):
        """Test nested BEGIN/END blocks in stored procedure."""
        sql = """CREATE PROCEDURE nested_test()
BEGIN
  BEGIN
    SELECT 1;
  END;
  BEGIN
    SELECT 2;
  END;
END;"""
        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement (entire procedure)
        assert len(statements) == 1
