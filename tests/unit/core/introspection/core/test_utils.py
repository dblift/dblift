"""Comprehensive tests for core.introspection._utils module."""

import json

import pytest

from core.introspection._utils import (
    get_row_value,
    parse_json_array,
    parse_pg_options,
    strip_leading_comments,
    to_int,
)


@pytest.mark.unit
class TestGetRowValue:
    """Test suite for get_row_value() function."""

    def test_get_row_value_lowercase_key(self):
        """Test get_row_value() with lowercase key (PostgreSQL, MySQL, SQL Server)."""
        row = {"name": "users", "schema": "public", "type": "TABLE"}

        assert get_row_value(row, "name") == "users"
        assert get_row_value(row, "schema") == "public"
        assert get_row_value(row, "type") == "TABLE"

    def test_get_row_value_uppercase_key(self):
        """Test get_row_value() with uppercase key (Oracle)."""
        row = {"NAME": "users", "SCHEMA": "public", "TYPE": "TABLE"}

        assert get_row_value(row, "name") == "users"
        assert get_row_value(row, "schema") == "public"
        assert get_row_value(row, "type") == "TABLE"

    def test_get_row_value_returns_none_when_not_found(self):
        """Test get_row_value() returns None when key not found."""
        row = {"name": "users"}

        assert get_row_value(row, "nonexistent") is None

    def test_get_row_value_handles_db2_underscore_stripping(self):
        """Test get_row_value() handles DB2 underscore stripping."""
        row = {"viewdefinition": "SELECT 1"}

        assert get_row_value(row, "view_definition") == "SELECT 1"

    def test_get_row_value_handles_db2_abbreviations(self):
        """Test get_row_value() handles DB2 abbreviations."""
        row = {"seqname": "my_seq", "tabname": "my_table", "trigname": "my_trigger"}

        assert get_row_value(row, "sequence_name") == "my_seq"
        assert get_row_value(row, "table_name") == "my_table"
        assert get_row_value(row, "trigger_name") == "my_trigger"

    def test_get_row_value_handles_db2_aliases(self):
        """Test get_row_value() handles DB2-specific aliases."""
        row = {"text": "SELECT 1", "seqname": "my_seq", "readonly": "N"}

        assert get_row_value(row, "view_definition") == "SELECT 1"
        assert get_row_value(row, "sequence_name") == "my_seq"
        assert get_row_value(row, "is_updatable") == "N"


@pytest.mark.unit
class TestParsePgOptions:
    """Test suite for parse_pg_options() function."""

    def test_parse_pg_options_from_list(self):
        """Test parse_pg_options() with list input."""
        options = ["option1=value1", "option2=value2", "option3"]

        result = parse_pg_options(options)

        assert result["option1"] == "value1"
        assert result["option2"] == "value2"
        assert result["option3"] == ""

    def test_parse_pg_options_from_string(self):
        """Test parse_pg_options() with comma-separated string."""
        options = "option1=value1,option2=value2,option3"

        result = parse_pg_options(options)

        assert result["option1"] == "value1"
        assert result["option2"] == "value2"
        assert result["option3"] == ""

    def test_parse_pg_options_handles_none(self):
        """Test parse_pg_options() handles None."""
        result = parse_pg_options(None)

        assert result == {}

    def test_parse_pg_options_handles_bytes(self):
        """Test parse_pg_options() handles bytes."""
        # Bytes are treated as a single item (not a string), so they don't get split by comma
        # The bytes are decoded, then the whole string is treated as one item with "=" split
        options = b"option1=value1,option2=value2"

        result = parse_pg_options(options)

        # Bytes are decoded to string, but treated as single item (not iterable like string)
        # So "option1=value1,option2=value2" becomes one item where first "=" splits key/value
        assert result["option1"] == "value1,option2=value2"

    def test_parse_pg_options_handles_single_value(self):
        """Test parse_pg_options() handles single value."""
        result = parse_pg_options("single_option")

        assert result["single_option"] == ""


