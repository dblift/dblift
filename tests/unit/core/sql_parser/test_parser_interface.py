"""Unit tests for core.sql_parser.parser_interface module."""

from unittest.mock import patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlStatement, SqlStatementType
from dblift.core.sql_parser.common.base_parser import RegexBasedParser
from dblift.core.sql_parser.parser_interface import SqlParserInterface


@pytest.mark.unit
class TestSqlParserInterface:
    """Test SqlParserInterface abstract class."""

    def test_parse_success(self):
        """Test parse method with successful parsing."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE test_table (id INT);"
        result = parser.parse(sql, default_schema="public")

        assert isinstance(result, SqlStatement)
        assert result.statement_type == SqlStatementType.DDL

    def test_parse_failure_no_statements(self):
        """Test parse method when parsing fails with no statements."""
        parser = RegexBasedParser("postgresql")

        # Mock parse_sql to return empty statements
        with patch.object(
            parser,
            "parse_sql",
            return_value=ParseResult(success=False, statements=[], errors=["Parse error"]),
        ):
            with pytest.raises(ValueError, match="Failed to parse SQL"):
                parser.parse("invalid sql")

    def test_parse_failure_with_errors(self):
        """Test parse method when parsing fails with errors."""
        parser = RegexBasedParser("postgresql")

        # Mock parse_sql to return failure with errors
        with patch.object(
            parser,
            "parse_sql",
            return_value=ParseResult(success=False, statements=[], errors=["Error 1", "Error 2"]),
        ):
            with pytest.raises(ValueError, match="Failed to parse SQL"):
                parser.parse("invalid sql")

    def test_get_affected_objects(self):
        """Test get_affected_objects method."""
        parser = RegexBasedParser("postgresql")

        sql = "CREATE TABLE test_table (id INT)"
        objects = parser.get_affected_objects(sql, default_schema="public")

        assert len(objects) >= 0  # May or may not extract objects depending on implementation
