"""Unit tests for core.sql_parser.common.base_parser module."""

from unittest.mock import patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlObject, SqlObjectType, SqlStatementType
from dblift.core.sql_parser.common.base_parser import RegexBasedParser


class _SemanticParser(RegexBasedParser):
    def split_statements(self, sql_content, strict_tokenizer=False):
        from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser

        return PostgreSqlRegexParser().split_statements(sql_content, strict_tokenizer)


@pytest.mark.unit
class TestRegexBasedParser:
    """Test RegexBasedParser class."""

    def test_init(self):
        """Test RegexBasedParser initialization."""
        parser = _SemanticParser("postgresql")

        assert parser._dialect == "postgresql"
        assert parser._last_statement is None
        assert parser._last_objects == []
        assert parser._last_errors == []
        assert parser._last_type is None

    def test_dialect_name_property(self):
        """Test dialect_name property."""
        parser = _SemanticParser("oracle")

        assert parser.dialect_name == "oracle"

    def test_parse_sql_empty(self):
        """Test parse_sql with empty content."""
        parser = _SemanticParser("postgresql")

        result = parser.parse_sql("")

        assert isinstance(result, ParseResult)
        assert result.success is True
        assert len(result.statements) == 0
        assert len(result.errors) == 0

    def test_parse_sql_simple_create_table(self):
        """Test parse_sql with simple CREATE TABLE."""
        parser = _SemanticParser("postgresql")

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
        parser = _SemanticParser("postgresql")

        sql = "CREATE TABLE t1 (id INT); CREATE TABLE t2 (id INT);"
        result = parser.parse_sql(sql, default_schema="public")

        assert result.success is True
        assert len(result.statements) == 2

    def test_parse_sql_with_whitespace(self):
        """Test parse_sql with whitespace-only statements."""
        parser = _SemanticParser("postgresql")

        sql = "   \n\n   ; CREATE TABLE t1 (id INT);"
        result = parser.parse_sql(sql, default_schema="public")

        assert result.success is True
        assert len(result.statements) == 1

    def test_parse_sql_with_errors(self):
        """Test parse_sql when statement parsing fails."""
        parser = _SemanticParser("postgresql")

        # Mock extract_objects to raise an exception
        with patch.object(parser, "extract_objects", side_effect=Exception("Parse error")):
            sql = "CREATE TABLE t1 (id INT);"
            result = parser.parse_sql(sql, default_schema="public")

            assert result.success is False
            assert len(result.errors) > 0

    def test_validate_sql(self):
        """Test validate_sql method."""
        parser = _SemanticParser("postgresql")

        result = parser.validate_sql("CREATE TABLE t1 (id INT);")

        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_extract_objects_empty(self):
        """Test extract_objects with empty content."""
        parser = _SemanticParser("postgresql")

        objects = parser.extract_objects("")

        assert len(objects) == 0

    def test_extract_objects_create_table(self):
        """Test extract_objects with CREATE TABLE."""
        parser = _SemanticParser("postgresql")

        sql = "CREATE TABLE test_table (id INT)"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_table"
        assert objects[0].object_type == SqlObjectType.TABLE
        assert objects[0].schema == "public"

    def test_extract_objects_create_table_with_schema(self):
        """Test extract_objects with CREATE TABLE including schema."""
        parser = _SemanticParser("postgresql")

        sql = "CREATE TABLE myschema.test_table (id INT)"
        objects = parser.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].name == "test_table"
        assert objects[0].schema == "myschema"

    def test_extract_objects_create_table_default_schema_sqlserver(self):
        """Test extract_objects with CREATE TABLE using SQL Server default schema."""
        parser = _SemanticParser("sqlserver")

        sql = "CREATE TABLE test_table (id INT)"
        objects = parser.extract_objects(sql)

        assert len(objects) == 1
        assert objects[0].schema == "dbo"

    def test_extract_objects_create_table_default_schema_other(self):
        """Test extract_objects with CREATE TABLE using other dialect default schema."""
        parser = _SemanticParser("postgresql")

        sql = "CREATE TABLE test_table (id INT)"
        objects = parser.extract_objects(sql)

        assert len(objects) == 1
        # When default_schema is None, uses quirks.default_schema_name (PG="public").
        assert objects[0].schema == "public"

    def test_extract_objects_alter_table(self):
        """Test extract_objects with ALTER TABLE."""
        parser = _SemanticParser("postgresql")

        sql = "ALTER TABLE test_table ADD COLUMN name VARCHAR(100)"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_table"
        assert objects[0].object_type == SqlObjectType.TABLE

    def test_extract_objects_create_view(self):
        """Test extract_objects with CREATE VIEW."""
        parser = _SemanticParser("postgresql")

        sql = "CREATE VIEW test_view AS SELECT * FROM t1"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_view"
        assert objects[0].object_type == SqlObjectType.VIEW

    def test_extract_objects_create_or_replace_view(self):
        """Test extract_objects with CREATE OR REPLACE VIEW."""
        parser = _SemanticParser("postgresql")

        sql = "CREATE OR REPLACE VIEW test_view AS SELECT * FROM t1"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_view"
        assert objects[0].object_type == SqlObjectType.VIEW

    def test_extract_objects_create_index(self):
        """Test extract_objects with CREATE INDEX."""
        parser = _SemanticParser("postgresql")

        sql = "CREATE INDEX idx_name ON test_table (id)"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 2  # Index and table
        assert objects[0].name == "idx_name"
        assert objects[0].object_type == SqlObjectType.INDEX
        assert objects[1].name == "test_table"
        assert objects[1].object_type == SqlObjectType.TABLE

    def test_extract_objects_create_unique_index(self):
        """Test extract_objects with CREATE UNIQUE INDEX."""
        parser = _SemanticParser("postgresql")

        sql = "CREATE UNIQUE INDEX idx_name ON test_table (id)"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 2
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_extract_objects_drop_table(self):
        """Test extract_objects with DROP TABLE."""
        parser = _SemanticParser("postgresql")

        sql = "DROP TABLE test_table"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_table"
        assert objects[0].object_type == SqlObjectType.TABLE

    def test_extract_objects_drop_view(self):
        """Test extract_objects with DROP VIEW."""
        parser = _SemanticParser("postgresql")

        sql = "DROP VIEW test_view"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.VIEW

    def test_extract_objects_drop_index(self):
        """Test extract_objects with DROP INDEX."""
        parser = _SemanticParser("postgresql")

        sql = "DROP INDEX idx_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.INDEX

    def test_extract_objects_drop_sequence(self):
        """Test extract_objects with DROP SEQUENCE."""
        parser = _SemanticParser("postgresql")

        sql = "DROP SEQUENCE seq_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.SEQUENCE

    def test_extract_objects_drop_procedure(self):
        """Test extract_objects with DROP PROCEDURE."""
        parser = _SemanticParser("postgresql")

        sql = "DROP PROCEDURE proc_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.PROCEDURE

    def test_extract_objects_drop_function(self):
        """Test extract_objects with DROP FUNCTION."""
        parser = _SemanticParser("postgresql")

        sql = "DROP FUNCTION func_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.FUNCTION

    def test_extract_objects_drop_trigger(self):
        """Test extract_objects with DROP TRIGGER."""
        parser = _SemanticParser("postgresql")

        sql = "DROP TRIGGER trig_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.TRIGGER

    def test_extract_objects_drop_unknown(self):
        """Test extract_objects with DROP unknown type."""
        parser = _SemanticParser("postgresql")

        sql = "DROP UNKNOWN_TYPE obj_name"
        objects = parser.extract_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.UNKNOWN

    def test_get_affected_objects(self):
        """Test get_affected_objects method."""
        parser = _SemanticParser("postgresql")

        sql = "CREATE TABLE test_table (id INT)"
        objects = parser.get_affected_objects(sql, default_schema="public")

        assert len(objects) == 1
        assert objects[0].name == "test_table"

    def test_get_errors(self):
        """Test get_errors method."""
        parser = _SemanticParser("postgresql")

        errors = parser.get_errors()

        assert isinstance(errors, list)

    def test_is_valid(self):
        """Test is_valid property."""
        parser = _SemanticParser("postgresql")

        assert parser.is_valid is True

        parser._last_errors = ["Error 1"]
        assert parser.is_valid is False

    def test_is_dml(self):
        """Test is_dml property."""
        parser = _SemanticParser("postgresql")

        assert parser.is_dml is False

        parser._last_type = "DML"
        assert parser.is_dml is True

    def test_is_query(self):
        """Test is_query property."""
        parser = _SemanticParser("postgresql")

        assert parser.is_query is False

        parser._last_type = "QUERY"
        assert parser.is_query is True

    def test_get_statement_type_ddl(self):
        """Test _get_statement_type with DDL statements."""
        parser = _SemanticParser("postgresql")

        assert parser._get_statement_type("CREATE TABLE t1") == "DDL"
        assert parser._get_statement_type("ALTER TABLE t1") == "DDL"
        assert parser._get_statement_type("DROP TABLE t1") == "DDL"
        assert parser._get_statement_type("TRUNCATE TABLE t1") == "DDL"
        assert parser._get_statement_type("RENAME TABLE t1") == "DDL"
        assert parser._get_statement_type("COMMENT ON TABLE t1") == "DDL"

    def test_get_statement_type_dml(self):
        """Test _get_statement_type with DML statements."""
        parser = _SemanticParser("postgresql")

        assert parser._get_statement_type("INSERT INTO t1") == "DML"
        assert parser._get_statement_type("UPDATE t1 SET") == "DML"
        assert parser._get_statement_type("DELETE FROM t1") == "DML"
        assert parser._get_statement_type("MERGE INTO t1") == "DML"
        assert parser._get_statement_type("CALL proc()") == "DML"
        assert parser._get_statement_type("EXPLAIN SELECT") == "DML"
        assert parser._get_statement_type("LOCK TABLE t1") == "DML"

    def test_get_statement_type_query(self):
        """Test _get_statement_type with query statements."""
        parser = _SemanticParser("postgresql")

        assert parser._get_statement_type("SELECT * FROM t1") == "QUERY"
        assert parser._get_statement_type("WITH cte AS") == "QUERY"
        assert parser._get_statement_type("SHOW TABLES") == "QUERY"
        assert parser._get_statement_type("DESC t1") == "QUERY"
        assert parser._get_statement_type("DESCRIBE t1") == "QUERY"

    def test_get_statement_type_unknown(self):
        """Test _get_statement_type with unknown statements."""
        parser = _SemanticParser("postgresql")

        assert parser._get_statement_type("UNKNOWN STATEMENT") == "UNKNOWN"
        assert parser._get_statement_type("") == "UNKNOWN"
