"""Unit tests for core.migration.placeholders.placeholder_service module."""

from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService


@pytest.mark.unit
class TestPlaceholderService:
    """Test PlaceholderService class."""

    def test_initialization_empty(self):
        """Test PlaceholderService initialization with no placeholders."""
        service = PlaceholderService()

        assert service.placeholders == {}
        assert isinstance(service.log, NullLog)

    def test_initialization_with_placeholders(self):
        """Test PlaceholderService initialization with placeholders."""
        placeholders = {"db_name": "mydb", "schema": "public"}
        service = PlaceholderService(placeholders=placeholders)

        assert service.placeholders == placeholders

    def test_initialization_with_logger(self):
        """Test PlaceholderService initialization with logger."""
        logger = MagicMock()
        service = PlaceholderService(logger=logger)

        assert service.log == logger

    def test_add_placeholders(self):
        """Test adding new placeholders."""
        service = PlaceholderService(placeholders={"db_name": "mydb"})
        service.add_placeholders({"schema": "public", "table": "users"})

        assert service.placeholders["db_name"] == "mydb"
        assert service.placeholders["schema"] == "public"
        assert service.placeholders["table"] == "users"

    def test_add_placeholders_overwrites_existing(self):
        """Test that add_placeholders overwrites existing values."""
        service = PlaceholderService(placeholders={"db_name": "olddb"})
        service.add_placeholders({"db_name": "newdb"})

        assert service.placeholders["db_name"] == "newdb"

    def test_add_placeholders_empty_dict(self):
        """Test adding empty placeholders dict does nothing."""
        service = PlaceholderService(placeholders={"db_name": "mydb"})
        service.add_placeholders({})

        assert len(service.placeholders) == 1
        assert service.placeholders["db_name"] == "mydb"

    def test_add_placeholders_none(self):
        """Test adding None placeholders does nothing."""
        service = PlaceholderService(placeholders={"db_name": "mydb"})
        service.add_placeholders(None)

        assert len(service.placeholders) == 1

    def test_replace_placeholders_basic(self):
        """Test basic placeholder replacement."""
        service = PlaceholderService(placeholders={"db_name": "mydb", "schema": "public"})
        sql = "SELECT * FROM ${schema}.users WHERE db = '${db_name}'"

        result = service.replace_placeholders(sql)

        assert "${schema}" not in result
        assert "${db_name}" not in result
        assert "public" in result
        assert "mydb" in result

    def test_replace_placeholders_with_default(self):
        """Test placeholder replacement with default value."""
        service = PlaceholderService(placeholders={"db_name": "mydb"})
        sql = "SELECT * FROM ${schema:public}.users"

        result = service.replace_placeholders(sql)

        assert "${schema" not in result
        assert "public" in result

    def test_replace_placeholders_default_when_not_found(self):
        """Test that default value is used when placeholder not found."""
        service = PlaceholderService(placeholders={})
        sql = "SELECT * FROM ${schema:public}.users"

        result = service.replace_placeholders(sql)

        assert "${schema" not in result
        assert "public" in result

    def test_replace_placeholders_no_default_no_value(self):
        """Test placeholder without default and no value leaves unchanged."""
        logger = MagicMock()
        service = PlaceholderService(placeholders={}, logger=logger)
        sql = "SELECT * FROM ${schema}.users"

        result = service.replace_placeholders(sql)

        assert "${schema}" in result
        logger.warning.assert_called_once()
        assert "schema" in str(logger.warning.call_args)

    def test_replace_placeholders_no_default_no_value_no_logger(self):
        """Test placeholder without default and no value, no logger."""
        service = PlaceholderService(placeholders={})
        sql = "SELECT * FROM ${schema}.users"

        result = service.replace_placeholders(sql)

        assert "${schema}" in result

    def test_replace_placeholders_multiple_placeholders(self):
        """Test replacing multiple placeholders."""
        service = PlaceholderService(
            placeholders={"db_name": "mydb", "schema": "public", "table": "users"}
        )
        sql = "SELECT * FROM ${schema}.${table} WHERE db = '${db_name}'"

        result = service.replace_placeholders(sql)

        assert "${" not in result
        assert "public" in result
        assert "users" in result
        assert "mydb" in result

    def test_replace_placeholders_no_placeholders_in_text(self):
        """Test text with no placeholders."""
        service = PlaceholderService(placeholders={"db_name": "mydb"})
        sql = "SELECT * FROM users"

        result = service.replace_placeholders(sql)

        assert result == sql

    def test_replace_placeholders_empty_text(self):
        """Test empty text."""
        service = PlaceholderService(placeholders={"db_name": "mydb"})
        result = service.replace_placeholders("")

        assert result == ""

    def test_replace_placeholders_none_text(self):
        """Test None text."""
        service = PlaceholderService(placeholders={"db_name": "mydb"})
        result = service.replace_placeholders(None)

        assert result is None or result == ""

    def test_replace_placeholders_no_placeholders_dict(self):
        """Test replacement when no placeholders dict."""
        service = PlaceholderService(placeholders={})
        sql = "SELECT * FROM ${schema}.users"

        result = service.replace_placeholders(sql)

        assert "${schema}" in result

    def test_replace_placeholders_complex_default(self):
        """Test placeholder with complex default value."""
        service = PlaceholderService(placeholders={})
        sql = "SELECT * FROM ${schema:public}.${table:users}"

        result = service.replace_placeholders(sql)

        assert "public" in result
        assert "users" in result

    def test_replace_placeholders_colon_in_default(self):
        """Test default value containing colon."""
        service = PlaceholderService(placeholders={})
        sql = "SELECT * FROM ${url:postgresql+psycopg://localhost/mydb}"

        result = service.replace_placeholders(sql)

        # Should use everything after first colon as default
        assert "postgresql+psycopg://localhost/mydb" in result

    def test_replace_placeholders_nested_braces(self):
        """Test placeholder with nested braces (edge case)."""
        service = PlaceholderService(placeholders={"name": "test"})
        sql = "SELECT ${name} FROM ${table:users}"

        result = service.replace_placeholders(sql)

        assert "${" not in result or result.count("${") == 0
        assert "test" in result

    def test_replace_placeholders_value_overrides_default(self):
        """Test that placeholder value overrides default."""
        service = PlaceholderService(placeholders={"schema": "custom"})
        sql = "SELECT * FROM ${schema:public}.users"

        result = service.replace_placeholders(sql)

        assert "custom" in result
        assert "public" not in result

    def test_replace_placeholders_non_string_values(self):
        """Test placeholder replacement with non-string values."""
        service = PlaceholderService(placeholders={"count": 100, "active": True})
        sql = "SELECT * FROM users WHERE count = ${count} AND active = ${active}"

        result = service.replace_placeholders(sql)

        assert "100" in result
        assert "True" in result

    def test_replace_placeholders_trims_name_whitespace(self):
        """Spaces inside ${...} around the name match config keys (e.g. ${table_schema })."""
        service = PlaceholderService(placeholders={"table_schema": "app_data"})
        sql = "CREATE TABLE ${table_schema }.users(id INT);"

        result = service.replace_placeholders(sql)

        assert "${" not in result
        assert "app_data.users" in result

    def test_replace_placeholders_trims_default_whitespace(self):
        """Spaces around name:default are ignored."""
        service = PlaceholderService(placeholders={})
        sql = "SELECT * FROM ${ schema : public }.t"

        result = service.replace_placeholders(sql)

        assert "${" not in result
        assert "public" in result
