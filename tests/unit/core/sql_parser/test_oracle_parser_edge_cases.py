"""
Comprehensive edge case tests for Oracle parser.

These tests focus on challenging the parser with complex scenarios:
- Multiple DDL statements without PL/SQL blocks
- Mixed DDL and PL/SQL blocks
- Complex string literals with special characters
- Nested comments and delimiters
- Statement boundary detection issues
"""

import pytest

from db.plugins.oracle.parser.oracle_parser import OracleParser


@pytest.mark.unit
class TestOracleParserEdgeCases:
    """Test Oracle parser with challenging edge cases."""

    def test_multiple_create_statements_semicolon_delimited(self):
        """Test that multiple CREATE statements separated by semicolons are split correctly.

        This is the bug found in Oracle introspection tests where CREATE TABLE + multiple
        CREATE INDEX statements were grouped together instead of being split.
        """
        parser = OracleParser()

        sql = """
        CREATE TABLE products (
            id NUMBER PRIMARY KEY,
            name VARCHAR2(100) NOT NULL,
            price NUMBER(10, 2) NOT NULL
        );

        CREATE INDEX idx_products_name ON products(name);
        CREATE INDEX idx_products_price ON products(price);
        CREATE UNIQUE INDEX idx_products_name_lower ON products(LOWER(name));
        """

        statements = parser.split_statements(sql)

        # Should split into 4 statements
        assert len(statements) == 4, f"Expected 4 statements, got {len(statements)}"

        # Check each statement is separate
        assert "CREATE TABLE products" in statements[0]
        assert "CREATE INDEX idx_products_name" in statements[1]
        assert "CREATE INDEX idx_products_price" in statements[2]
        assert "CREATE UNIQUE INDEX idx_products_name_lower" in statements[3]

        # Ensure no statement contains multiple CREATE commands
        for stmt in statements:
            create_count = stmt.upper().count("CREATE")
            assert (
                create_count == 1
            ), f"Statement should have exactly 1 CREATE, found {create_count}: {stmt[:100]}"

    def test_semicolons_in_string_literals(self):
        """Test that semicolons inside string literals don't split statements."""
        parser = OracleParser()

        sql = """
        INSERT INTO messages VALUES (1, 'This has a semicolon; in the string');
        INSERT INTO messages VALUES (2, 'Another; with; multiple; semicolons');
        """

        statements = parser.split_statements(sql)

        assert len(statements) == 2
        assert "This has a semicolon; in the string" in statements[0]
        assert "Another; with; multiple; semicolons" in statements[1]

    def test_semicolons_in_comments(self):
        """Test that semicolons in comments don't split statements."""
        parser = OracleParser()

        sql = """
        CREATE TABLE test1 (id NUMBER); -- This is a comment; with semicolons;
        CREATE TABLE test2 (name VARCHAR2(100));
        /* Block comment with semicolons;
           and multiple lines;
        */
        CREATE TABLE test3 (value NUMBER);
        """

        statements = parser.split_statements(sql)

        assert len(statements) == 3
        assert "CREATE TABLE test1" in statements[0]
        assert "CREATE TABLE test2" in statements[1]
        assert "CREATE TABLE test3" in statements[2]

    def test_q_quote_literals(self):
        """Test Oracle Q-quote alternative quote delimiters."""
        parser = OracleParser()

        sql = """
        INSERT INTO messages VALUES (1, Q'[This has 'quotes' and semicolons; no problem]');
        INSERT INTO messages VALUES (2, Q'!Multiple delimiters work!');
        INSERT INTO messages VALUES (3, Q'{Curly braces; and 'quotes'}');
        """

        statements = parser.split_statements(sql)

        # All three should be separate statements
        assert len(statements) == 3
        # Q-quotes should be preserved
        assert "Q'[" in statements[0]
        assert "Q'!" in statements[1]
        assert "Q'{" in statements[2]

    def test_slash_delimiter_with_regular_sql(self):
        """Test that slash delimiter only terminates PL/SQL, not regular SQL."""
        parser = OracleParser()

        sql = """
        CREATE TABLE table1 (id NUMBER);
        CREATE TABLE table2 (name VARCHAR2(100));

        CREATE OR REPLACE PROCEDURE test_proc AS
        BEGIN
            NULL;
        END;
        /

        CREATE INDEX idx_table1 ON table1(id);
        CREATE INDEX idx_table2 ON table2(name);
        """

        statements = parser.split_statements(sql)

        # Should have: 2 tables + 1 procedure + 2 indexes = 5 statements
        assert len(statements) >= 4, f"Expected at least 4 statements, got {len(statements)}"

        # Check procedure is one statement
        proc_statements = [s for s in statements if "CREATE OR REPLACE PROCEDURE" in s.upper()]
        assert len(proc_statements) == 1

        # Check indexes are separate
        index_statements = [s for s in statements if "CREATE INDEX" in s.upper()]
        assert len(index_statements) == 2

    def test_nested_begin_end_blocks(self):
        """Test nested BEGIN/END blocks are handled correctly."""
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PROCEDURE nested_test AS
        BEGIN
            -- Outer block
            BEGIN
                -- Inner block 1
                NULL;
            END;

            BEGIN
                -- Inner block 2
                BEGIN
                    -- Nested inner block
                    NULL;
                END;
            END;
        END nested_test;
        /

        CREATE TABLE after_nested (id NUMBER);
        """

        statements = parser.split_statements(sql)

        # Should have procedure + table = 2 statements
        assert len(statements) >= 2

        # Procedure should be complete with all nested blocks
        proc = [s for s in statements if "CREATE OR REPLACE PROCEDURE" in s][0]
        assert proc.count("BEGIN") == 4  # Outer + 3 inner blocks
        assert proc.count("END") == 4  # Matching ENDs

    def test_case_expression_with_end_keyword(self):
        """Test that END in CASE expressions doesn't break block parsing."""
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PROCEDURE test_case AS
            v_status VARCHAR2(20);
        BEGIN
            v_status := CASE
                WHEN 1=1 THEN 'active'
                ELSE 'inactive'
            END;

            v_status := CASE
                WHEN 2=2 THEN 'pending'
                WHEN 3=3 THEN 'done'
                ELSE 'unknown'
            END;
        END test_case;
        /
        """

        statements = parser.split_statements(sql)

        assert len(statements) == 1
        # Should have 2 CASE ENDs + 1 procedure END = 3 ENDs total
        assert statements[0].upper().count("END") >= 3

    def test_string_with_escaped_quotes(self):
        """Test strings with escaped quotes (doubled single quotes)."""
        parser = OracleParser()

        sql = """
        INSERT INTO test VALUES (1, 'This is O''Reilly''s book');
        INSERT INTO test VALUES (2, 'Don''t split; this statement');
        INSERT INTO test VALUES (3, 'It''s; working; isn''t; it?');
        """

        statements = parser.split_statements(sql)

        assert len(statements) == 3
        # Check escaped quotes are preserved
        assert "O''Reilly''s" in statements[0]
        assert "Don''t" in statements[1]
        assert "isn''t" in statements[2]

    def test_multiline_string_literals(self):
        """Test multiline string literals."""
        parser = OracleParser()

        sql = """
        INSERT INTO test VALUES (1, 'This is
        a multiline
        string with; semicolons');
        INSERT INTO test VALUES (2, 'Another one');
        """

        statements = parser.split_statements(sql)

        assert len(statements) == 2

    def test_mixed_slash_and_semicolon(self):
        """Test file with mix of slash and semicolon delimiters."""
        parser = OracleParser()

        sql = """
        CREATE TABLE t1 (id NUMBER);

        CREATE OR REPLACE FUNCTION get_count RETURN NUMBER AS
        BEGIN
            RETURN 1;
        END;
        /

        CREATE TABLE t2 (name VARCHAR2(100));

        CREATE OR REPLACE PROCEDURE do_something AS
        BEGIN
            NULL;
        END;
        /

        CREATE INDEX idx_t1 ON t1(id);
        """

        statements = parser.split_statements(sql)

        # Should have: 2 tables + 1 function + 1 procedure + 1 index = 5 statements
        assert len(statements) >= 5, f"Expected at least 5 statements, got {len(statements)}"

        # Count each type
        tables = sum(1 for s in statements if "CREATE TABLE" in s.upper())
        functions = sum(1 for s in statements if "CREATE OR REPLACE FUNCTION" in s.upper())
        procedures = sum(1 for s in statements if "CREATE OR REPLACE PROCEDURE" in s.upper())
        indexes = sum(1 for s in statements if "CREATE INDEX" in s.upper())

        assert tables == 2
        assert functions == 1
        assert procedures == 1
        assert indexes == 1

    def test_function_based_index(self):
        """Test function-based index with expressions."""
        parser = OracleParser()

        sql = """
        CREATE TABLE orders (
            id NUMBER,
            order_date TIMESTAMP
        );

        CREATE INDEX idx_orders_year ON orders(EXTRACT(YEAR FROM order_date));
        CREATE INDEX idx_orders_month ON orders(EXTRACT(MONTH FROM order_date));
        """

        statements = parser.split_statements(sql)

        assert len(statements) == 3
        assert "CREATE TABLE orders" in statements[0]
        assert "EXTRACT(YEAR FROM order_date)" in statements[1]
        assert "EXTRACT(MONTH FROM order_date)" in statements[2]

    def test_complex_plsql_with_cursors(self):
        """Test PL/SQL with cursor declarations and loops."""
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PROCEDURE process_data AS
            CURSOR c1 IS SELECT * FROM table1;
            CURSOR c2 IS SELECT * FROM table2 WHERE id > 100;
        BEGIN
            FOR rec IN c1 LOOP
                -- Process
                NULL;
            END LOOP;

            FOR rec IN c2 LOOP
                BEGIN
                    -- Nested block
                    NULL;
                END;
            END LOOP;
        END process_data;
        /

        CREATE SEQUENCE after_cursor START WITH 1;
        """

        statements = parser.split_statements(sql)

        assert len(statements) >= 2
        # Procedure should have all CURSOR declarations and loops
        proc = [s for s in statements if "CREATE OR REPLACE PROCEDURE" in s][0]
        assert "CURSOR c1" in proc
        assert "CURSOR c2" in proc
        assert proc.count("END LOOP") == 2

    def test_exception_handling(self):
        """Test exception handling blocks."""
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PROCEDURE safe_op AS
        BEGIN
            -- Main block
            NULL;
        EXCEPTION
            WHEN NO_DATA_FOUND THEN
                NULL;
            WHEN OTHERS THEN
                BEGIN
                    -- Nested exception handler
                    NULL;
                EXCEPTION
                    WHEN OTHERS THEN
                        NULL;
                END;
        END safe_op;
        /
        """

        statements = parser.split_statements(sql)

        assert len(statements) == 1
        # Should have proper EXCEPTION block structure
        assert "EXCEPTION" in statements[0]
        assert "WHEN NO_DATA_FOUND" in statements[0]
        assert "WHEN OTHERS" in statements[0]

    def test_package_spec_and_body(self):
        """Test package specification and body are separate."""
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PACKAGE test_pkg AS
            FUNCTION get_val RETURN NUMBER;
            PROCEDURE set_val(p_val NUMBER);
        END test_pkg;
        /

        CREATE OR REPLACE PACKAGE BODY test_pkg AS
            FUNCTION get_val RETURN NUMBER IS
            BEGIN
                RETURN 42;
            END get_val;

            PROCEDURE set_val(p_val NUMBER) IS
            BEGIN
                NULL;
            END set_val;
        END test_pkg;
        /
        """

        statements = parser.split_statements(sql)

        assert len(statements) == 2
        # First should be package spec
        assert "PACKAGE test_pkg AS" in statements[0]
        # Second should be package body
        assert "PACKAGE BODY test_pkg" in statements[1]

    def test_comments_everywhere(self):
        """Test comments in various locations."""
        parser = OracleParser()

        sql = """
        -- Leading comment
        CREATE TABLE test1 (
            -- Comment before column
            id NUMBER, -- inline comment
            -- Comment between columns
            name VARCHAR2(100) -- another inline
            -- Comment before closing paren
        ); -- trailing comment

        /* Block comment before statement */
        CREATE /* mid-statement comment */ TABLE test2 (id NUMBER);

        /* Multi-line
           block comment
           with semicolons;
           and slashes /
        */
        CREATE TABLE test3 (id NUMBER);
        """

        statements = parser.split_statements(sql)

        # Should extract 3 CREATE TABLE statements
        assert len(statements) == 3
        for stmt in statements:
            assert "CREATE TABLE" in stmt.upper()

    def test_empty_statements_filtered(self):
        """Test that empty statements and whitespace are filtered out."""
        parser = OracleParser()

        sql = """


        CREATE TABLE test1 (id NUMBER);


        ;

        CREATE TABLE test2 (name VARCHAR2(100));


        -- Just a comment


        CREATE TABLE test3 (value NUMBER);


        """

        statements = parser.split_statements(sql)

        # Should only get the 3 CREATE TABLE statements
        assert len(statements) == 3
        for stmt in statements:
            assert stmt.strip()  # No empty statements
            assert "CREATE TABLE" in stmt.upper()

    def test_trigger_with_when_clause(self):
        """Test trigger with WHEN clause."""
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE TRIGGER trg_test
            BEFORE INSERT ON test_table
            FOR EACH ROW
            WHEN (NEW.id IS NULL)
        BEGIN
            :NEW.id := seq.NEXTVAL;
        END;
        /

        CREATE INDEX idx_after_trigger ON test_table(id);
        """

        statements = parser.split_statements(sql)

        assert len(statements) == 2
        # Trigger should include WHEN clause
        assert "WHEN (NEW.id IS NULL)" in statements[0]
        # Index should be separate
        assert "CREATE INDEX" in statements[1]

    def test_for_loop_with_complex_subquery_many_keywords(self):
        """Test FOR loop with complex subquery containing 16+ keywords.

        This tests the fix for the bug in _preceded_by_for_or_while where
        the safety check was counting total keywords instead of keywords checked,
        causing incorrect statement splitting for complex FOR loops.
        """
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PROCEDURE process_data AS
        BEGIN
            FOR rec IN (
                SELECT t1.id, t1.name, t1.value, t2.category, t2.status
                FROM table1 t1
                INNER JOIN table2 t2 ON t1.id = t2.id
                WHERE t1.active = 1
                AND t2.status IN ('ACTIVE', 'PENDING')
                UNION ALL
                SELECT t3.id, t3.name, t3.value, t3.category, t3.status
                FROM table3 t3
                WHERE t3.archived = 0
                AND t3.created_date > SYSDATE - 30
                ORDER BY id
            ) LOOP
                DBMS_OUTPUT.PUT_LINE(rec.name || ': ' || rec.value);
            END LOOP;
        END;
        /
        """

        statements = parser.split_statements(sql)

        # Should be one statement (the entire procedure)
        assert len(statements) == 1, f"Expected 1 statement, got {len(statements)}"

        # Verify the entire FOR loop is intact
        assert "FOR rec IN" in statements[0]
        assert "LOOP" in statements[0]
        assert "END LOOP" in statements[0]
        assert "UNION ALL" in statements[0]

    def test_nested_for_loops_with_complex_queries(self):
        """Test nested FOR loops with complex subqueries.

        This ensures the fix handles multiple FOR...LOOP constructs
        with many keywords correctly.
        """
        parser = OracleParser()

        sql = """
        CREATE OR REPLACE PROCEDURE nested_loop_test AS
        BEGIN
            FOR outer_rec IN (
                SELECT dept_id, dept_name
                FROM departments
                WHERE active = 1
                AND region IN ('NORTH', 'SOUTH', 'EAST', 'WEST')
            ) LOOP
                FOR inner_rec IN (
                    SELECT emp_id, emp_name, salary, bonus, commission
                    FROM employees
                    WHERE dept_id = outer_rec.dept_id
                    AND hire_date > ADD_MONTHS(SYSDATE, -12)
                    AND status = 'ACTIVE'
                    ORDER BY salary DESC
                ) LOOP
                    UPDATE employee_summary
                    SET processed = 1
                    WHERE emp_id = inner_rec.emp_id;
                END LOOP;
            END LOOP;
        END;
        /
        """

        statements = parser.split_statements(sql)

        # Should be one statement (the entire procedure)
        assert len(statements) == 1, f"Expected 1 statement, got {len(statements)}"

        # Verify both FOR loops are intact
        assert statements[0].count("FOR") == 2
        # LOOP appears 4 times: "FOR ... LOOP" twice + "END LOOP" twice
        assert statements[0].count("LOOP") == 4
        assert statements[0].count("END LOOP") == 2
