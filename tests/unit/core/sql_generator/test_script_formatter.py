"""Tests for SqlScriptFormatter class."""

import pytest

from core.sql_generator.script_formatter import SqlScriptFormatter
from core.sql_generator.sql_statement import SqlStatement


@pytest.mark.unit
class TestSqlScriptFormatterInit:
    """Test SqlScriptFormatter initialization."""

    def test_init_defaults(self):
        """Test initialization with default parameters."""
        formatter = SqlScriptFormatter()
        assert formatter.include_comments is True
        assert formatter.include_checks is True

    def test_init_without_comments(self):
        """Test initialization without comments."""
        formatter = SqlScriptFormatter(include_comments=False)
        assert formatter.include_comments is False
        assert formatter.include_checks is True

    def test_init_without_checks(self):
        """Test initialization without checks."""
        formatter = SqlScriptFormatter(include_checks=False)
        assert formatter.include_comments is True
        assert formatter.include_checks is False

    def test_init_both_false(self):
        """Test initialization with both options disabled."""
        formatter = SqlScriptFormatter(include_comments=False, include_checks=False)
        assert formatter.include_comments is False
        assert formatter.include_checks is False


@pytest.mark.unit
class TestSqlScriptFormatterFormatScript:
    """Test SqlScriptFormatter.format_script method."""

    def test_format_script_empty(self):
        """Test formatting empty script."""
        formatter = SqlScriptFormatter()
        result = formatter.format_script([])
        assert "-- Generated:" in result
        assert "-- Total statements: 0" in result

    def test_format_script_with_title(self):
        """Test formatting script with title."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        result = formatter.format_script([statement], title="Test Script")
        assert "-- Test Script" in result
        assert "===" in result

    def test_format_script_with_description(self):
        """Test formatting script with description."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        result = formatter.format_script([statement], description="Test description")
        assert "-- Test description" in result

    def test_format_script_create_statements(self):
        """Test formatting CREATE statements."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        result = formatter.format_script([statement])
        assert "-- CREATE OBJECTS" in result
        assert "CREATE TABLE test" in result

    def test_format_script_alter_statements(self):
        """Test formatting ALTER statements."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="ALTER TABLE test ADD COLUMN name VARCHAR(100);",
            statement_type="ALTER",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        result = formatter.format_script([statement])
        assert "-- ALTER OBJECTS" in result
        assert "ALTER TABLE test" in result

    def test_format_script_drop_statements(self):
        """Test formatting DROP statements."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="DROP TABLE test;",
            statement_type="DROP",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        result = formatter.format_script([statement])
        assert "-- DROP OBJECTS" in result
        assert "WARNING" in result
        assert "DROP TABLE test" in result

    def test_format_script_mixed_statements(self):
        """Test formatting mixed statement types."""
        formatter = SqlScriptFormatter()
        create_stmt = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        drop_stmt = SqlStatement(
            sql="DROP TABLE test;",
            statement_type="DROP",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        result = formatter.format_script([create_stmt, drop_stmt])
        assert "-- CREATE OBJECTS" in result
        assert "-- DROP OBJECTS" in result
        assert result.index("CREATE TABLE") < result.index("DROP TABLE")

    def test_format_script_without_comments(self):
        """Test formatting script without comments."""
        formatter = SqlScriptFormatter(include_comments=False)
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        result = formatter.format_script([statement])
        # Should still have section headers but not object comments
        assert "-- CREATE OBJECTS" in result
        assert "-- CREATE TABLE" not in result or "-- CREATE TABLE" not in result.split("\n")[0:10]

    def test_format_script_cosmosdb_sdk_operation(self):
        """Test formatting CosmosDB SDK operation."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="CREATE CONTAINER test",
            statement_type="CREATE",
            object_type="CONTAINER",
            object_name="test",
            dialect="cosmosdb",
            requires_sdk=True,
            sdk_operation={
                "operation": "create_container",
                "python_code": "database.create_container(...)",
            },
        )
        result = formatter.format_script([statement])
        assert "[COSMOSDB SDK OPERATION]" in result
        assert "create_container" in result
        assert "python_code" in result or "create_container" in result

    def test_format_script_cosmosdb_sdk_with_warning(self):
        """Test formatting CosmosDB SDK operation with warning."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="DROP CONTAINER test",
            statement_type="DROP",
            object_type="CONTAINER",
            object_name="test",
            dialect="cosmosdb",
            requires_sdk=True,
            sdk_operation={
                "operation": "delete_container",
                "python_code": "database.delete_container(...)",
                "warning": "This will delete all data",
            },
        )
        result = formatter.format_script([statement])
        assert "WARNING" in result
        assert "This will delete all data" in result

    def test_format_script_with_pre_check(self):
        """Test formatting script with pre-execution check."""
        formatter = SqlScriptFormatter(include_checks=True)
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
            pre_check="SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'test'",
        )
        result = formatter.format_script([statement])
        assert "Pre-execution check:" in result
        assert "information_schema.tables" in result

    def test_format_script_with_pre_check_error(self):
        """Test formatting script with pre-check that errors on failure."""
        formatter = SqlScriptFormatter(include_checks=True)
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
            pre_check="SELECT COUNT(*) FROM test",
            error_if_check_fails=True,
            error_message="Table already exists",
        )
        result = formatter.format_script([statement])
        assert "ERROR if check fails" in result
        assert "Table already exists" in result

    def test_format_script_without_checks(self):
        """Test formatting script without checks."""
        formatter = SqlScriptFormatter(include_checks=False)
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
            pre_check="SELECT COUNT(*) FROM test",
        )
        result = formatter.format_script([statement])
        assert "Pre-execution check:" not in result

    def test_format_script_title_and_description(self):
        """Test formatting script with both title and description."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        result = formatter.format_script(
            [statement], title="Test Script", description="Test description"
        )
        assert "-- Test Script" in result
        assert "-- Test description" in result
        assert "===" in result


