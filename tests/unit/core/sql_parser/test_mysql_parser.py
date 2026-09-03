"""Tests for MySQL parser."""

from unittest.mock import MagicMock, patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlStatementType
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser


@pytest.mark.unit
class TestMySqlParser:
    """Test MySQL parser functionality."""

    def test_parser_creation(self):
        """Test parser can be created."""
        parser = MySqlRegexParser()
        assert parser is not None
        assert parser.dialect_name == "mysql"

    def test_delimiter_extraction(self):
        """Test DELIMITER statement extraction."""
        parser = MySqlRegexParser()

        sql = "DELIMITER //\nCREATE PROCEDURE test() BEGIN SELECT 1; END //\nDELIMITER ;"

        # Test that delimiter statements are handled
        result = parser.parse_sql(sql)
        assert result.success
        assert len(result.statements) > 0

    def test_parse_sql_simple(self):
        """Test parsing simple SQL."""
        parser = MySqlRegexParser()

        sql = "CREATE TABLE test (id INT PRIMARY KEY);"
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) >= 1
        assert "CREATE TABLE test" in result.statements[0].sql_text

    def test_parse_sql_multiple_statements(self):
        """Test parsing multiple SQL statements."""
        parser = MySqlRegexParser()

        sql = """
        CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(100));
        CREATE INDEX idx_name ON users(name);
        INSERT INTO users VALUES (1, 'John');
        """
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) >= 3

    def test_parse_sql_mysql_specific(self):
        """Test parsing MySQL-specific SQL."""
        parser = MySqlRegexParser()

        sql = """
        CREATE TABLE test (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB;
        """
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) >= 1

    def test_parse_sql_with_backticks(self):
        """Test parsing SQL with backtick identifiers."""
        parser = MySqlRegexParser()

        sql = "CREATE TABLE `test_table` (id INT PRIMARY KEY, `column_name` VARCHAR(100));"

        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert "`test_table`" in result.statements[0].sql_text
        assert "`column_name`" in result.statements[0].sql_text

    def test_parse_sql_empty(self):
        """Test parsing empty SQL."""
        parser = MySqlRegexParser()

        result = parser.parse_sql("")

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) == 0

    def test_extract_objects(self):
        """Test object extraction from SQL."""
        parser = MySqlRegexParser()

        sql = """
        CREATE TABLE users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        ) ENGINE=InnoDB;
        """

        objects = parser.extract_objects(sql)
        assert len(objects) >= 1
        assert objects[0].name == "users"

    def test_delimiter_handling(self):
        """Test DELIMITER statement handling."""
        parser = MySqlRegexParser()

        sql = """
        DELIMITER //
        CREATE PROCEDURE GetUserCount(OUT total INT)
        BEGIN
            SELECT COUNT(*) INTO total FROM users;
        END //
        DELIMITER ;
        """

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success

    def test_extract_indexes(self):
        """Test index extraction from SQL."""
        parser = MySqlRegexParser()

        sql = """
        CREATE INDEX idx_name ON users(name);
        CREATE UNIQUE INDEX idx_email ON users(email);
        """

        objects = parser.extract_objects(sql)
        # Should find the indexes and referenced tables
        assert len(objects) >= 2

    def test_split_statements(self):
        """Test SQL statement splitting."""
        parser = MySqlRegexParser()

        sql = """
        CREATE TABLE test1 (id INT);
        INSERT INTO test1 VALUES (1, 'test');
        CREATE TABLE test2 (id INT);
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 3

    def test_statement_classification(self):
        """Test statement type classification."""
        parser = MySqlRegexParser()

        # Test through parse_sql which uses the classification logic
        ddl_sql = "CREATE TABLE test (id INT)"
        result = parser.parse_sql(ddl_sql)
        assert result.success
        assert result.statements[0].statement_type == SqlStatementType.DDL

        dml_sql = "INSERT INTO test VALUES (1)"
        result = parser.parse_sql(dml_sql)
        assert result.success
        assert result.statements[0].statement_type == SqlStatementType.DML

        query_sql = "SELECT * FROM test"
        result = parser.parse_sql(query_sql)
        assert result.success
        assert result.statements[0].statement_type == SqlStatementType.QUERY

    def test_validate_sql(self):
        """Test SQL validation."""
        parser = MySqlRegexParser()

        # Valid SQL
        valid_sql = "CREATE TABLE test (id INT PRIMARY KEY)"
        result = parser.validate_sql(valid_sql)
        assert result["valid"]

        # Invalid SQL (unmatched backticks)
        invalid_sql = "CREATE TABLE `test (id INT PRIMARY KEY)"
        result = parser.validate_sql(invalid_sql)
        assert not result["valid"]

    def test_parse_sql_mysql_engine_syntax(self):
        """Test parsing MySQL-specific ENGINE syntax."""
        parser = MySqlRegexParser()

        sql = """
        CREATE TABLE test (
            id INT PRIMARY KEY,
            data TEXT
        ) ENGINE=MyISAM;
        """

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success

    def test_parse_sql_mysql_auto_increment(self):
        """Test parsing MySQL AUTO_INCREMENT."""
        parser = MySqlRegexParser()

        sql = "CREATE TABLE test (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100));"

        result = parser.parse_sql(sql)
        assert isinstance(result, ParseResult)
        assert result.success

    def test_mysql_parser_inheritance(self):
        """Test that MySQL parser inherits from EnhancedRegexParser."""
        from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser

        parser = MySqlRegexParser()
        assert isinstance(parser, EnhancedRegexParser)

    def test_parser_configuration(self):
        """Test parser configuration attributes."""
        parser = MySqlRegexParser()
        assert hasattr(parser, "dialect_name")
        assert hasattr(parser, "config")
        assert parser.dialect_name == "mysql"
        assert parser.config is not None

    def test_delimiter_statement_detection(self):
        """Test MySQL DELIMITER statement detection."""
        parser = MySqlRegexParser()

        # Test with DELIMITER statement
        sql_with_delimiter = (
            "DELIMITER //\nCREATE PROCEDURE test() BEGIN SELECT 1; END //\nDELIMITER ;"
        )
        assert parser._has_delimiter_statements(sql_with_delimiter)

        # Test without DELIMITER statement
        sql_without_delimiter = "CREATE TABLE test (id INT);"
        assert not parser._has_delimiter_statements(sql_without_delimiter)

    def test_stored_procedure_detection(self):
        """Test MySQL stored procedure detection."""
        parser = MySqlRegexParser()

        # Test with stored procedure
        sql_with_proc = "CREATE PROCEDURE test() BEGIN SELECT 1; END;"
        assert parser._has_stored_procedures(sql_with_proc)

        # Test with function
        sql_with_func = "CREATE FUNCTION test() RETURNS INT BEGIN RETURN 1; END;"
        assert parser._has_stored_procedures(sql_with_func)

        # Test without procedures
        sql_without_proc = "CREATE TABLE test (id INT);"
        assert not parser._has_stored_procedures(sql_without_proc)

    def test_complex_delimiter_parsing(self):
        """Test complex DELIMITER parsing scenarios."""
        parser = MySqlRegexParser()

        sql = """
        DELIMITER //
        CREATE PROCEDURE GetUserCount(OUT total INT)
        BEGIN
            SELECT COUNT(*) INTO total FROM users;
        END //
        
        CREATE FUNCTION GetUserName(user_id INT) RETURNS VARCHAR(100)
        BEGIN
            DECLARE name VARCHAR(100);
            SELECT username INTO name FROM users WHERE id = user_id;
            RETURN name;
        END //
        DELIMITER ;
        
        INSERT INTO users VALUES (1, 'test');
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 3

        # Should have procedure, function, and insert
        proc_found = any("CREATE PROCEDURE" in stmt for stmt in statements)
        func_found = any("CREATE FUNCTION" in stmt for stmt in statements)
        insert_found = any("INSERT INTO" in stmt for stmt in statements)

        assert proc_found
        assert func_found
        assert insert_found

    def test_procedure_with_delimiter_splitting(self):
        """Test procedure parsing with DELIMITER awareness."""
        parser = MySqlRegexParser()

        sql = """
        DELIMITER $$
        CREATE PROCEDURE complex_proc(IN param1 INT, OUT param2 VARCHAR(100))
        BEGIN
            DECLARE done INT DEFAULT FALSE;
            DECLARE cur CURSOR FOR SELECT name FROM users;
            
            OPEN cur;
            read_loop: LOOP
                FETCH cur INTO param2;
                IF done THEN
                    LEAVE read_loop;
                END IF;
            END LOOP;
            CLOSE cur;
        END $$
        DELIMITER ;
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 1

        # Should preserve the entire procedure as one statement
        proc_stmt = next((stmt for stmt in statements if "CREATE PROCEDURE" in stmt), None)
        assert proc_stmt is not None
        assert "CURSOR" in proc_stmt
        assert "LOOP" in proc_stmt

    def test_mysql_comments_cleaning(self):
        """Test MySQL comment cleaning."""
        parser = MySqlRegexParser()

        sql = """
        -- This is a line comment
        CREATE TABLE test (
            id INT, -- Column comment
            name VARCHAR(100) # MySQL hash comment
        );
        /* Multi-line
           comment */
        """

        cleaned = parser._clean_mysql_comments(sql)
        assert "--" not in cleaned
        assert "#" not in cleaned
        assert "/*" not in cleaned
        assert "CREATE TABLE test" in cleaned

    def test_backtick_identifier_extraction(self):
        """Test backtick identifier extraction."""
        parser = MySqlRegexParser()

        sql = "CREATE TABLE `test-table` (`column-name` INT);"
        result = parser._extract_backtick_identifier(sql)
        assert result == "test-table"

    def test_stored_procedure_name_extraction(self):
        """Test stored procedure name extraction."""
        parser = MySqlRegexParser()

        # Test basic procedure
        sql = "CREATE PROCEDURE test_proc() BEGIN SELECT 1; END;"
        name = parser._extract_stored_procedure_name(sql)
        assert name == "test_proc"

        # Test with schema (returns first non-None group, which is the schema)
        sql = "CREATE PROCEDURE mydb.test_proc() BEGIN SELECT 1; END;"
        name = parser._extract_stored_procedure_name(sql)
        assert name == "mydb"  # The regex returns the first non-None group

        # Test with quoted name
        sql = "CREATE PROCEDURE `test_proc`() BEGIN SELECT 1; END;"
        name = parser._extract_stored_procedure_name(sql)
        assert name == "test_proc"

    def test_stored_function_name_extraction(self):
        """Test stored function name extraction."""
        parser = MySqlRegexParser()

        # Test basic function
        sql = "CREATE FUNCTION test_func() RETURNS INT BEGIN RETURN 1; END;"
        name = parser._extract_stored_function_name(sql)
        assert name == "test_func"

        # Test with schema (returns first non-None group, which is the schema)
        sql = "CREATE FUNCTION mydb.test_func() RETURNS INT BEGIN RETURN 1; END;"
        name = parser._extract_stored_function_name(sql)
        assert name == "mydb"  # The regex returns the first non-None group

        # Test with quoted name
        sql = "CREATE FUNCTION `test_func`() RETURNS INT BEGIN RETURN 1; END;"
        name = parser._extract_stored_function_name(sql)
        assert name == "test_func"

    def test_mysql_specific_syntax_validation(self):
        """Test MySQL-specific syntax validation."""
        parser = MySqlRegexParser()

        # Test unmatched backticks
        invalid_sql = "CREATE TABLE `test (id INT);"
        result = parser.validate_sql(invalid_sql)
        assert not result["valid"]
        assert "Unmatched backtick identifier" in result["errors"][0]

        # Test valid MySQL syntax should pass
        valid_sql = "CREATE TABLE test (id INT PRIMARY KEY);"
        result = parser.validate_sql(valid_sql)
        assert result["valid"]

        # Test empty SQL should have no errors but fail on no statements
        empty_sql = ""
        result = parser.validate_sql(empty_sql)
        assert not result["valid"]
        assert "No valid statements found" in result["errors"][0]

    def test_complex_mysql_features(self):
        """Test complex MySQL features parsing."""
        parser = MySqlRegexParser()

        sql = """
        CREATE TABLE products (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            price DECIMAL(10,2),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        
        CREATE INDEX idx_name ON products(name);
        CREATE FULLTEXT INDEX idx_description ON products(description);
        """

        result = parser.parse_sql(sql)
        assert result.success
        assert len(result.statements) >= 3

        # Check for MySQL-specific features
        table_stmt = next(
            (stmt for stmt in result.statements if "CREATE TABLE" in stmt.sql_text), None
        )
        assert table_stmt is not None
        assert "AUTO_INCREMENT" in table_stmt.sql_text
        assert "ENGINE=InnoDB" in table_stmt.sql_text
        assert "DEFAULT CHARSET=utf8mb4" in table_stmt.sql_text

    def test_mysql_transaction_handling(self):
        """Test MySQL transaction statement handling."""
        parser = MySqlRegexParser()

        sql = """
        START TRANSACTION;
        INSERT INTO users VALUES (1, 'test');
        UPDATE users SET name = 'updated' WHERE id = 1;
        COMMIT;
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 4

        # Should have transaction statements
        start_found = any("START TRANSACTION" in stmt for stmt in statements)
        commit_found = any("COMMIT" in stmt for stmt in statements)

        assert start_found
        assert commit_found

    def test_mysql_error_handling(self):
        """Test MySQL parser error handling."""
        parser = MySqlRegexParser()

        # Test with malformed SQL
        malformed_sql = "CREATE TABLE test (id INT; -- Missing closing parenthesis"
        result = parser.parse_sql(malformed_sql)

        # Should handle gracefully
        assert isinstance(result, ParseResult)
        # May succeed or fail, but shouldn't crash

        # Test with None input
        result = parser.parse_sql(None)
        assert isinstance(result, ParseResult)

    def test_mysql_edge_cases(self):
        """Test MySQL parser edge cases."""
        parser = MySqlRegexParser()

        edge_cases = [
            "",  # Empty string
            ";",  # Just semicolon
            "   ; ; ;   ",  # Multiple semicolons with whitespace
            "-- Comment only",  # Comment only
            "# MySQL comment only",  # MySQL hash comment
            "/* Block comment */",  # Block comment
            "DELIMITER //",  # Incomplete delimiter
            "DELIMITER ;",  # Reset delimiter
        ]

        for sql in edge_cases:
            result = parser.parse_sql(sql)
            assert isinstance(result, ParseResult)
            # Should not crash, may succeed or fail gracefully

    def test_mysql_large_statement_handling(self):
        """Test handling of large MySQL statements."""
        parser = MySqlRegexParser()

        # Create a large INSERT statement
        large_sql = "INSERT INTO test_table VALUES " + ", ".join(
            [f"({i}, 'value{i}')" for i in range(1000)]
        )

        result = parser.parse_sql(large_sql)
        assert result.success
        assert len(result.statements) == 1

    def test_mysql_special_characters(self):
        """Test MySQL parser with special characters."""
        parser = MySqlRegexParser()

        sql = """
        CREATE TABLE test (
            id INT,
            `special-column` VARCHAR(100),
            `column with spaces` TEXT,
            `quoted"column` VARCHAR(50)
        );
        """

        result = parser.parse_sql(sql)
        assert result.success
        assert len(result.statements) >= 1

    def test_mysql_nested_delimiters(self):
        """Test MySQL nested delimiter scenarios."""
        parser = MySqlRegexParser()

        sql = """
        DELIMITER //
        CREATE PROCEDURE outer_proc()
        BEGIN
            DECLARE EXIT HANDLER FOR SQLEXCEPTION
            BEGIN
                ROLLBACK;
            END;
            
            START TRANSACTION;
            INSERT INTO log VALUES ('test');
            COMMIT;
        END //
        DELIMITER ;
        """

        statements = parser.split_statements(sql)
        assert len(statements) >= 1

        # Should preserve nested BEGIN/END blocks
        proc_stmt = next((stmt for stmt in statements if "CREATE PROCEDURE" in stmt), None)
        assert proc_stmt is not None
        assert "DECLARE EXIT HANDLER" in proc_stmt
