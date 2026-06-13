"""Test for Oracle FOR loop keyword limit bug fix.

This test specifically verifies the fix for the bug in _preceded_by_for_or_while
where the safety check was counting total keywords instead of keywords checked,
causing FOR...LOOP detection to fail in statements with 16+ total keywords.
"""

import pytest

from db.plugins.oracle.parser.oracle_parser import OracleParser


@pytest.mark.unit
class TestOracleForLoopKeywordLimitFix:
    """Test that FOR...LOOP detection works with many keywords in the statement."""

    def test_for_loop_with_exactly_16_keywords_before_for(self):
        """Test FOR loop detection with exactly 16 keywords before FOR.

        This is the edge case where the old buggy code would start failing.
        """
        parser = OracleParser()

        # Craft SQL with exactly 16 keywords before FOR keyword
        sql = """
        CREATE OR REPLACE PROCEDURE test_proc AS
            v_count NUMBER;
            v_sum NUMBER;
            v_avg NUMBER;
        BEGIN
            SELECT COUNT(*), SUM(value), AVG(value)
            INTO v_count, v_sum, v_avg
            FROM table1
            WHERE active = 1;
            
            FOR rec IN (SELECT id FROM table2) LOOP
                UPDATE table2 SET processed = 1 WHERE id = rec.id;
            END LOOP;
        END;
        /
        """

        statements = parser.split_statements(sql)

        # Should be one statement (the entire procedure)
        assert len(statements) == 1
        assert "FOR rec IN" in statements[0]
        assert "END LOOP" in statements[0]

    def test_for_loop_with_20_keywords_before_for(self):
        """Test FOR loop detection with 20+ keywords before FOR.

        With the bug, this would always fail because the total keyword count
        would exceed 15 on the first iteration and break immediately.
        """
        parser = OracleParser()

        # SQL with many keywords before the FOR loop
        sql = """
        CREATE OR REPLACE PROCEDURE complex_proc AS
            v1 NUMBER;
            v2 VARCHAR2(100);
            v3 DATE;
            v4 BOOLEAN;
        BEGIN
            SELECT column1, column2, column3
            INTO v1, v2, v3
            FROM table1
            WHERE id = 1
            AND status = 'ACTIVE'
            AND created_date > SYSDATE - 30;
            
            FOR rec IN (
                SELECT id, name
                FROM table2
                WHERE category = 'TEST'
            ) LOOP
                INSERT INTO log_table VALUES (rec.id, rec.name);
            END LOOP;
        END;
        /
        """

        statements = parser.split_statements(sql)

        # Should be one statement (the entire procedure)
        assert len(statements) == 1
        assert "FOR rec IN" in statements[0]
        assert "END LOOP" in statements[0]
        # Verify the INSERT inside the loop is included
        assert "INSERT INTO log_table" in statements[0]

    def test_for_loop_with_complex_subquery_many_keywords(self):
        """Test FOR loop where the subquery itself has many keywords.

        This is the scenario mentioned in the bug report:
        FOR rec IN (SELECT ... UNION SELECT ...) LOOP
        """
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PROCEDURE union_query_proc AS
        BEGIN
            FOR rec IN (
                SELECT id, name, value, category, status, created_date
                FROM table1
                WHERE active = 1
                AND status IN ('ACTIVE', 'PENDING', 'PROCESSING')
                UNION ALL
                SELECT id, name, value, category, status, created_date
                FROM table2
                WHERE archived = 0
                AND modified_date > SYSDATE - 60
                ORDER BY id
            ) LOOP
                DBMS_OUTPUT.PUT_LINE('Processing: ' || rec.name);
            END LOOP;
        END;
        /
        """

        statements = parser.split_statements(sql)

        # Should be one statement (the entire procedure)
        assert len(statements) == 1
        assert "FOR rec IN" in statements[0]
        assert "UNION ALL" in statements[0]
        assert "END LOOP" in statements[0]

    def test_while_loop_with_many_keywords(self):
        """Test WHILE loop detection also works with many keywords.

        The fix applies to both FOR and WHILE loops.
        """
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PROCEDURE while_test AS
            v_counter NUMBER := 0;
            v_sum NUMBER := 0;
            v_avg NUMBER := 0;
        BEGIN
            SELECT COUNT(*), SUM(value), AVG(value)
            INTO v_counter, v_sum, v_avg
            FROM table1
            WHERE active = 1
            AND status = 'PENDING'
            AND created_date > SYSDATE - 30;
            
            WHILE v_counter > 0 LOOP
                v_counter := v_counter - 1;
                DBMS_OUTPUT.PUT_LINE(v_counter);
            END LOOP;
        END;
        /
        """

        statements = parser.split_statements(sql)

        # Should be one statement (the entire procedure)
        assert len(statements) == 1
        # Note: Tokenization removes spaces around operators
        assert "WHILE v_counter" in statements[0] and "LOOP" in statements[0]
        assert "END LOOP" in statements[0]

    def test_for_loop_does_not_increase_depth_after_end(self):
        """Test that LOOP after END doesn't incorrectly increase depth.

        This ensures the fix doesn't break the existing logic that stops
        at END, BEGIN, THEN, ELSE keywords.
        """
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PROCEDURE test_proc AS
        BEGIN
            IF some_condition THEN
                DBMS_OUTPUT.PUT_LINE('True');
            END IF;
            
            -- This LOOP should not be detected as part of a FOR...LOOP
            -- because we stopped at END IF above
            FOR rec IN (SELECT id FROM table1) LOOP
                NULL;
            END LOOP;
        END;
        /
        """

        statements = parser.split_statements(sql)

        # Should be one statement (the entire procedure)
        assert len(statements) == 1
        assert "END IF" in statements[0]
        assert "FOR rec IN" in statements[0]
        assert "END LOOP" in statements[0]

    def test_create_synonym_for_not_interpreted_as_loop(self):
        """Test that CREATE OR REPLACE SYNONYM ... FOR is not interpreted as a FOR loop.

        This was a bug where FOR in regular SQL statements (not PL/SQL) was
        incorrectly increasing block depth, causing statement splitting to fail.
        """
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE SYNONYM servers FOR dbops_inventory.servers;
        CREATE OR REPLACE SYNONYM instances FOR dbops_inventory.instances;
        CREATE OR REPLACE SYNONYM db FOR dbops_inventory.db;
        """

        statements = parser.split_statements(sql)

        # Should be 3 separate statements
        assert len(statements) == 3
        assert "SYNONYM servers" in statements[0]
        assert "SYNONYM instances" in statements[1]
        assert "SYNONYM db" in statements[2]

    def test_select_for_update_not_interpreted_as_loop(self):
        """Test that SELECT ... FOR UPDATE is not interpreted as a FOR loop."""
        parser = OracleParser()

        sql = """
        SELECT id, name FROM employees WHERE dept_id = 10 FOR UPDATE;
        UPDATE employees SET salary = salary * 1.1 WHERE dept_id = 10;
        """

        statements = parser.split_statements(sql)

        # Should be 2 separate statements
        assert len(statements) == 2
        assert "FOR UPDATE" in statements[0]
        assert "UPDATE employees" in statements[1]

    def test_mixed_synonym_and_plsql_with_for_loop(self):
        """Test that mixing regular SQL with FOR and PL/SQL FOR loops works correctly."""
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE SYNONYM emp FOR hr.employees;

        CREATE OR REPLACE TRIGGER trg_audit
            BEFORE INSERT ON audit_log
            FOR EACH ROW
        BEGIN
            FOR i IN 1..5 LOOP
                NULL;
            END LOOP;
        END;
        /

        SELECT * FROM emp FOR UPDATE;
        """

        statements = parser.split_statements(sql)

        # Should be 3 statements: SYNONYM, TRIGGER, SELECT
        assert len(statements) == 3
        assert "SYNONYM emp FOR" in statements[0]
        assert "TRIGGER trg_audit" in statements[1]
        assert "FOR i IN 1..5 LOOP" in statements[1]
        assert "END LOOP" in statements[1]
        assert "FOR UPDATE" in statements[2]