@pytest.mark.unit
class TestParseJsonArray:
    """Test suite for parse_json_array() function."""

    def test_parse_json_array_from_string(self):
        """Test parse_json_array() with JSON string."""
        json_str = '["a", "b", "c"]'

        result = parse_json_array(json_str)

        assert result == ["a", "b", "c"]

    def test_parse_json_array_from_list(self):
        """Test parse_json_array() with list."""
        json_list = ["a", "b", "c"]

        result = parse_json_array(json_list)

        assert result == ["a", "b", "c"]

    def test_parse_json_array_handles_none(self):
        """Test parse_json_array() handles None."""
        result = parse_json_array(None)

        assert result == []

    def test_parse_json_array_handles_empty_string(self):
        """Test parse_json_array() handles empty string."""
        result = parse_json_array("")

        assert result == []

    def test_parse_json_array_handles_invalid_json(self):
        """Test parse_json_array() handles invalid JSON."""
        result = parse_json_array("invalid json")

        assert result == []

    def test_parse_json_array_handles_non_list_json(self):
        """Test parse_json_array() handles non-list JSON."""
        result = parse_json_array('{"key": "value"}')

        assert result == []


@pytest.mark.unit
class TestStripLeadingComments:
    """Test suite for strip_leading_comments() function."""

    def test_strip_leading_comments_removes_single_line_comments(self):
        """Test strip_leading_comments() removes single-line comments."""
        sql = "-- This is a comment\nSELECT * FROM users"

        result = strip_leading_comments(sql)

        assert result == "SELECT * FROM users"

    def test_strip_leading_comments_removes_multi_line_comments(self):
        """Test strip_leading_comments() removes multi-line comments."""
        sql = "/* This is a\nmulti-line comment */\nSELECT * FROM users"

        result = strip_leading_comments(sql)

        assert result == "SELECT * FROM users"

    def test_strip_leading_comments_removes_whitespace(self):
        """Test strip_leading_comments() removes leading whitespace."""
        sql = "   \n\t  SELECT * FROM users"

        result = strip_leading_comments(sql)

        assert result == "SELECT * FROM users"

    def test_strip_leading_comments_handles_multiple_comments(self):
        """Test strip_leading_comments() handles multiple comments."""
        sql = "-- Comment 1\n-- Comment 2\n/* Block comment */\nSELECT * FROM users"

        result = strip_leading_comments(sql)

        assert result == "SELECT * FROM users"

    def test_strip_leading_comments_handles_empty_string(self):
        """Test strip_leading_comments() handles empty string."""
        assert strip_leading_comments("") == ""
        assert strip_leading_comments(None) == ""

    def test_strip_leading_comments_handles_only_comments(self):
        """Test strip_leading_comments() handles SQL with only comments."""
        sql = "-- Only comments\n/* No SQL */"

        result = strip_leading_comments(sql)

        assert result == ""

    def test_strip_leading_comments_preserves_sql_after_comments(self):
        """Test strip_leading_comments() preserves SQL after comments."""
        sql = "-- Comment\nSELECT * FROM users WHERE id = 1"

        result = strip_leading_comments(sql)

        assert "SELECT * FROM users" in result


@pytest.mark.unit
class TestToInt:
    """Test suite for to_int() function."""

    def test_to_int_with_integer(self):
        """Test to_int() with integer."""
        assert to_int(123) == 123
        assert to_int(0) == 0
        assert to_int(-456) == -456

    def test_to_int_with_float(self):
        """Test to_int() with float."""
        assert to_int(123.45) == 123
        assert to_int(0.0) == 0

    def test_to_int_with_string(self):
        """Test to_int() with string."""
        assert to_int("123") == 123
        assert to_int("0") == 0
        assert to_int("-456") == -456

    def test_to_int_handles_none(self):
        """Test to_int() handles None."""
        assert to_int(None) is None

    def test_to_int_handles_empty_string(self):
        """Test to_int() handles empty string."""
        assert to_int("") is None
        assert to_int("   ") is None

    def test_to_int_handles_invalid_string(self):
        """Test to_int() handles invalid string."""
        assert to_int("invalid") is None
        assert to_int("abc123") is None

    def test_to_int_handles_boolean(self):
        """Test to_int() handles boolean."""
        assert to_int(True) == 1
        assert to_int(False) == 0
