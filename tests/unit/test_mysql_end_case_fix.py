"""Comprehensive tests for MySQL END CASE fix.

This module tests the fix for the bug where CASE in 'END CASE' incorrectly
increased block depth because _last_token_is("END") was checking after the
current CASE token was already added to context.tokens.
"""

import pytest

from dblift.core.sql_parser.parser_context import ParserContext
from dblift.db.plugins.mysql.parser.mysql_statement_parser import MySQLStatementParser
from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer


class TestMySQLEndCaseFix:
    """Test END CASE handling after fix."""

    def test_simple_end_case(self):
        """Test simple CASE statement with END CASE."""
        sql = """CREATE PROCEDURE test()
BEGIN
  CASE x
    WHEN 1 THEN SELECT 'one';
  END CASE;
END;"""

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one complete statement
        assert len(statements) == 1
        assert "CREATE PROCEDURE" in statements[0].upper()
        assert "END CASE" in statements[0].upper()

    def test_multiple_end_case(self):
        """Test procedure with multiple CASE statements."""
        sql = """CREATE PROCEDURE multi()
BEGIN
  CASE x
    WHEN 1 THEN SELECT 'one';
  END CASE;
  
  CASE y
    WHEN 2 THEN SELECT 'two';
  END CASE;
END;"""

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one complete statement
        assert len(statements) == 1
        assert statements[0].count("END CASE") == 2

    def test_nested_case_statements(self):
        """Test nested CASE statements."""
        sql = """CREATE PROCEDURE nested()
BEGIN
  CASE x
    WHEN 1 THEN
      CASE y
        WHEN 'a' THEN SELECT 'one-a';
        WHEN 'b' THEN SELECT 'one-b';
      END CASE;
  END CASE;
END;"""

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one complete statement
        assert len(statements) == 1
        assert statements[0].count("END CASE") == 2

    def test_case_with_multiple_whens(self):
        """Test CASE with multiple WHEN clauses."""
        sql = """CREATE PROCEDURE test()
BEGIN
  CASE status
    WHEN 1 THEN SELECT 'active';
    WHEN 2 THEN SELECT 'inactive';
    WHEN 3 THEN SELECT 'pending';
    ELSE SELECT 'unknown';
  END CASE;
END;"""

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1

    def test_case_expression_not_affected(self):
        """Test that CASE expressions (not statements) are handled correctly."""
        sql = """SELECT 
  CASE 
    WHEN x = 1 THEN 'one'
    WHEN x = 2 THEN 'two'
    ELSE 'other'
  END AS result
FROM table1;"""

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should be one statement
        assert len(statements) == 1

    def test_case_in_stored_function(self):
        """Test CASE in stored function."""
        sql = """CREATE FUNCTION get_status(x INT)
RETURNS VARCHAR(20)
BEGIN
  CASE x
    WHEN 1 THEN RETURN 'active';
    WHEN 2 THEN RETURN 'inactive';
  END CASE;
END;"""

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1

    def test_case_with_delimiter_change(self):
        """Test CASE with DELIMITER statement."""
        sql = """DELIMITER //
CREATE PROCEDURE test()
BEGIN
  CASE x
    WHEN 1 THEN SELECT 'one';
  END CASE;
END //
DELIMITER ;"""

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should have procedure statement
        proc_stmt = None
        for stmt in statements:
            if "CREATE PROCEDURE" in stmt.upper():
                proc_stmt = stmt
                break

        assert proc_stmt is not None
        assert "END CASE" in proc_stmt.upper()

    def test_case_with_begin_end_blocks(self):
        """Test CASE with nested BEGIN/END blocks."""
        sql = """CREATE PROCEDURE complex()
BEGIN
  CASE x
    WHEN 1 THEN
      BEGIN
        SELECT 'one';
        SELECT 'uno';
      END;
    WHEN 2 THEN
      BEGIN
        SELECT 'two';
        SELECT 'dos';
      END;
  END CASE;
END;"""

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        assert len(statements) == 1

    def test_preceded_by_end_with_comments(self):
        """Test that _preceded_by_end works with comments between END and CASE."""
        sql = """CREATE PROCEDURE test()
BEGIN
  CASE x
    WHEN 1 THEN SELECT 'one';
  END /* comment */ CASE;
END;"""

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should handle comments correctly
        assert len(statements) == 1