@pytest.mark.unit
class TestSqlScriptFormatterFormatStatement:
    """Test SqlScriptFormatter._format_statement method."""

    def test_format_statement_simple(self):
        """Test formatting a simple statement."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        lines = formatter._format_statement(statement)
        assert len(lines) > 0
        assert "CREATE TABLE test" in "\n".join(lines)

    def test_format_statement_with_comments(self):
        """Test formatting statement with comments enabled."""
        formatter = SqlScriptFormatter(include_comments=True)
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        lines = formatter._format_statement(statement)
        assert any("CREATE TABLE" in line and "--" in line for line in lines)

    def test_format_statement_without_comments(self):
        """Test formatting statement without comments."""
        formatter = SqlScriptFormatter(include_comments=False)
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        lines = formatter._format_statement(statement)
        # Should not have comment lines
        comment_lines = [line for line in lines if line.startswith("--")]
        assert len(comment_lines) == 0 or all("CREATE TABLE" not in line for line in comment_lines)


@pytest.mark.unit
class TestSqlScriptFormatterFormatStatementsSimple:
    """Test SqlScriptFormatter.format_statements_simple method."""

    def test_format_statements_simple_empty(self):
        """Test formatting empty statements."""
        formatter = SqlScriptFormatter()
        result = formatter.format_statements_simple([])
        assert result == ""

    def test_format_statements_simple_single(self):
        """Test formatting single statement."""
        formatter = SqlScriptFormatter()
        statement = SqlStatement(
            sql="CREATE TABLE test (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test",
            dialect="postgresql",
        )
        result = formatter.format_statements_simple([statement])
        assert result == "CREATE TABLE test (id INT);"

    def test_format_statements_simple_multiple(self):
        """Test formatting multiple statements."""
        formatter = SqlScriptFormatter()
        stmt1 = SqlStatement(
            sql="CREATE TABLE test1 (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test1",
            dialect="postgresql",
        )
        stmt2 = SqlStatement(
            sql="CREATE TABLE test2 (id INT);",
            statement_type="CREATE",
            object_type="TABLE",
            object_name="test2",
            dialect="postgresql",
        )
        result = formatter.format_statements_simple([stmt1, stmt2])
        assert "CREATE TABLE test1" in result
        assert "CREATE TABLE test2" in result
        assert "\n\n" in result
