"""Unit tests for MySQL stored program flag reset bug fix.

Tests for the fix where in_stored_program flag was not reset between
statements, causing subsequent BEGIN statements to be incorrectly treated
as block starts.
"""

import pytest

from dblift.db.plugins.mysql.parser.mysql_statement_parser import MySQLStatementParser
from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer


class TestMySQLStoredProgramFlagReset:
    """Test in_stored_program flag reset between statements."""

    def test_stored_procedure_followed_by_transaction(self):
        """Test stored procedure followed by BEGIN TRANSACTION.

        This tests the bug where in_stored_program was not reset after
        parsing a stored procedure, causing subsequent BEGIN TRANSACTION
        to incorrectly increase block depth.
        """
        sql = """
        DELIMITER //
        CREATE PROCEDURE test_proc()
        BEGIN
            SELECT 1;
        END //
        DELIMITER ;
        
        BEGIN;
        INSERT INTO test VALUES (1);
        COMMIT;
        """

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should have 4 statements:
        # 1. CREATE PROCEDURE (entire procedure)
        # 2. BEGIN (transaction start)
        # 3. INSERT
        # 4. COMMIT
        assert len(statements) == 4, f"Expected 4 statements, got {len(statements)}"

        # Verify procedure is intact
        assert "CREATE PROCEDURE" in statements[0].upper()
        assert "BEGIN" in statements[0].upper()
        assert "END" in statements[0].upper()

        # Verify transaction statements are separate
        # The BEGIN should be a separate statement (transaction start)
        begin_found = False
        for stmt in statements[1:]:
            if "BEGIN" in stmt.upper() and "CREATE" not in stmt.upper():
                begin_found = True
                # Should be just BEGIN, not part of a procedure
                assert "PROCEDURE" not in stmt.upper()
                break

        assert begin_found, "BEGIN transaction statement not found after procedure"

    def test_multiple_stored_procedures(self):
        """Test multiple stored procedures in sequence.

        Verifies that in_stored_program is reset between procedures.
        """
        sql = """
        DELIMITER //
        CREATE PROCEDURE proc1()
        BEGIN
            SELECT 1;
        END //
        
        CREATE PROCEDURE proc2()
        BEGIN
            SELECT 2;
        END //
        DELIMITER ;
        """

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should have 2 statements (one for each procedure)
        assert len(statements) == 2

        # Both should be complete procedures
        assert "CREATE PROCEDURE" in statements[0].upper()
        assert "PROC1" in statements[0].upper()
        assert "CREATE PROCEDURE" in statements[1].upper()
        assert "PROC2" in statements[1].upper()

    def test_stored_function_followed_by_select(self):
        """Test stored function followed by SELECT.

        Ensures in_stored_program doesn't affect subsequent regular SQL.
        """
        sql = """
        DELIMITER //
        CREATE FUNCTION calc_sum(a INT, b INT) RETURNS INT
        BEGIN
            RETURN a + b;
        END //
        DELIMITER ;
        
        SELECT calc_sum(1, 2);
        """

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should have 2 statements: function and select
        assert len(statements) == 2

        # First should be function
        assert "CREATE FUNCTION" in statements[0].upper()

        # Second should be SELECT
        assert "SELECT" in statements[1].upper()
        assert "CREATE" not in statements[1].upper()

    def test_trigger_followed_by_insert(self):
        """Test trigger followed by INSERT statement."""
        sql = """
        DELIMITER //
        CREATE TRIGGER before_insert_test
        BEFORE INSERT ON test_table
        FOR EACH ROW
        BEGIN
            SET NEW.created_at = NOW();
        END //
        DELIMITER ;
        
        INSERT INTO test_table (name) VALUES ('test');
        """

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should have 2 statements: trigger and insert
        assert len(statements) == 2

        # First should be trigger
        assert "CREATE TRIGGER" in statements[0].upper()

        # Second should be INSERT
        assert "INSERT" in statements[1].upper()
        assert "TRIGGER" not in statements[1].upper()

    def test_event_followed_by_sql(self):
        """Test event followed by regular SQL."""
        sql = """
        DELIMITER //
        CREATE EVENT test_event
        ON SCHEDULE EVERY 1 DAY
        DO
        BEGIN
            DELETE FROM logs WHERE created_at < DATE_SUB(NOW(), INTERVAL 30 DAY);
        END //
        DELIMITER ;
        
        SELECT * FROM logs;
        """

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should have 2 statements: event and select
        assert len(statements) == 2

        # First should be event
        assert "CREATE EVENT" in statements[0].upper()

        # Second should be SELECT
        assert "SELECT" in statements[1].upper()
        assert "EVENT" not in statements[1].upper()

    def test_begin_without_stored_program(self):
        """Test that regular BEGIN still works without stored program.

        This is a baseline test to ensure normal BEGIN behavior is unchanged.
        """
        sql = """
        CREATE TABLE test (id INT);
        BEGIN;
        INSERT INTO test VALUES (1);
        COMMIT;
        """

        tokenizer = MySQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        parser = MySQLStatementParser(tokens)
        statements = parser.split_statements()

        # Should have 4 statements
        assert len(statements) == 4

        # Verify CREATE TABLE
        assert "CREATE TABLE" in statements[0].upper()

        # Verify BEGIN is separate
        assert "BEGIN" in statements[1].upper()
        assert "CREATE" not in statements[1].upper()
        assert "INSERT" not in statements[1].upper()
