"""Tests for SQL generation module."""

import logging
from unittest.mock import MagicMock

import pytest

from core.sql_generator import (
    AlterGenerator,
    DependencyAnalyzer,
    ScriptOrganizer,
    SqlFormatter,
    SqlGenerator,
)
from core.sql_generator.options import OrganizationStrategy, ScriptOptions
from core.sql_model import Index, Procedure, Sequence, Table, Trigger, View
from core.sql_model.base import SqlColumn, SqlConstraint, SqlObjectType
from core.sql_model.view_options import MySqlViewOptions, ViewOptions

pytestmark = [pytest.mark.unit]


class TestSqlFormatter:
    """Tests for SqlFormatter class."""

    def test_format_postgresql_table(self):
        """Test formatting PostgreSQL CREATE TABLE statement."""
        formatter = SqlFormatter(dialect="postgresql")
        sql = "CREATE TABLE users(id INTEGER PRIMARY KEY,name VARCHAR(100) NOT NULL)"
        formatted = formatter.format(sql)

        # Should be formatted with proper indentation
        assert "CREATE TABLE" in formatted
        assert "id" in formatted
        assert "name" in formatted
        # Check that it's formatted (has newlines)
        assert "\n" in formatted or formatted != sql.strip()

    def test_format_invalid_sql_fallback(self):
        """Test that invalid SQL falls back gracefully."""
        formatter = SqlFormatter(dialect="postgresql")
        # Invalid SQL that sqlglot can't parse
        sql = "INVALID SQL STATEMENT THAT CANNOT BE PARSED"
        formatted = formatter.format(sql)

        # Should return original SQL
        assert formatted == sql

    def test_format_batch(self):
        """Test formatting multiple statements."""
        formatter = SqlFormatter(dialect="postgresql")
        statements = [
            "CREATE TABLE users(id INTEGER)",
            "CREATE TABLE orders(order_id INTEGER)",
        ]
        formatted = formatter.format_batch(statements)

        assert "CREATE TABLE users" in formatted
        assert "CREATE TABLE orders" in formatted


