"""Tests for SqlGlot-based SQL parser."""

import pytest

from dblift.core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlObjectType,
    SqlStatementType,
)
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from tests.support.legacy_snowflake_parsers import snowflake_facts_off
from tests.support.legacy_sqlserver_parsers import legacy_sqlserver_sqlglot

pytestmark = pytest.mark.usefixtures("legacy_oracle")


def test_snowflake_qualified_drop_index_on_relation_stays_unread():
    sql = "DROP INDEX idx1 ON dbo.mytable"
    with snowflake_facts_off():
        parser = SqlParserFactory("snowflake")

        with pytest.raises(ValueError, match="Failed to parse SQL"):
            parser.parse(sql)
        assert not parser.validate_sql(sql)["valid"]
        assert parser.extract_objects(sql) == []


@pytest.mark.unit
class TestSqlGlotParser:
    """Test SqlGlotParser functionality across all supported dialects."""

    # ==================== Parser Creation Tests ====================

    def test_dialect_is_required(self):
        """ADR-26 E: ``dialect`` has no default — the sole production caller
        (HybridParser) always passes one, so the literal default was removed."""
        with pytest.raises(TypeError):
            SqlGlotParser()

    def test_parser_creation_oracle(self):
        """Test parser can be created for Oracle."""
        parser = SqlGlotParser(dialect="oracle")
        assert parser is not None
        assert parser.dialect_name == "oracle"
        assert parser.sqlglot_dialect == "oracle"

    def test_parser_creation_sqlserver(self):
        """The SQL Server plugin serves statement facts publicly."""
        with pytest.raises(ValueError, match="StatementFactsParser"):
            SqlGlotParser(dialect="sqlserver")

    # ==================== Oracle Tests ====================

    def test_parse_oracle_create_view(self):
        """Test parsing Oracle CREATE VIEW."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "CREATE VIEW user_emails AS SELECT id, email FROM users"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.CREATE
        # Should have both the view and the referenced table
        assert len(result.statements[0].objects) >= 1

    def test_parse_oracle_multiple_statements(self):
        """Test parsing multiple Oracle statements."""
        parser = SqlGlotParser(dialect="oracle")
        sql = """
        CREATE TABLE users (id INTEGER);
        CREATE TABLE posts (id INTEGER, user_id INTEGER);
        """

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 2
        assert all(stmt.statement_type == SqlStatementType.CREATE for stmt in result.statements)

    def test_parse_oracle_with_schema(self):
        """Test parsing Oracle statements with schema."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "CREATE TABLE public.users (id INTEGER)"

        result = parser.parse_sql(sql, default_schema="public")

        assert result.success
        assert len(result.statements) == 1
        # The table should have schema specified
        table_obj = result.statements[0].objects[0]
        assert table_obj.name == "users"

    def test_split_statements_one_per_line(self):
        """Test splitting statements written one per line."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "SELECT 1;\nSELECT 2;\nSELECT 3"

        statements = parser.split_statements(sql)

        assert len(statements) == 3

    def test_validate_sql_oracle_valid(self):
        """Test validating valid Oracle SQL."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "SELECT * FROM users WHERE id = 1"

        result = parser.validate_sql(sql)

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_sql_oracle_invalid(self):
        """Test validating invalid Oracle SQL."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "SELECT * FROM"  # Incomplete statement

        result = parser.validate_sql(sql)

        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_extract_objects_oracle(self):
        """Test extracting objects from Oracle SQL."""
        parser = SqlGlotParser(dialect="oracle")
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

    # ==================== SQL Server Tests ====================

    def test_parse_sqlserver_insert(self):
        """Test parsing SQL Server INSERT."""
        parser = legacy_sqlserver_sqlglot()
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
        parser = legacy_sqlserver_sqlglot()
        sql = "CREATE TABLE users (id INT PRIMARY KEY, name NVARCHAR(100))"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.CREATE

    def test_parse_sqlserver_inline_primary_key_clustered(self):
        """SQL Server inline PRIMARY KEY with CLUSTERED should parse."""
        parser = legacy_sqlserver_sqlglot()
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
        parser = legacy_sqlserver_sqlglot()
        sql = "SELECT TOP 10 * FROM users"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.SELECT

    # ==================== Common DDL Tests ====================

    def test_parse_drop_table(self):
        """Test parsing DROP TABLE."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "DROP TABLE users"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.DROP

    def test_parse_alter_table(self):
        """Test parsing ALTER TABLE."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "ALTER TABLE users ADD COLUMN age INTEGER"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.ALTER

    def test_parse_update(self):
        """Test parsing UPDATE."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "UPDATE users SET name = 'John' WHERE id = 1"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.UPDATE

    def test_parse_delete(self):
        """Test parsing DELETE."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "DELETE FROM users WHERE id = 1"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.DELETE

    # ==================== Complex SQL Tests ====================

    def test_parse_cte(self):
        """Test parsing Common Table Expression (CTE)."""
        parser = SqlGlotParser(dialect="oracle")
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
        parser = SqlGlotParser(dialect="oracle")
        sql = "SELECT * FROM users WHERE id IN (SELECT user_id FROM posts)"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1

    def test_parse_join(self):
        """Test parsing JOIN."""
        parser = SqlGlotParser(dialect="oracle")
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
        parser = SqlGlotParser(dialect="oracle")
        sql = ""

        result = parser.parse_sql(sql)

        # Empty SQL should succeed but have no statements
        assert len(result.statements) == 0

    def test_parse_invalid_sql(self):
        """Test parsing invalid SQL."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "CREATE TABLE"  # Incomplete

        result = parser.parse_sql(sql)

        # Should fail or create statement with errors
        assert not result.success or len(result.errors) > 0

    def test_extract_objects_empty_sql(self):
        """Test extracting objects from empty SQL."""
        parser = SqlGlotParser(dialect="oracle")
        sql = ""

        objects = parser.extract_objects(sql)

        assert len(objects) == 0

    def test_extract_objects_logs_visibly_when_sqlglot_cannot_parse(self, caplog):
        """A ``ParseError`` swallowed by ``extract_objects`` must be visible.

        sqlglot cannot parse the comma-separated ``DROP INDEX a.idx1,
        b.idx2;`` form under ``tsql`` (dblift/dblift#379). Before this test,
        the failure was logged at DEBUG, a level no default application
        configuration surfaces, so the degradation to "no objects here" left
        no trace an operator would see. It must log at WARNING or above.
        """
        parser = legacy_sqlserver_sqlglot()
        sql = "DROP INDEX a.idx1, b.idx2;"

        with caplog.at_level("WARNING", logger="dblift.core.sql_parser.sqlglot_parser"):
            objects = parser.extract_objects(sql)

        assert objects == []
        assert any(record.levelname == "WARNING" for record in caplog.records)

    def test_extract_objects_warning_has_no_ansi_escape_codes(self, caplog):
        parser = SqlGlotParser(dialect="oracle")

        with caplog.at_level("WARNING", logger="dblift.core.sql_parser.sqlglot_parser"):
            parser.extract_objects("DROP TRIGGER IF EXISTS trg_items_touch ON public.items;")

        warning = caplog.records[-1].getMessage()
        assert "SqlGlot parse failed for object extraction" in warning
        assert "Unexpected token" in warning
        assert "public" in warning
        assert "\x1b" not in warning

    # ==================== Affected Objects Tests ====================

    def test_affected_objects_create_table(self):
        """Test affected objects for CREATE TABLE."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "CREATE TABLE users (id INTEGER)"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements[0].affected_objects) == 1
        assert result.statements[0].affected_objects[0].name == "users"
        assert result.statements[0].affected_objects[0].object_type == SqlObjectType.TABLE

    def test_affected_objects_drop_table(self):
        """Test affected objects for DROP TABLE."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "DROP TABLE users"

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements[0].affected_objects) >= 1

    def test_affected_objects_drop_multiple_tables(self):
        """Test affected objects for DROP TABLE naming several tables."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "DROP TABLE IF EXISTS users, orders CASCADE"

        result = parser.parse_sql(sql)

        assert result.success
        names = [obj.name for obj in result.statements[0].affected_objects]
        assert names == ["users", "orders"]
        assert all(
            obj.object_type == SqlObjectType.TABLE for obj in result.statements[0].affected_objects
        )

    def test_affected_objects_insert(self):
        """Test affected objects for INSERT."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "INSERT INTO users (id) VALUES (1)"

        result = parser.parse_sql(sql)

        assert result.success
        # INSERT should affect the target table
        assert len(result.statements[0].affected_objects) >= 1

    def test_affected_objects_drop_index_legacy_table_dot_name(self):
        """SQL Server's deprecated ``DROP INDEX table.index_name`` spelling
        must not leak into affected_objects either: ``_extract_affected_objects``
        has its own call into ``_correct_sqlserver_drop_index_schema`` (#367),
        separate from the one ``extract_objects`` uses, and covering one does
        not exercise the other — this is that path's own default_schema,
        distinct from any schema embedded in the SQL."""
        parser = legacy_sqlserver_sqlglot()
        sql = "DROP INDEX real_one.idx1;"

        result = parser.parse_sql(sql, default_schema="unrelated_default")

        assert result.success
        affected = result.statements[0].affected_objects
        assert len(affected) == 1
        assert affected[0].name == "idx1"
        assert affected[0].schema == "unrelated_default"
        assert affected[0].object_type == SqlObjectType.INDEX

    def test_affected_objects_drop_index_legacy_owner_table_dot_name(self):
        """Same path, three-part ``owner.table.index_name`` form: the owner
        sqlglot parses into ``Table.catalog`` must survive here too, not
        just through ``extract_objects``."""
        parser = legacy_sqlserver_sqlglot()
        sql = "DROP INDEX dbo.real_one.idx1;"

        result = parser.parse_sql(sql, default_schema="unrelated_default")

        assert result.success
        affected = result.statements[0].affected_objects
        assert len(affected) == 1
        assert affected[0].name == "idx1"
        assert affected[0].schema == "dbo"
        assert affected[0].object_type == SqlObjectType.INDEX

    # ==================== Quoted Identifiers Tests ====================

    def test_parse_quoted_identifiers_oracle(self):
        """Test parsing quoted identifiers in Oracle."""
        parser = SqlGlotParser(dialect="oracle")
        sql = 'CREATE TABLE "User Table" (id INTEGER)'

        result = parser.parse_sql(sql)

        assert result.success
        assert len(result.statements) == 1

    # ==================== Dialect-Specific Features ====================

    def test_oracle_array_type(self):
        """Test parsing Oracle array type."""
        parser = SqlGlotParser(dialect="oracle")
        sql = "CREATE TABLE users (tags TEXT[])"

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
        parser = legacy_sqlserver_sqlglot()
        sql = "CREATE TABLE users (id INT IDENTITY(1,1) PRIMARY KEY)"

        result = parser.parse_sql(sql)

        assert result.success
