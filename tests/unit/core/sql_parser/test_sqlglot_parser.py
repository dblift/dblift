"""Tests for SqlGlot-based SQL parser."""

import pytest

from core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlObjectType,
    SqlStatementType,
)
from core.sql_parser.sqlglot_parser import SqlGlotParser


@pytest.mark.unit
class TestSqlGlotParser:
    """Test SqlGlotParser functionality across all supported dialects."""

    # ==================== Parser Creation Tests ====================

    def test_dialect_is_required(self):
        """ADR-26 E: ``dialect`` has no default — the sole production caller
        (HybridParser) always passes one, so the literal default was removed."""
        with pytest.raises(TypeError):
            SqlGlotParser()

    def test_parser_creation_postgresql(self):
        """Test parser can be created for PostgreSQL."""
        parser = SqlGlotParser(dialect="postgresql")
        assert parser is not None
        assert parser.dialect_name == "postgresql"
        assert parser.sqlglot_dialect == "postgres"

    def test_parser_creation_mysql(self):
        """Test parser can be created for MySQL."""
        parser = SqlGlotParser(dialect="mysql")
        assert parser is not None
        assert parser.dialect_name == "mysql"
        assert parser.sqlglot_dialect == "mysql"

    def test_parser_creation_oracle(self):
        """Test parser can be created for Oracle."""
        parser = SqlGlotParser(dialect="oracle")
        assert parser is not None
        assert parser.dialect_name == "oracle"
        assert parser.sqlglot_dialect == "oracle"

    def test_parser_creation_sqlserver(self):
        """Test parser can be created for SQL Server."""
        parser = SqlGlotParser(dialect="sqlserver")
        assert parser is not None
        assert parser.dialect_name == "sqlserver"
        assert parser.sqlglot_dialect == "tsql"

    # ==================== PostgreSQL Tests ====================

    def test_parse_postgresql_create_table(self):
        """Test parsing PostgreSQL CREATE TABLE."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL)"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.CREATE
        assert len(result.statements[0].objects) == 1
        assert result.statements[0].objects[0].name == "users"
        assert result.statements[0].objects[0].object_type == SqlObjectType.TABLE

    def test_parse_postgresql_create_view(self):
        """Test parsing PostgreSQL CREATE VIEW."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "CREATE VIEW user_emails AS SELECT id, email FROM users"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.CREATE
        # Should have both the view and the referenced table
        assert len(result.statements[0].objects) >= 1

    def test_parse_postgresql_multiple_statements(self):
        """Test parsing multiple PostgreSQL statements."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = """
        CREATE TABLE users (id INTEGER);
        CREATE TABLE posts (id INTEGER, user_id INTEGER);
        """

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 2
        assert all(stmt.statement_type == SqlStatementType.CREATE for stmt in result.statements)

    def test_parse_postgresql_with_schema(self):
        """Test parsing PostgreSQL statements with schema."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "CREATE TABLE public.users (id INTEGER)"

        result = parser.parse_sql(sql, default_schema="public")

        assert result.success
        assert len(result.statements) == 1
        # The table should have schema specified
        table_obj = result.statements[0].objects[0]
        assert table_obj.name == "users"

    def test_split_statements_postgresql(self):
        """Test splitting PostgreSQL statements."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "SELECT 1; SELECT 2; SELECT 3"

        statements = parser.split_statements(sql)

        assert len(statements) == 3

    def test_validate_sql_postgresql_valid(self):
        """Test validating valid PostgreSQL SQL."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "SELECT * FROM users WHERE id = 1"

        result = parser.validate_sql(sql)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_sql_postgresql_invalid(self):
        """Test validating invalid PostgreSQL SQL."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "SELECT * FROM"  # Incomplete statement

        result = parser.validate_sql(sql)

        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_extract_objects_postgresql(self):
        """Test extracting objects from PostgreSQL SQL."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = """
        SELECT u.id, p.title
        FROM users u
        JOIN posts p ON u.id = p.user_id
        """

        objects = parser.extract_objects(sql)

        assert len(objects) >= 2
        object_names = [obj.name for obj in objects]
        assert "users" in object_names
        assert "posts" in object_names

    # ==================== MySQL Tests ====================

    def test_parse_mysql_create_table(self):
        """Test parsing MySQL CREATE TABLE."""
        parser = SqlGlotParser(dialect="mysql")
        sql = "CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(100))"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.CREATE

    def test_parse_mysql_with_engine(self):
        """Test parsing MySQL CREATE TABLE with ENGINE."""
        parser = SqlGlotParser(dialect="mysql")
        sql = "CREATE TABLE users (id INT) ENGINE=InnoDB"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1

    def test_parse_mysql_insert(self):
        """Test parsing MySQL INSERT."""
        parser = SqlGlotParser(dialect="mysql")
        sql = "INSERT INTO users (id, name) VALUES (1, 'John')"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.INSERT

    # ==================== Oracle Tests ====================

    def test_parse_oracle_create_table(self):
        """Test parsing Oracle CREATE TABLE."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "CREATE TABLE users (id NUMBER, name VARCHAR2(100))"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.CREATE
        assert result.statements[0].objects[0].name == "users"

    def test_parse_oracle_create_sequence(self):
        """Test parsing Oracle CREATE SEQUENCE."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "CREATE SEQUENCE user_id_seq START WITH 1"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.CREATE

    def test_parse_oracle_dual(self):
        """Test parsing Oracle SELECT FROM DUAL."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "SELECT SYSDATE FROM DUAL"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1

    # ==================== SQL Server Tests ====================

    def test_parse_sqlserver_create_table(self):
        """Test parsing SQL Server CREATE TABLE."""
        parser = SqlGlotParser(dialect="sqlserver")
        sql = "CREATE TABLE users (id INT PRIMARY KEY, name NVARCHAR(100))"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.CREATE

    def test_parse_sqlserver_inline_primary_key_clustered(self):
        """SQL Server inline PRIMARY KEY with CLUSTERED should parse."""
        parser = SqlGlotParser(dialect="sqlserver")
        sql = "CREATE TABLE orders (order_id INT NOT NULL PRIMARY KEY CLUSTERED, status NVARCHAR(20));"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        objects = result.statements[0].objects
        assert any(
            obj.object_type == SqlObjectType.TABLE and obj.name == "orders" for obj in objects
        )

    def test_parse_sqlserver_select_top(self):
        """Test parsing SQL Server SELECT TOP."""
        parser = SqlGlotParser(dialect="sqlserver")
        sql = "SELECT TOP 10 * FROM users"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.SELECT

    # ==================== Common DDL Tests ====================

    def test_parse_drop_table(self):
        """Test parsing DROP TABLE."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "DROP TABLE users"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.DROP

    def test_parse_alter_table(self):
        """Test parsing ALTER TABLE."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "ALTER TABLE users ADD COLUMN age INTEGER"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.ALTER

    def test_parse_update(self):
        """Test parsing UPDATE."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "UPDATE users SET name = 'John' WHERE id = 1"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.UPDATE

    def test_parse_delete(self):
        """Test parsing DELETE."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "DELETE FROM users WHERE id = 1"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.DELETE

    # ==================== Complex SQL Tests ====================

    def test_parse_cte(self):
        """Test parsing Common Table Expression (CTE)."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = """
        WITH active_users AS (
            SELECT * FROM users WHERE active = true
        )
        SELECT * FROM active_users
        """

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1

    def test_parse_subquery(self):
        """Test parsing subquery."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "SELECT * FROM users WHERE id IN (SELECT user_id FROM posts)"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1

    def test_parse_join(self):
        """Test parsing JOIN."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = """
        SELECT u.name, p.title
        FROM users u
        INNER JOIN posts p ON u.id = p.user_id
        """

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1

    # ==================== Error Handling Tests ====================

    def test_parse_empty_string(self):
        """Test parsing empty string."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = ""

        result = parser.parse_sql(sql)

        # Empty SQL should succeed but have no statements
        assert len(result.statements) == 0

    def test_parse_invalid_sql(self):
        """Test parsing invalid SQL."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "CREATE TABLE"  # Incomplete

        result = parser.parse_sql(sql)

        # Should fail or create statement with errors
        assert not result.success or len(result.errors) > 0

    def test_extract_objects_empty_sql(self):
        """Test extracting objects from empty SQL."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = ""

        objects = parser.extract_objects(sql)

        assert len(objects) == 0

    # ==================== Affected Objects Tests ====================

    def test_affected_objects_create_table(self):
        """Test affected objects for CREATE TABLE."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "CREATE TABLE users (id INTEGER)"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements[0].affected_objects) == 1
        assert result.statements[0].affected_objects[0].name == "users"
        assert result.statements[0].affected_objects[0].object_type == SqlObjectType.TABLE

    def test_affected_objects_drop_table(self):
        """Test affected objects for DROP TABLE."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "DROP TABLE users"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements[0].affected_objects) >= 1

    def test_affected_objects_insert(self):
        """Test affected objects for INSERT."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "INSERT INTO users (id) VALUES (1)"

        result = parser.parse_sql(sql)

        assert result.success
        # INSERT should affect the target table
        assert len(result.statements[0].affected_objects) >= 1

    # ==================== Quoted Identifiers Tests ====================

    def test_parse_quoted_identifiers_postgresql(self):
        """Test parsing quoted identifiers in PostgreSQL."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = 'CREATE TABLE "User Table" (id INTEGER)'

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1

    def test_parse_quoted_identifiers_mysql(self):
        """Test parsing backtick identifiers in MySQL."""
        parser = SqlGlotParser(dialect="mysql")
        sql = "CREATE TABLE `users` (`id` INT)"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1

    # ==================== Dialect-Specific Features ====================

    def test_postgresql_array_type(self):
        """Test parsing PostgreSQL array type."""
        parser = SqlGlotParser(dialect="postgresql")
        sql = "CREATE TABLE users (tags TEXT[])"

        result = parser.parse_sql(sql)

        assert result.success

    def test_mysql_auto_increment(self):
        """Test parsing MySQL AUTO_INCREMENT."""
        parser = SqlGlotParser(dialect="mysql")
        sql = "CREATE TABLE users (id INT AUTO_INCREMENT PRIMARY KEY)"

        result = parser.parse_sql(sql)

        assert result.success

    def test_oracle_number_type(self):
        """Test parsing Oracle NUMBER type."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "CREATE TABLE users (id NUMBER(10,0))"

        result = parser.parse_sql(sql)

        assert result.success

    def test_sqlserver_identity(self):
        """Test parsing SQL Server IDENTITY."""
        parser = SqlGlotParser(dialect="sqlserver")
        sql = "CREATE TABLE users (id INT IDENTITY(1,1) PRIMARY KEY)"

        result = parser.parse_sql(sql)

        assert result.success
