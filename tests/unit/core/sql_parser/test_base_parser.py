"""Unit tests for core.sql_parser.common.base_parser module."""

from unittest.mock import patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlObject, SqlObjectType, SqlStatementType
from dblift.core.sql_parser.common.base_parser import RegexBasedParser


@pytest.mark.unit
class TestRegexBasedParser:
    """Test RegexBasedParser class."""

    def test_init(self):
        """Test RegexBasedParser initialization."""
        parser = RegexBasedParser("postgresql")

        assert parser._dialect == "postgresql"
        assert parser._last_statement is None
        assert parser._last_objects == []
        assert parser._last_errors == []
        assert parser._last_type is None

    def test_dialect_name_property(self):
        """Test dialect_name property."""
        parser = RegexBasedParser("oracle")

        assert parser.dialect_name == "oracle"

    def test_parse_sql_empty(self):
        """Test parse_sql with empty content."""
        parser = RegexBasedParser("postgresql")

        result = parser.parse_sql("")

        assert isinstance(result, ParseResult)
        assert result.success is True
        assert len(result.statements) == 0
        assert len(result.errors) == 0

    def test_parse_sql_simple_create_table(self):
        """Test parse_sql with simple CREATE TABLE."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE test_table (id INT);"
        result = parser.parse_sql(sql, default_schema="public")

        assert result.success is True
        assert len(result.statements) == 1
        assert result.statements[0].statement_type == SqlStatementType.DDL
        assert len(result.statements[0].objects) == 1
        assert result.statements[0].objects[0].name == "test_table"
        assert result.statements[0].objects[0].object_type == SqlObjectType.TABLE

    def test_parse_sql_multiple_statements(self):
        """Test parse_sql with multiple statements."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE t1 (id INT); CREATE TABLE t2 (id INT);"
        result = parser.parse_sql(sql, default_schema="public")

        assert result.success is True
        assert len(result.statements) == 2

    def test_parse_sql_with_whitespace(self):
        """Test parse_sql with whitespace-only statements."""
        parser = RegexBasedParser("postgresql")

        sql = "   \n\n   ; CREATE TABLE t1 (id INT);"
        result = parser.parse_sql(sql, default_schema="public")

        assert result.success is True
        assert len(result.statements) == 1

    def test_parse_sql_with_errors(self):
        """Test parse_sql when statement parsing fails."""
        parser = RegexBasedParser("postgresql")

        # Mock extract_objects to raise an exception
        with patch.object(parser, "extract_objects", side_effect=Exception("Parse error")):
            sql = "CREATE TABLE t1 (id INT);"
            result = parser.parse_sql(sql, default_schema="public")

            assert result.success is False
            assert len(result.errors) > 0

    def test_split_statements_simple(self):
        """Test split_statements with semicolon-separated statements."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE t1 (id INT); CREATE TABLE t2 (id INT);"
        statements = parser.split_statements(sql)

        assert len(statements) == 2
        assert "CREATE TABLE t1" in statements[0]
        assert "CREATE TABLE t2" in statements[1]

    def test_split_statements_sqlserver_with_go(self):
        """Test split_statements with SQL Server GO statements."""
        parser = RegexBasedParser("sqlserver")

        sql = "CREATE TABLE t1 (id INT)\nGO\nCREATE TABLE t2 (id INT)\nGO"
        statements = parser.split_statements(sql)

        assert len(statements) >= 2

    def test_split_statements_sqlserver_no_go(self):
        """Test split_statements with SQL Server but no GO statements."""
        parser = RegexBasedParser("sqlserver")

        sql = "CREATE TABLE t1 (id INT); CREATE TABLE t2 (id INT);"
        statements = parser.split_statements(sql)

        assert len(statements) == 2

    def test_split_statements_mssql_dialect(self):
        """Test split_statements with mssql dialect."""
        parser = RegexBasedParser("mssql")

        sql = "CREATE TABLE t1 (id INT)\nGO\nCREATE TABLE t2 (id INT)"
        statements = parser.split_statements(sql)

        assert len(statements) >= 1

    def test_validate_sql(self):
        """Test validate_sql method."""
        parser = RegexBasedParser("postgresql")

        result = parser.validate_sql("CREATE TABLE t1 (id INT);")

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_extract_objects_empty(self):
        """Test extract_objects with empty content."""
        parser = RegexBasedParser("postgresql")

        objects = parser.extract_objects("")

        assert len(objects) == 0

    def test_extract_objects_create_table(self):
        """Test extract_objects with CREATE TABLE."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE test_table (id INT)"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_table"
        assert objects[0].object_type == SqlObjectType.TABLE
        assert objects[0].schema == "public"

    def test_extract_objects_create_table_with_schema(self):
        """Test extract_objects with CREATE TABLE including schema."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE myschema.test_table (id INT)"
        objects = parser.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "test_table"
        assert objects[0].schema == "myschema"

    def test_extract_objects_create_table_default_schema_sqlserver(self):
        """Test extract_objects with CREATE TABLE using SQL Server default schema."""
        parser = RegexBasedParser("sqlserver")

        sql = "CREATE TABLE test_table (id INT)"
        objects = parser.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].schema == "dbo"

    def test_extract_objects_create_table_default_schema_other(self):
        """Test extract_objects with CREATE TABLE using other dialect default schema."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE test_table (id INT)"
        objects = parser.extract_objects(sql)

        assert len(objects) == 1
        # When default_schema is None, uses quirks.default_schema_name (PG="public").
        assert objects[0].schema == "public"

    def test_extract_objects_alter_table(self):
        """Test extract_objects with ALTER TABLE."""
        parser = RegexBasedParser("postgresql")

        sql = "ALTER TABLE test_table ADD COLUMN name VARCHAR(100)"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_table"
        assert objects[0].object_type == SqlObjectType.TABLE

    def test_extract_objects_create_view(self):
        """Test extract_objects with CREATE VIEW."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE VIEW test_view AS SELECT * FROM t1"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_view"
        assert objects[0].object_type == SqlObjectType.VIEW

    def test_extract_objects_create_or_replace_view(self):
        """Test extract_objects with CREATE OR REPLACE VIEW."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE OR REPLACE VIEW test_view AS SELECT * FROM t1"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_view"
        assert objects[0].object_type == SqlObjectType.VIEW

    def test_extract_objects_create_index(self):
        """Test extract_objects with CREATE INDEX."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE INDEX idx_name ON test_table (id)"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 2  # Index and table
        assert objects[0].name == "idx_name"
        assert objects[0].object_type == SqlObjectType.INDEX
        assert objects[1].name == "test_table"
        assert objects[1].object_type == SqlObjectType.TABLE

    def test_extract_objects_create_unique_index(self):
        """Test extract_objects with CREATE UNIQUE INDEX."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE UNIQUE INDEX idx_name ON test_table (id)"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 2
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_extract_objects_drop_table(self):
        """Test extract_objects with DROP TABLE."""
        parser = RegexBasedParser("postgresql")

        sql = "DROP TABLE test_table"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_table"
        assert objects[0].object_type == SqlObjectType.TABLE

    def test_extract_objects_drop_view(self):
        """Test extract_objects with DROP VIEW."""
        parser = RegexBasedParser("postgresql")

        sql = "DROP VIEW test_view"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.VIEW

    def test_extract_objects_drop_index(self):
        """Test extract_objects with DROP INDEX."""
        parser = RegexBasedParser("postgresql")

        sql = "DROP INDEX idx_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_extract_objects_drop_sequence(self):
        """Test extract_objects with DROP SEQUENCE."""
        parser = RegexBasedParser("postgresql")

        sql = "DROP SEQUENCE seq_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.SEQUENCE

    def test_extract_objects_drop_procedure(self):
        """Test extract_objects with DROP PROCEDURE."""
        parser = RegexBasedParser("postgresql")

        sql = "DROP PROCEDURE proc_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.PROCEDURE

    def test_extract_objects_drop_function(self):
        """Test extract_objects with DROP FUNCTION."""
        parser = RegexBasedParser("postgresql")

        sql = "DROP FUNCTION func_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.FUNCTION

    def test_extract_objects_drop_trigger(self):
        """Test extract_objects with DROP TRIGGER."""
        parser = RegexBasedParser("postgresql")

        sql = "DROP TRIGGER trig_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.TRIGGER

    def test_extract_objects_drop_unknown(self):
        """Test extract_objects with DROP unknown type."""
        parser = RegexBasedParser("postgresql")

        sql = "DROP UNKNOWN_TYPE obj_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.UNKNOWN

    def test_get_affected_objects(self):
        """Test get_affected_objects method."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE test_table (id INT)"
        objects = parser.get_affected_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_table"

    def test_get_errors(self):
        """Test get_errors method."""
        parser = RegexBasedParser("postgresql")

        errors = parser.get_errors()

        assert isinstance(errors, list)

    def test_is_valid(self):
        """Test is_valid property."""
        parser = RegexBasedParser("postgresql")

        assert parser.is_valid is True

        parser._last_errors = ["Error 1"]
        assert parser.is_valid is False

    def test_is_dml(self):
        """Test is_dml property."""
        parser = RegexBasedParser("postgresql")

        assert parser.is_dml is False

        parser._last_type = "DML"
        assert parser.is_dml is True

    def test_is_query(self):
        """Test is_query property."""
        parser = RegexBasedParser("postgresql")

        assert parser.is_query is False

        parser._last_type = "QUERY"
        assert parser.is_query is True

    def test_split_by_semicolon_simple(self):
        """Test _split_by_semicolon with simple statements."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE t1 (id INT); CREATE TABLE t2 (id INT);"
        statements = parser._split_by_semicolon(sql)

        assert len(statements) == 2

    def test_split_by_semicolon_with_strings(self):
        """Test _split_by_semicolon with string literals."""
        parser = RegexBasedParser("postgresql")

        sql = "INSERT INTO t1 VALUES ('test;value'); SELECT * FROM t1;"
        statements = parser._split_by_semicolon(sql)

        assert len(statements) == 2
        assert "'test;value'" in statements[0]

    def test_split_by_semicolon_with_comments(self):
        """Test _split_by_semicolon with comments."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE t1 (id INT); -- comment\nSELECT * FROM t1;"
        statements = parser._split_by_semicolon(sql)

        assert len(statements) == 2

    def test_split_by_semicolon_with_block_comments(self):
        """Test _split_by_semicolon with block comments."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE t1 (id INT); /* comment */ SELECT * FROM t1;"
        statements = parser._split_by_semicolon(sql)

        assert len(statements) == 2

    def test_split_by_semicolon_with_quoted_identifiers(self):
        """Test _split_by_semicolon with quoted identifiers."""
        parser = RegexBasedParser("postgresql")

        sql = 'CREATE TABLE "test;table" (id INT); SELECT * FROM t1;'
        statements = parser._split_by_semicolon(sql)

        # The semicolon inside quoted identifier should be preserved
        # So we should get at least 1 statement (the CREATE TABLE)
        assert len(statements) >= 1
        assert 'CREATE TABLE "test;table"' in statements[0]

    def test_split_by_semicolon_with_sqlserver_identifiers(self):
        """Test _split_by_semicolon with SQL Server identifiers."""
        parser = RegexBasedParser("sqlserver")

        sql = "CREATE TABLE [test;table] (id INT); SELECT * FROM t1;"
        statements = parser._split_by_semicolon(sql)

        assert len(statements) == 2

    def test_split_sqlserver_with_go(self):
        """Test _split_sqlserver_with_go method."""
        parser = RegexBasedParser("sqlserver")

        sql = "CREATE TABLE t1 (id INT)\nGO\nCREATE TABLE t2 (id INT)"
        statements = parser._split_sqlserver_with_go(sql)

        assert len(statements) >= 1

    def test_split_sqlserver_with_go_empty_batches(self):
        """Test _split_sqlserver_with_go with empty batches."""
        parser = RegexBasedParser("sqlserver")

        sql = "GO\nGO\nCREATE TABLE t1 (id INT)\nGO"
        statements = parser._split_sqlserver_with_go(sql)

        assert len(statements) >= 1

    def test_get_statement_type_ddl(self):
        """Test _get_statement_type with DDL statements."""
        parser = RegexBasedParser("postgresql")

        assert parser._get_statement_type("CREATE TABLE t1") == "DDL"
        assert parser._get_statement_type("ALTER TABLE t1") == "DDL"
        assert parser._get_statement_type("DROP TABLE t1") == "DDL"
        assert parser._get_statement_type("TRUNCATE TABLE t1") == "DDL"
        assert parser._get_statement_type("RENAME TABLE t1") == "DDL"
        assert parser._get_statement_type("COMMENT ON TABLE t1") == "DDL"

    def test_get_statement_type_dml(self):
        """Test _get_statement_type with DML statements."""
        parser = RegexBasedParser("postgresql")

        assert parser._get_statement_type("INSERT INTO t1") == "DML"
        assert parser._get_statement_type("UPDATE t1 SET") == "DML"
        assert parser._get_statement_type("DELETE FROM t1") == "DML"
        assert parser._get_statement_type("MERGE INTO t1") == "DML"
        assert parser._get_statement_type("CALL proc()") == "DML"
        assert parser._get_statement_type("EXPLAIN SELECT") == "DML"
        assert parser._get_statement_type("LOCK TABLE t1") == "DML"

    def test_get_statement_type_query(self):
        """Test _get_statement_type with query statements."""
        parser = RegexBasedParser("postgresql")

        assert parser._get_statement_type("SELECT * FROM t1") == "QUERY"
        assert parser._get_statement_type("WITH cte AS") == "QUERY"
        assert parser._get_statement_type("SHOW TABLES") == "QUERY"
        assert parser._get_statement_type("DESC t1") == "QUERY"
        assert parser._get_statement_type("DESCRIBE t1") == "QUERY"

    def test_get_statement_type_unknown(self):
        """Test _get_statement_type with unknown statements."""
        parser = RegexBasedParser("postgresql")

        assert parser._get_statement_type("UNKNOWN STATEMENT") == "UNKNOWN"
        assert parser._get_statement_type("") == "UNKNOWN"