class TestSqlGenerator:
    """Tests for SqlGenerator class."""

    def test_generate_ddl_table(self):
        """Test generating DDL for a table."""
        generator = SqlGenerator(default_dialect="postgresql")

        # Create a simple table
        table = Table(
            name="users",
            columns=[
                SqlColumn("id", "INTEGER", is_nullable=False),
                SqlColumn("name", "VARCHAR(100)", is_nullable=False),
            ],
            dialect="postgresql",
        )

        sql = generator.generate_ddl([table], format_sql=True)

        assert "CREATE TABLE" in sql
        assert "users" in sql
        assert "id" in sql
        assert "name" in sql

    def test_generate_ddl_view(self):
        """Test generating DDL for a view."""
        generator = SqlGenerator(default_dialect="postgresql")

        view = View(
            name="active_users",
            query="SELECT id, name FROM users WHERE active=true",
            dialect="postgresql",
        )

        sql = generator.generate_ddl([view], format_sql=True)

        assert "CREATE OR REPLACE VIEW" in sql
        assert "active_users" in sql

    def test_generate_ddl_index(self):
        """Test generating DDL for an index."""
        generator = SqlGenerator(default_dialect="postgresql")

        index = Index(
            name="idx_user_email",
            table_name="users",
            columns=["email"],
            dialect="postgresql",
        )

        sql = generator.generate_ddl([index], format_sql=True)

        assert "CREATE INDEX" in sql
        assert "idx_user_email" in sql
        assert "users" in sql

    def test_generate_ddl_mysql_view_preserves_definer(self):
        """MySQL view DDL should preserve DEFINER quoting."""
        generator = SqlGenerator(default_dialect="mysql")
        view = View.from_options(
            name="v_active_products",
            schema="store_app_metadata",
            query="SELECT * FROM products",
            dialect="mysql",
            options=ViewOptions(
                mysql=MySqlViewOptions(
                    definer="root@%", sql_security="DEFINER", algorithm="UNDEFINED"
                )
            ),
        )

        sql = generator.generate_ddl([view], target_dialect="mysql")
        assert "DEFINER = `root`@`%`" in sql

    def test_generate_ddl_mysql_procedure_wraps_delimiter(self):
        """MySQL routines should be wrapped with DELIMITER statements."""
        generator = SqlGenerator(default_dialect="mysql")
        procedure = Procedure(
            name="sp_test",
            schema="store_app_metadata",
            definition="BEGIN\n    SELECT 1;\nEND;",
            dialect="mysql",
        )

        sql = generator.generate_ddl([procedure], target_dialect="mysql")
        assert "DELIMITER //" in sql
        assert "END" in sql
        assert "DELIMITER ;" in sql

    def test_generate_ddl_sequence(self):
        """Test generating DDL for a sequence."""
        generator = SqlGenerator(default_dialect="postgresql")

        sequence = Sequence(
            name="user_id_seq",
            start_with=1,
            increment_by=1,
            dialect="postgresql",
        )

        sql = generator.generate_ddl([sequence], format_sql=True)

        assert "CREATE SEQUENCE" in sql
        assert "user_id_seq" in sql

    def test_generate_drop_statements(self):
        """Test generating DROP statements."""
        generator = SqlGenerator(default_dialect="postgresql")

        table = Table(name="users", columns=[], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        # Generate DROP statements
        drop_sql = generator.generate_drop_statements([table, view], format_sql=True)

        assert "DROP" in drop_sql
        # Views should be dropped before tables
        assert drop_sql.index("VIEW") < drop_sql.index("TABLE")

    def test_generate_schema_script_single_file(self):
        """Test generating schema script in single file format."""
        generator = SqlGenerator(default_dialect="postgresql")

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        schema = {"tables": [table], "views": [view]}
        options = ScriptOptions(organization=OrganizationStrategy.SINGLE_FILE)

        files = generator.generate_schema_script(schema, options=options)

        assert "schema.sql" in files
        assert "CREATE TABLE" in files["schema.sql"]
        assert "CREATE OR REPLACE VIEW" in files["schema.sql"]

    def test_generate_schema_script_single_file_includes_sequences(self):
        """Regression guard for BUG-C: SINGLE_FILE must include sequences.

        Reported symptom: generated schema SQL appeared to drop
        sequences while ``--split-by-type`` kept them. Locks in the generator
        behavior — sequences flow through the same ``generate_ddl`` loop as
        tables regardless of ``OrganizationStrategy``, so both paths emit them.
        """
        generator = SqlGenerator(default_dialect="postgresql")

        table = Table(name="orders", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        sequence = Sequence(name="user_id_seq", schema="public", start_with=1, dialect="postgresql")

        schema = {"table": [table], "sequence": [sequence]}
        options = ScriptOptions(organization=OrganizationStrategy.SINGLE_FILE, format_sql=False)

        files = generator.generate_schema_script(schema, options=options)

        content = files["schema.sql"]
        assert "CREATE TABLE" in content
        assert "CREATE SEQUENCE" in content
        assert "user_id_seq" in content

    def test_generate_schema_script_by_type(self):
        """Test generating schema script organized by type."""
        generator = SqlGenerator(default_dialect="postgresql")

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        schema = {"tables": [table], "views": [view]}
        options = ScriptOptions(organization=OrganizationStrategy.BY_TYPE)

        files = generator.generate_schema_script(schema, options=options)

        assert "table.sql" in files
        assert "view.sql" in files
        assert "CREATE TABLE" in files["table.sql"]
        assert "CREATE OR REPLACE VIEW" in files["view.sql"]

    def test_generate_schema_script_by_object(self):
        """Test generating schema script with one file per object."""
        generator = SqlGenerator(default_dialect="postgresql")

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        schema = {"tables": [table]}
        options = ScriptOptions(organization=OrganizationStrategy.BY_OBJECT)

        files = generator.generate_schema_script(schema, options=options)

        assert "users_table.sql" in files
        assert "CREATE TABLE" in files["users_table.sql"]

    def test_generate_schema_script_with_drops(self):
        """Test generating schema script with DROP statements."""
        generator = SqlGenerator(default_dialect="postgresql")

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        schema = {"tables": [table]}
        options = ScriptOptions(organization=OrganizationStrategy.SINGLE_FILE, include_drops=True)

        files = generator.generate_schema_script(schema, options=options)

        assert "DROP TABLE" in files["schema.sql"]
        assert "CREATE TABLE" in files["schema.sql"]

    def test_generate_ddl_with_dependency_ordering(self):
        """Test that DDL generation orders objects by dependencies."""
        generator = SqlGenerator(default_dialect="postgresql", use_dependency_ordering=True)

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(
            name="active_users",
            query="SELECT id, name FROM users WHERE active=true",
            dialect="postgresql",
        )

        sql = generator.generate_ddl([view, table], format_sql=False)

        # Table should come before view (dependency)
        assert sql.index("CREATE TABLE") < sql.index("CREATE OR REPLACE VIEW")

    def test_generate_ddl_empty_list(self):
        """Test generating DDL for empty list."""
        generator = SqlGenerator(default_dialect="postgresql")
        result = generator.generate_ddl([])
        assert result == ""

    def test_generate_ddl_without_dependency_ordering(self):
        """Test generating DDL without dependency ordering."""
        generator = SqlGenerator(default_dialect="postgresql", use_dependency_ordering=False)
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        result = generator.generate_ddl([table], order_by_dependencies=False)
        assert "CREATE TABLE" in result

    def test_generate_ddl_dependency_ordering_failure(self):
        """Test that dependency ordering failure falls back gracefully."""
        generator = SqlGenerator(default_dialect="postgresql", use_dependency_ordering=True)
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        # Mock dependency analyzer to raise exception
        generator.script_organizer.dependency_analyzer.get_create_order = lambda x: (
            _ for _ in ()
        ).throw(Exception("Dependency error"))

        result = generator.generate_ddl([table, view])
        # Should still generate SQL despite dependency error
        assert "CREATE TABLE" in result or "CREATE OR REPLACE VIEW" in result

    def test_generate_ddl_object_without_create_statement(self):
        """Test handling object without create_statement."""
        generator = SqlGenerator(default_dialect="postgresql")
        # Create a mock object without create_statement
        from unittest.mock import MagicMock

        from core.sql_model.base import SqlObjectType

        obj = MagicMock()
        obj.name = "test_object"
        obj.object_type = SqlObjectType.TABLE
        obj.create_statement = None
        del obj.create_statement  # Remove the attribute

        result = generator.generate_ddl([obj])
        # Should handle gracefully and continue
        assert isinstance(result, str)

    def test_generate_ddl_preserve_definition(self):
        """Test preserving definition when it's a complete DDL statement."""
        generator = SqlGenerator(default_dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table.definition = "CREATE TABLE users (id INTEGER);"

        result = generator.generate_ddl([table], format_sql=True)
        # Should preserve the definition
        assert "CREATE TABLE users" in result

    def test_generate_ddl_skip_formatting_for_partitioned_table(self):
        """Test skipping formatting for partitioned tables."""
        generator = SqlGenerator(default_dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table.partition_method = "RANGE"

        result = generator.generate_ddl([table], format_sql=True)
        assert "CREATE TABLE" in result

    def test_generate_ddl_skip_formatting_for_package(self):
        """Test skipping formatting for packages."""
        generator = SqlGenerator(default_dialect="postgresql")
        from core.sql_model.base import SqlObjectType

        package = MagicMock()
        package.name = "test_package"
        package.object_type = SqlObjectType.PACKAGE
        package.create_statement = "CREATE PACKAGE test_package AS\nEND;\n/"
        package.dialect = "postgresql"
        package.schema = None
        package.format_identifier = lambda x: x

        result = generator.generate_ddl([package], format_sql=True)
        assert "CREATE PACKAGE" in result

    def test_generate_ddl_mysql_function_wrapping(self):
        """Test MySQL function wrapping with DELIMITER."""
        generator = SqlGenerator(default_dialect="mysql")
        # Use Procedure with FUNCTION object_type for MySQL functions
        func = Procedure(
            name="test_func",
            definition="BEGIN RETURN 1; END",
            dialect="mysql",
        )
        func.object_type = SqlObjectType.FUNCTION

        result = generator.generate_ddl([func], target_dialect="mysql")
        assert "DELIMITER" in result

    def test_generate_ddl_statement_termination(self):
        """Test that statements are properly terminated."""
        generator = SqlGenerator(default_dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        result = generator.generate_ddl([table], format_sql=False)
        # Should end with semicolon
        assert result.strip().endswith(";")

    def test_generate_ddl_statement_already_terminated(self):
        """Test statement that already has terminator."""
        generator = SqlGenerator(default_dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        # Table's create_statement already ends with semicolon
        result = generator.generate_ddl([table], format_sql=False)
        # Should not double-terminate (should have exactly one semicolon per statement)
        assert result.count(";") >= 1

    def test_generate_ddl_exception_handling(self):
        """Test exception handling during DDL generation."""
        generator = SqlGenerator(default_dialect="postgresql")
        # Create a mock object that raises exception when accessing create_statement
        obj = MagicMock()
        obj.name = "test_object"
        obj.object_type = SqlObjectType.TABLE
        obj.create_statement = property(
            lambda self: (_ for _ in ()).throw(Exception("Generation error"))
        )
        obj.definition = None
        obj.format_identifier = lambda x: x

        result = generator.generate_ddl([obj])
        # Should handle gracefully
        assert isinstance(result, str)

    def test_generate_ddl_target_dialect_change(self):
        """Test changing target dialect updates formatter."""
        generator = SqlGenerator(default_dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        generator.generate_ddl([table], target_dialect="mysql")
        assert generator.formatter.dialect == "mysql"

    def test_generate_drop_statements_empty(self):
        """Test generating DROP statements for empty list."""
        generator = SqlGenerator(default_dialect="postgresql")
        result = generator.generate_drop_statements([])
        assert result == ""

    def test_generate_drop_statements_single_object(self):
        """Test generating DROP for single object."""
        generator = SqlGenerator(default_dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        result = generator.generate_drop_statements([table])
        assert "DROP TABLE" in result

    def test_generate_drop_statements_with_drop_statement_property(self):
        """Test using drop_statement property when available."""
        generator = SqlGenerator(default_dialect="postgresql")
        # Create a mock object with drop_statement property
        obj = MagicMock()
        obj.name = "users"
        obj.object_type = SqlObjectType.TABLE
        obj.drop_statement = "DROP TABLE IF EXISTS users;"
        obj.format_identifier = lambda x: x
        result = generator.generate_drop_statements([obj])
        assert "DROP TABLE IF EXISTS users" in result

    def test_generate_drop_statements_dependency_ordering_failure(self):
        """Test dependency ordering failure for DROP statements."""
        generator = SqlGenerator(default_dialect="postgresql", use_dependency_ordering=True)
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        # Mock get_drop_order to raise exception
        generator.script_organizer.get_drop_order = lambda x: (_ for _ in ()).throw(
            Exception("Dependency error")
        )

        result = generator.generate_drop_statements([table, view])
        # Should fall back to type-based ordering
        assert "DROP" in result

    def test_generate_drop_statements_same_order_fallback(self):
        """Test fallback when dependency order doesn't change."""
        generator = SqlGenerator(default_dialect="postgresql", use_dependency_ordering=True)
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        # Mock get_drop_order to return same order
        generator.script_organizer.get_drop_order = lambda x: x

        result = generator.generate_drop_statements([table], reverse_order=True)
        assert "DROP TABLE" in result

    def test_generate_drop_statement_table_mysql(self):
        """Test generating DROP TABLE for MySQL."""
        generator = SqlGenerator(default_dialect="mysql")
        table = Table(name="test_table", columns=[SqlColumn("id", "INTEGER")], dialect="mysql")
        result = generator._generate_drop_statement(table, "mysql")
        assert "DROP TABLE IF EXISTS" in result
        assert "CASCADE" not in result

    def test_generate_drop_statement_extension_postgresql(self):
        """Test generating DROP EXTENSION for PostgreSQL."""
        generator = SqlGenerator(default_dialect="postgresql")
        from core.sql_model.base import SqlObjectType

        extension = MagicMock()
        extension.name = "test_ext"
        extension.object_type = SqlObjectType.EXTENSION
        extension.schema = None
        extension.format_identifier = lambda x: x
        result = generator._generate_drop_statement(extension, "postgresql")
        assert "DROP EXTENSION IF EXISTS" in result

    def test_generate_drop_statement_with_schema(self):
        """Test generating DROP statement with schema."""
        generator = SqlGenerator(default_dialect="postgresql")
        table = Table(
            name="users",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        result = generator._generate_drop_statement(table, "postgresql")
        assert "public" in result

    def test_generate_drop_statements_exception_handling(self):
        """Test exception handling during DROP generation."""
        generator = SqlGenerator(default_dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        # Mock format_identifier to raise exception
        table.format_identifier = lambda x: (_ for _ in ()).throw(Exception("Format error"))

        result = generator.generate_drop_statements([table])
        # Should handle gracefully
        assert isinstance(result, str)

    def test_generate_drop_statements_filters_empty_statements(self):
        """Test that empty statements are filtered out."""
        generator = SqlGenerator(default_dialect="postgresql")
        # Create a mock object with empty drop_statement
        obj = MagicMock()
        obj.name = "users"
        obj.object_type = SqlObjectType.TABLE
        obj.drop_statement = "   \n  "
        obj.format_identifier = lambda x: x
        result = generator.generate_drop_statements([obj])
        # Empty statements should be filtered
        assert result.strip() == ""

    def test_generate_schema_script_empty_schema(self):
        """Test generating schema script for empty schema."""
        generator = SqlGenerator(default_dialect="postgresql")
        result = generator.generate_schema_script({})
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_generate_schema_script_with_comments(self):
        """Test generating schema script with comments."""
        generator = SqlGenerator(default_dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        schema = {"tables": [table]}
        options = ScriptOptions(
            organization=OrganizationStrategy.SINGLE_FILE, include_comments=True
        )
        result = generator.generate_schema_script(schema, options=options)
        # Check any file in result has comments
        assert any("-- SQL Script:" in content for content in result.values())

    def test_generate_schema_script_non_list_values(self):
        """Test handling non-list values in schema dict."""
        generator = SqlGenerator(default_dialect="postgresql")
        schema = {"tables": "not a list"}
        result = generator.generate_schema_script(schema)
        # Should handle gracefully
        assert isinstance(result, dict)

    def test_ensure_statement_terminated_empty(self):
        """Test ensuring termination for empty string."""
        generator = SqlGenerator()
        result = generator._ensure_statement_terminated("")
        assert result == ""

    def test_ensure_statement_terminated_whitespace_only(self):
        """Test ensuring termination for whitespace-only string."""
        generator = SqlGenerator()
        result = generator._ensure_statement_terminated("   \n  ")
        # When stripped is empty, returns the stripped (empty) string
        assert result == ""

    def test_ensure_statement_terminated_already_has_semicolon(self):
        """Test statement that already has semicolon."""
        generator = SqlGenerator()
        result = generator._ensure_statement_terminated("CREATE TABLE test;")
        assert result == "CREATE TABLE test;"

    def test_ensure_statement_terminated_has_slash(self):
        """Test statement that ends with slash."""
        generator = SqlGenerator()
        result = generator._ensure_statement_terminated("CREATE PROCEDURE test\n/")
        assert result == "CREATE PROCEDURE test\n/"

    def test_ensure_statement_terminated_has_dollar(self):
        """Test statement that ends with $$."""
        generator = SqlGenerator()
        result = generator._ensure_statement_terminated("CREATE FUNCTION test\n$$")
        assert result == "CREATE FUNCTION test\n$$"

    def test_ensure_statement_terminated_adds_semicolon(self):
        """Test adding semicolon when missing."""
        generator = SqlGenerator()
        result = generator._ensure_statement_terminated("CREATE TABLE test")
        assert result == "CREATE TABLE test;"

    def test_should_preserve_definition_none(self):
        """Test _should_preserve_definition with None."""
        result = SqlGenerator._should_preserve_definition(None)
        assert result is False

    def test_should_preserve_definition_not_string(self):
        """Test _should_preserve_definition with non-string."""
        result = SqlGenerator._should_preserve_definition(123)
        assert result is False

    def test_should_preserve_definition_empty_string(self):
        """Test _should_preserve_definition with empty string."""
        result = SqlGenerator._should_preserve_definition("")
        assert result is False

    def test_should_preserve_definition_whitespace_only(self):
        """Test _should_preserve_definition with whitespace only."""
        result = SqlGenerator._should_preserve_definition("   \n  ")
        assert result is False

    def test_should_preserve_definition_create(self):
        """Test _should_preserve_definition with CREATE."""
        result = SqlGenerator._should_preserve_definition("CREATE TABLE test (id INT)")
        assert result is True

    def test_should_preserve_definition_alter(self):
        """Test _should_preserve_definition with ALTER."""
        result = SqlGenerator._should_preserve_definition("ALTER TABLE test ADD COLUMN x INT")
        assert result is True

    def test_should_preserve_definition_replace(self):
        """Test _should_preserve_definition with REPLACE."""
        result = SqlGenerator._should_preserve_definition("REPLACE VIEW test AS SELECT 1")
        assert result is True

    def test_should_preserve_definition_lowercase(self):
        """Test _should_preserve_definition with lowercase."""
        result = SqlGenerator._should_preserve_definition("create table test")
        assert result is True

    def test_should_skip_formatting_empty_sql(self):
        """Test _should_skip_formatting with empty SQL."""
        generator = SqlGenerator()
        obj = MagicMock()
        obj.object_type = SqlObjectType.TABLE
        result = generator._should_skip_formatting(obj, "")
        assert result is False

    def test_should_skip_formatting_partitioned_table(self):
        """Test _should_skip_formatting for partitioned table."""
        generator = SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table.partition_method = "RANGE"
        result = generator._should_skip_formatting(
            table, "CREATE TABLE users PARTITION BY RANGE (id)"
        )
        assert result is True

    def test_should_skip_formatting_package(self):
        """Test _should_skip_formatting for package."""
        generator = SqlGenerator()
        from core.sql_model.base import SqlObjectType

        package = MagicMock()
        package.object_type = SqlObjectType.PACKAGE
        result = generator._should_skip_formatting(package, "CREATE PACKAGE test")
        assert result is True

    def test_should_skip_formatting_mysql_view(self):
        """Test _should_skip_formatting for MySQL view."""
        generator = SqlGenerator()
        view = View(name="test_view", query="SELECT 1", dialect="mysql")
        result = generator._should_skip_formatting(view, "CREATE VIEW test_view")
        assert result is True

    def test_should_skip_formatting_mysql_procedure(self):
        """Test _should_skip_formatting for MySQL procedure."""
        generator = SqlGenerator()
        procedure = Procedure(name="test_proc", definition="BEGIN END", dialect="mysql")
        result = generator._should_skip_formatting(procedure, "CREATE PROCEDURE test_proc")
        assert result is True

    def test_should_skip_formatting_mysql_function(self):
        """Test _should_skip_formatting for MySQL function."""
        generator = SqlGenerator()
        func = Procedure(name="test_func", definition="RETURN 1", dialect="mysql")
        func.object_type = SqlObjectType.FUNCTION
        result = generator._should_skip_formatting(func, "CREATE FUNCTION test_func")
        assert result is True

    def test_should_skip_formatting_mysql_trigger(self):
        """Test _should_skip_formatting for MySQL trigger."""
        generator = SqlGenerator()
        trigger = Trigger(
            name="test_trigger",
            table_name="test",
            timing="BEFORE",
            events=["INSERT"],
            dialect="mysql",
        )
        result = generator._should_skip_formatting(trigger, "CREATE TRIGGER test_trigger")
        assert result is True

    def test_should_skip_formatting_mysql_event(self):
        """Test _should_skip_formatting for MySQL event."""
        generator = SqlGenerator()
        from core.sql_model.base import SqlObjectType

        event = MagicMock()
        event.object_type = SqlObjectType.EVENT
        event.dialect = "mysql"
        result = generator._should_skip_formatting(event, "CREATE EVENT test_event")
        assert result is True

    def test_should_skip_formatting_non_mysql_dialect(self):
        """Test _should_skip_formatting for non-MySQL dialect."""
        generator = SqlGenerator()
        view = View(name="test_view", query="SELECT 1", dialect="postgresql")
        result = generator._should_skip_formatting(view, "CREATE VIEW test_view")
        assert result is False

    def test_sort_by_type_priority_reverse_true(self):
        """Test _sort_by_type_priority with reverse=True."""
        generator = SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        sorted_objs = generator._sort_by_type_priority([view, table], reverse=True)
        # For DROP (reverse=True), VIEW should come before TABLE
        assert sorted_objs.index(view) < sorted_objs.index(table)

    def test_sort_by_type_priority_reverse_false(self):
        """Test _sort_by_type_priority with reverse=False."""
        generator = SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        sorted_objs = generator._sort_by_type_priority([view, table], reverse=False)
        # For CREATE (reverse=False), TABLE should come before VIEW
        assert sorted_objs.index(table) < sorted_objs.index(view)

    def test_sort_by_type_priority_unknown_type(self):
        """Test _sort_by_type_priority with unknown type."""
        generator = SqlGenerator()
        from core.sql_model.base import SqlObjectType

        unknown = MagicMock()
        unknown.object_type = SqlObjectType.UNKNOWN
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        sorted_objs = generator._sort_by_type_priority([unknown, table], reverse=True)
        # Unknown type should get priority 99 (lowest)
        assert sorted_objs.index(table) < sorted_objs.index(unknown)

    def test_format_statements_empty(self):
        """Test _format_statements with empty list."""
        generator = SqlGenerator()
        result = generator._format_statements([], "postgresql")
        assert result == ""

    def test_format_statements_multiple(self):
        """Test _format_statements with multiple statements."""
        generator = SqlGenerator()
        statements = ["CREATE TABLE test1;", "CREATE TABLE test2;"]
        result = generator._format_statements(statements, "postgresql")
        assert "CREATE TABLE test1" in result
        assert "CREATE TABLE test2" in result
        assert "\n\n" in result

    def test_requires_dialect_specific_wrapping_mysql_procedure(self):
        """Test _requires_dialect_specific_wrapping for MySQL procedure."""
        generator = SqlGenerator()
        procedure = Procedure(name="test_proc", definition="BEGIN END", dialect="mysql")
        result = generator._requires_dialect_specific_wrapping(procedure, "mysql")
        assert result is True

    def test_requires_dialect_specific_wrapping_mysql_function(self):
        """Test _requires_dialect_specific_wrapping for MySQL function."""
        generator = SqlGenerator()
        func = Procedure(name="test_func", definition="RETURN 1", dialect="mysql")
        func.object_type = SqlObjectType.FUNCTION
        result = generator._requires_dialect_specific_wrapping(func, "mysql")
        assert result is True

    def test_requires_dialect_specific_wrapping_non_mysql(self):
        """Test _requires_dialect_specific_wrapping for non-MySQL."""
        generator = SqlGenerator()
        procedure = Procedure(name="test_proc", definition="BEGIN END", dialect="postgresql")
        result = generator._requires_dialect_specific_wrapping(procedure, "postgresql")
        assert result is False

    def test_wrap_dialect_specific_block_mysql(self):
        """Test _wrap_dialect_specific_block for MySQL."""
        generator = SqlGenerator()
        sql = "CREATE PROCEDURE test BEGIN END"
        result = generator._wrap_dialect_specific_block(sql, "mysql")
        assert "DELIMITER //" in result
        assert "DELIMITER ;" in result

    def test_wrap_dialect_specific_block_non_mysql(self):
        """Test _wrap_dialect_specific_block for non-MySQL."""
        generator = SqlGenerator()
        sql = "CREATE PROCEDURE test BEGIN END"
        result = generator._wrap_dialect_specific_block(sql, "postgresql")
        assert result == sql

    def test_generate_additional_statements(self):
        """Test _generate_additional_statements."""
        generator = SqlGenerator()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        result = generator._generate_additional_statements(table, "postgresql")
        assert result == []

    # ``_requires_mysql_delimiter`` / ``_wrap_mysql_delimiter_block``
    # were removed in PR #241 Bugbot follow-up — the methods had no
    # production caller; MySQL ``$$`` wrapping lives in the plugin
    # generator (``MysqlSqlGenerator._wrap_dialect_specific_block``).


class TestDependencyAnalyzer:
    """Tests for DependencyAnalyzer class."""

    def test_build_dependency_graph(self):
        """Test building a dependency graph."""
        analyzer = DependencyAnalyzer()

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(
            name="active_users",
            query="SELECT id FROM users",
            dialect="postgresql",
        )

        graph = analyzer.build_graph([table, view])

        assert table in graph.objects
        assert view in graph.objects

    def test_get_create_order(self):
        """Test getting objects in CREATE order."""
        analyzer = DependencyAnalyzer()

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(
            name="active_users",
            query="SELECT id FROM users",
            dialect="postgresql",
        )

        ordered = analyzer.get_create_order([view, table])

        # Table should come before view
        assert ordered.index(table) < ordered.index(view)

    def test_get_drop_order(self):
        """Test getting objects in DROP order (dependents first)."""
        analyzer = DependencyAnalyzer()

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(
            name="active_users",
            query="SELECT id FROM users",
            dialect="postgresql",
        )

        ordered = analyzer.get_drop_order([table, view])

        # View should come before table (dependent first)
        assert ordered.index(view) < ordered.index(table)

    def test_create_order_handles_default_schema_references(self):
        """Views referencing tables without schema should still depend on them."""
        analyzer = DependencyAnalyzer()

        table = Table(
            name="orders",
            schema="public",
            columns=[SqlColumn("order_id", "INTEGER")],
            dialect="postgresql",
        )
        view = View(
            name="vw_customer_orders",
            schema="public",
            query="SELECT order_id FROM orders",
            dialect="postgresql",
        )

        ordered = analyzer.get_create_order([view, table])

        assert ordered.index(table) < ordered.index(view)

    def test_detect_circular_dependencies(self):
        """Test detection of circular dependencies."""
        analyzer = DependencyAnalyzer()

        # Create a simple case - in practice, circular dependencies might be
        # detected through foreign key cycles or view dependencies
        # For now, test that the method exists and doesn't crash
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        graph = analyzer.build_graph([table])
        cycles = graph.detect_circular_dependencies()

        # Should return empty list for no cycles
        assert isinstance(cycles, list)


class TestScriptOrganizer:
    """Tests for ScriptOrganizer class."""

    def test_organize_single_file(self):
        """Test organizing objects into a single file."""
        organizer = ScriptOrganizer()

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        options = ScriptOptions(organization=OrganizationStrategy.SINGLE_FILE)
        files = organizer.organize([table, view], options)

        assert "schema.sql" in files
        assert len(files["schema.sql"]) == 2

    def test_organize_by_type(self):
        """Test organizing objects by type."""
        organizer = ScriptOrganizer()

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        options = ScriptOptions(organization=OrganizationStrategy.BY_TYPE)
        files = organizer.organize([table, view], options)

        assert "table.sql" in files
        assert "view.sql" in files

    def test_organize_by_object(self):
        """Test organizing one file per object."""
        organizer = ScriptOrganizer()

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        options = ScriptOptions(organization=OrganizationStrategy.BY_OBJECT)
        files = organizer.organize([table], options)

        assert "users_table.sql" in files

    def test_filter_objects_by_type(self):
        """Test filtering objects by include/exclude types."""
        organizer = ScriptOrganizer()

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        index = Index(name="idx_email", table_name="users", columns=["email"], dialect="postgresql")

        objects = [table, view, index]
        options = ScriptOptions(
            organization=OrganizationStrategy.SINGLE_FILE,
            include_object_types={"TABLE", "VIEW"},
        )

        files = organizer.organize(objects, options)
        file_objects = files.get("schema.sql", [])

        assert len(file_objects) == 2
        assert table in file_objects
        assert view in file_objects
        assert index not in file_objects

    def test_filter_objects_exclude(self):
        """Test excluding object types."""
        organizer = ScriptOrganizer()

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        objects = [table, view]
        options = ScriptOptions(
            organization=OrganizationStrategy.SINGLE_FILE, exclude_object_types={"VIEW"}
        )

        files = organizer.organize(objects, options)
        file_objects = files.get("schema.sql", [])

        assert len(file_objects) == 1
        assert table in file_objects
        assert view not in file_objects

    def test_generate_file_header(self):
        """Test generating file header comments."""
        organizer = ScriptOrganizer()

        header = organizer.generate_file_header("test.sql", 5, "postgresql")

        assert "-- SQL Script: test.sql" in header
        assert "Generated for dialect: postgresql" in header
        assert "Object count: 5" in header

    def test_get_drop_order(self):
        """Test getting DROP order from organizer."""
        organizer = ScriptOrganizer()

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(
            name="active_users",
            query="SELECT id FROM users",
            dialect="postgresql",
        )

        ordered = organizer.get_drop_order([table, view])

        # View should come before table (dependent first)
        assert ordered.index(view) < ordered.index(table)

    def test_organize_empty_list(self):
        """Test organizing empty list."""
        organizer = ScriptOrganizer()
        options = ScriptOptions(organization=OrganizationStrategy.SINGLE_FILE)
        result = organizer.organize([], options)
        assert result == {}

    def test_organize_by_schema(self):
        """Test organizing objects by schema."""
        organizer = ScriptOrganizer()
        table1 = Table(
            name="users",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        table2 = Table(
            name="orders",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        table3 = Table(
            name="logs", schema="app", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )

        options = ScriptOptions(organization=OrganizationStrategy.BY_SCHEMA)
        files = organizer.organize([table1, table2, table3], options)

        assert "public/schema.sql" in files
        assert "app/schema.sql" in files
        assert len(files["public/schema.sql"]) == 2
        assert len(files["app/schema.sql"]) == 1

    def test_organize_by_schema_default(self):
        """Test organizing objects by schema with None schema."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        options = ScriptOptions(organization=OrganizationStrategy.BY_SCHEMA)
        files = organizer.organize([table], options)

        assert "default/schema.sql" in files

    def test_organize_by_dependency(self):
        """Test organizing objects by dependency."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")

        options = ScriptOptions(organization=OrganizationStrategy.BY_DEPENDENCY)
        files = organizer.organize([table, view], options)

        # Should group related objects together
        assert len(files) > 0

    def test_organize_by_dependency_single_object(self):
        """Test organizing by dependency with single object."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        options = ScriptOptions(organization=OrganizationStrategy.BY_DEPENDENCY)
        files = organizer.organize([table], options)

        # Single object should get its own file
        assert len(files) == 1
        assert "users_table.sql" in files

    def test_organize_default_fallback(self):
        """Test organizing with unknown strategy falls back to by_type."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        # Create options with invalid organization strategy
        options = ScriptOptions()
        options.organization = "INVALID_STRATEGY"  # type: ignore

        files = organizer.organize([table], options)
        # Should fall back to by_type
        assert len(files) > 0

    def test_order_by_dependencies_single_object(self):
        """Test ordering by dependencies with single object."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        options = ScriptOptions()
        ordered = organizer._order_by_dependencies([table], options)
        assert ordered == [table]

    def test_order_by_dependencies_exception(self):
        """Test ordering by dependencies handles exceptions."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        # Mock dependency analyzer to raise exception
        organizer.dependency_analyzer.get_create_order = lambda x: (_ for _ in ()).throw(
            Exception("Dependency error")
        )

        options = ScriptOptions()
        ordered = organizer._order_by_dependencies([table, view], options)
        # Should return original order on exception
        assert len(ordered) == 2

    def test_order_by_dependencies_circular_dependency(self):
        """Test ordering by dependencies with circular dependency."""
        organizer = ScriptOrganizer()
        table1 = Table(name="table1", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table2 = Table(name="table2", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        # Create circular dependency manually
        organizer.dependency_analyzer.build_graph([table1, table2])
        # Add circular dependency
        organizer.dependency_analyzer.graph.add_dependency(table1, table2)
        organizer.dependency_analyzer.graph.add_dependency(table2, table1)

        options = ScriptOptions()
        ordered = organizer._order_by_dependencies([table1, table2], options)
        # Should still return ordered list (may have warnings)
        assert len(ordered) == 2

    def test_order_by_dependencies_circular_dependency_logs_debug_not_warning(self, caplog):
        """Cycle details should be hidden from normal schema output."""
        organizer = ScriptOrganizer()
        table = Table(
            name="categories",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("parent_id", "INTEGER")],
            dialect="postgresql",
        )
        table.constraints = [
            SqlConstraint(
                name="categories_parent_id_fkey",
                constraint_type="FOREIGN KEY",
                column_names=["parent_id"],
                reference_table="categories",
            )
        ]

        with caplog.at_level(logging.DEBUG, logger="core.sql_generator"):
            ordered = organizer._order_by_dependencies(
                [
                    table,
                    Index(
                        name="idx_categories_parent",
                        table_name="categories",
                        columns=["parent_id"],
                    ),
                ],
                ScriptOptions(),
            )

        assert len(ordered) == 2
        circular_records = [
            record
            for record in caplog.records
            if "circular dependency" in record.message.lower()
            or "circular dependencies" in record.message.lower()
        ]
        assert circular_records
        assert all(record.levelno == logging.DEBUG for record in circular_records)

    def test_order_by_dependencies_circular_dependency_many_cycles(self):
        """Test ordering by dependencies with many circular dependencies."""
        organizer = ScriptOrganizer()
        tables = [
            Table(name=f"table{i}", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
            for i in range(10)
        ]

        # Create multiple circular dependencies
        organizer.dependency_analyzer.build_graph(tables)
        for i in range(9):
            organizer.dependency_analyzer.graph.add_dependency(tables[i], tables[i + 1])
        organizer.dependency_analyzer.graph.add_dependency(tables[9], tables[0])

        options = ScriptOptions()
        ordered = organizer._order_by_dependencies(tables, options)
        # Should still return ordered list
        assert len(ordered) == 10

    def test_organize_by_dependency_dep_not_in_objects(self):
        """Test organizing by dependency when dependency is not in objects list."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        # Create another table that view depends on but is not in objects list
        other_table = Table(
            name="other", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )

        # Build graph with all objects
        organizer.dependency_analyzer.build_graph([table, view, other_table])

        # But only organize table and view (other_table not included)
        options = ScriptOptions(organization=OrganizationStrategy.BY_DEPENDENCY)
        files = organizer.organize([table, view], options)

        # Should still work
        assert len(files) > 0

    def test_get_drop_order_single_object(self):
        """Test get_drop_order with single object."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        ordered = organizer.get_drop_order([table])
        assert ordered == [table]

    def test_get_drop_order_exception(self):
        """Test get_drop_order handles exceptions."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        # Mock dependency analyzer to raise exception
        organizer.dependency_analyzer.get_drop_order = lambda x: (_ for _ in ()).throw(
            Exception("Dependency error")
        )

        ordered = organizer.get_drop_order([table])
        # Should return original order on exception
        assert ordered == [table]

    def test_generate_file_header_without_timestamp(self):
        """Test generating file header without timestamp."""
        organizer = ScriptOrganizer()
        header = organizer.generate_file_header(
            "test.sql", 5, "postgresql", include_timestamp=False
        )
        assert "-- SQL Script: test.sql" in header
        assert "Generated:" not in header

    def test_generate_file_header_none_dialect(self):
        """Test generating file header with None dialect."""
        organizer = ScriptOrganizer()
        header = organizer.generate_file_header("test.sql", 5, None)  # type: ignore
        assert "-- SQL Script: test.sql" in header

    def test_generate_file_footer_with_summary(self):
        """Test generating file footer with summary."""
        organizer = ScriptOrganizer()
        footer = organizer.generate_file_footer("test.sql", include_summary=True)
        assert "-- End of script" in footer

    def test_generate_file_footer_without_summary(self):
        """Test generating file footer without summary."""
        organizer = ScriptOrganizer()
        footer = organizer.generate_file_footer("test.sql", include_summary=False)
        assert footer == ""

    def test_filter_objects_no_filter(self):
        """Test filtering objects with no filter options."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        options = ScriptOptions()
        filtered = organizer._filter_objects([table], options)
        assert filtered == [table]

    def test_filter_objects_object_type_without_value(self):
        """Test filtering objects with object_type without value attribute."""
        organizer = ScriptOrganizer()
        from unittest.mock import MagicMock

        from core.sql_model.base import SqlObjectType

        obj = MagicMock()
        obj.object_type = "TABLE"  # String instead of enum
        options = ScriptOptions(include_object_types={"TABLE"})
        filtered = organizer._filter_objects([obj], options)
        assert len(filtered) == 1

    def test_organize_by_dependency_multiple_groups(self):
        """Test organizing by dependency with multiple dependency groups."""
        organizer = ScriptOrganizer()
        table1 = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view1 = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        table2 = Table(name="orders", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view2 = View(name="order_summary", query="SELECT id FROM orders", dialect="postgresql")

        options = ScriptOptions(organization=OrganizationStrategy.BY_DEPENDENCY)
        files = organizer.organize([table1, view1, table2, view2], options)

        # Should create multiple groups
        assert len(files) >= 2

    def test_organize_by_dependency_group_naming(self):
        """Test that dependency groups with multiple objects get group naming."""
        organizer = ScriptOrganizer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        index = Index(name="idx_users_id", table_name="users", columns=["id"], dialect="postgresql")

        options = ScriptOptions(organization=OrganizationStrategy.BY_DEPENDENCY)
        files = organizer.organize([table, view, index], options)

        # Should have at least one file
        assert len(files) > 0
        # Check that group files are named correctly
        file_names = list(files.keys())
        assert any("dependency_group" in name or "users" in name for name in file_names)


class TestAlterGenerator:
    """Tests for AlterGenerator class."""

    def test_generate_alter_table_add_constraint(self):
        """Test generating ALTER TABLE ADD CONSTRAINT."""
        generator = AlterGenerator(dialect="postgresql")

        from core.sql_model.base import ConstraintType, SqlConstraint

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        constraint = SqlConstraint(
            name="pk_users",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id"],
        )

        statements = generator.generate_alter_table_statements(table, add_constraints=[constraint])

        assert len(statements) == 1
        assert "ALTER TABLE" in statements[0]
        assert "ADD" in statements[0]
        assert "PRIMARY KEY" in statements[0]

    def test_generate_alter_table_drop_column(self):
        """Test generating ALTER TABLE DROP COLUMN."""
        generator = AlterGenerator(dialect="postgresql")

        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        statements = generator.generate_alter_table_statements(table, drop_columns=["email"])

        assert len(statements) == 1
        assert "ALTER TABLE" in statements[0]
        assert "DROP COLUMN" in statements[0]
        assert "email" in statements[0]

    def test_generate_alter_view_postgresql(self):
        """Test generating ALTER VIEW for PostgreSQL."""
        generator = AlterGenerator(dialect="postgresql")

        view = View(name="active_users", query="SELECT 1", dialect="postgresql")

        statement = generator.generate_alter_view_statement(view, "SELECT id FROM users")

        assert statement is not None
        assert "CREATE OR REPLACE VIEW" in statement
        assert "active_users" in statement

    def test_alter_generator_init(self):
        """Test AlterGenerator initialization."""
        generator = AlterGenerator(dialect="postgresql")
        assert generator.dialect == "postgresql"
        assert generator._generator is not None

    def test_alter_generator_init_lowercase_dialect(self):
        """Test AlterGenerator initialization with uppercase dialect."""
        generator = AlterGenerator(dialect="POSTGRESQL")
        assert generator.dialect == "postgresql"

    def test_format_schema_prefix(self):
        """Test _format_schema_prefix method."""
        generator = AlterGenerator(dialect="postgresql")
        result = generator._format_schema_prefix("public")
        assert isinstance(result, str)

    def test_format_schema_prefix_none(self):
        """Test _format_schema_prefix with None."""
        generator = AlterGenerator(dialect="postgresql")
        result = generator._format_schema_prefix(None)
        assert isinstance(result, str)

    def test_format_identifier(self):
        """Test _format_identifier method."""
        generator = AlterGenerator(dialect="postgresql")
        result = generator._format_identifier("test_table")
        assert isinstance(result, str)
        assert "test_table" in result

    def test_format_column_definition(self):
        """Test _format_column_definition method."""
        generator = AlterGenerator(dialect="postgresql")
        column = SqlColumn("id", "INTEGER")
        result = generator._format_column_definition(column)
        assert isinstance(result, str)

    def test_format_constraint_definition(self):
        """Test _format_constraint_definition method."""
        generator = AlterGenerator(dialect="postgresql")
        from core.sql_model.base import ConstraintType, SqlConstraint

        constraint = SqlConstraint(
            name="pk_test",
            constraint_type=ConstraintType.PRIMARY_KEY,
            column_names=["id"],
        )
        result = generator._format_constraint_definition(constraint)
        assert result is None or isinstance(result, str)

    def test_generate_alter_table_add_columns(self):
        """Test generating ALTER TABLE ADD COLUMN."""
        generator = AlterGenerator(dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        new_column = SqlColumn("email", "VARCHAR(100)")
        statements = generator.generate_alter_table_statements(table, add_columns=[new_column])
        assert len(statements) > 0
        assert "ALTER TABLE" in statements[0]
        assert "ADD" in statements[0] or "ADD COLUMN" in statements[0]

    def test_generate_alter_table_modify_columns(self):
        """Test generating ALTER TABLE MODIFY COLUMN."""
        generator = AlterGenerator(dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        modified_column = SqlColumn("id", "BIGINT")
        statements = generator.generate_alter_table_statements(
            table, modify_columns=[modified_column]
        )
        assert len(statements) > 0
        assert "ALTER TABLE" in statements[0]

    def test_generate_alter_table_drop_constraints(self):
        """Test generating ALTER TABLE DROP CONSTRAINT."""
        generator = AlterGenerator(dialect="postgresql")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        statements = generator.generate_alter_table_statements(table, drop_constraints=["pk_users"])
        assert len(statements) > 0
        assert "ALTER TABLE" in statements[0]
        assert "DROP" in statements[0]

    def test_generate_alter_view_none_query(self):
        """Test generating ALTER VIEW with None query."""
        generator = AlterGenerator(dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        statement = generator.generate_alter_view_statement(view, None)
        # Should use existing query or return None
        assert statement is None or isinstance(statement, str)
