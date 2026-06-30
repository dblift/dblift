"""Unit tests for core.sql_model.foreign_data_wrapper module."""

from unittest.mock import Mock, patch

import pytest

from core.sql_model.foreign_data_wrapper import ForeignDataWrapper


@pytest.mark.unit
class TestForeignDataWrapper:
    """Test ForeignDataWrapper class."""

    def test_init_basic(self):
        """Test basic initialization."""
        fdw = ForeignDataWrapper("postgres_fdw", dialect="postgresql")
        assert fdw.name == "postgres_fdw"
        assert fdw.handler is None
        assert fdw.validator is None
        assert fdw.options == {}
        assert fdw.dialect == "postgresql"

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters."""
        options = {"option1": "value1", "option2": "value2"}
        fdw = ForeignDataWrapper(
            name="oracle_fdw",
            handler="oracle_fdw_handler",
            validator="oracle_fdw_validator",
            options=options,
            schema="public",
            dialect="postgresql",
        )
        assert fdw.name == "oracle_fdw"
        assert fdw.handler == "oracle_fdw_handler"
        assert fdw.validator == "oracle_fdw_validator"
        assert fdw.options == options
        assert fdw.schema == "public"
        assert fdw.dialect == "postgresql"

    def test_init_options_copy(self):
        """Test that options dictionary is copied."""
        original_options = {"key": "value"}
        fdw = ForeignDataWrapper("test_fdw", options=original_options)
        fdw.options["new_key"] = "new_value"
        assert "new_key" not in original_options

    def test_drop_statement(self):
        """Test drop statement generation."""
        fdw = ForeignDataWrapper("test_fdw", dialect="postgresql")
        result = fdw.drop_statement
        assert result == 'DROP FOREIGN DATA WRAPPER IF EXISTS "test_fdw" CASCADE;'

    def test_str_representation_basic(self):
        """Test string representation without handler."""
        fdw = ForeignDataWrapper("test_fdw")
        result = str(fdw)
        assert "FOREIGN DATA WRAPPER test_fdw" in result

    def test_str_representation_with_handler(self):
        """Test string representation with handler."""
        fdw = ForeignDataWrapper("test_fdw", handler="my_handler")
        result = str(fdw)
        assert "FOREIGN DATA WRAPPER test_fdw" in result
        assert "(handler: my_handler)" in result

    def test_eq_same_fdw(self):
        """Test equality with same FDW."""
        fdw1 = ForeignDataWrapper(
            "test_fdw", handler="handler", validator="validator", options={"k": "v"}
        )
        fdw2 = ForeignDataWrapper(
            "test_fdw", handler="handler", validator="validator", options={"k": "v"}
        )
        assert fdw1 == fdw2

    def test_eq_different_type(self):
        """Test equality with different type."""
        fdw = ForeignDataWrapper("test_fdw")
        assert fdw != "not_an_fdw"

    def test_eq_different_handler(self):
        """Test equality with different handler."""
        fdw1 = ForeignDataWrapper("test_fdw", handler="handler1")
        fdw2 = ForeignDataWrapper("test_fdw", handler="handler2")
        assert fdw1 != fdw2

    def test_eq_different_validator(self):
        """Test equality with different validator."""
        fdw1 = ForeignDataWrapper("test_fdw", validator="validator1")
        fdw2 = ForeignDataWrapper("test_fdw", validator="validator2")
        assert fdw1 != fdw2

    def test_eq_different_options(self):
        """Test equality with different options."""
        fdw1 = ForeignDataWrapper("test_fdw", options={"k1": "v1"})
        fdw2 = ForeignDataWrapper("test_fdw", options={"k2": "v2"})
        assert fdw1 != fdw2

    def test_eq_case_insensitive_handler(self):
        """Test equality is case-insensitive for handler."""
        fdw1 = ForeignDataWrapper("test_fdw", handler="Handler")
        fdw2 = ForeignDataWrapper("test_fdw", handler="handler")
        assert fdw1 == fdw2

    def test_eq_case_insensitive_validator(self):
        """Test equality is case-insensitive for validator."""
        fdw1 = ForeignDataWrapper("test_fdw", validator="Validator")
        fdw2 = ForeignDataWrapper("test_fdw", validator="validator")
        assert fdw1 == fdw2

    def test_eq_none_handler(self):
        """Test equality with None handlers."""
        fdw1 = ForeignDataWrapper("test_fdw")
        fdw2 = ForeignDataWrapper("test_fdw")
        assert fdw1 == fdw2

    def test_hash(self):
        """Test hash generation."""
        fdw1 = ForeignDataWrapper("test_fdw", handler="handler", schema="public")
        fdw2 = ForeignDataWrapper("test_fdw", handler="handler", schema="public")
        assert hash(fdw1) == hash(fdw2)

    def test_hash_different_handler(self):
        """Test hash differs with different handler."""
        fdw1 = ForeignDataWrapper("test_fdw", handler="handler1")
        fdw2 = ForeignDataWrapper("test_fdw", handler="handler2")
        assert hash(fdw1) != hash(fdw2)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        fdw = ForeignDataWrapper(
            "test_fdw",
            handler="handler_func",
            validator="validator_func",
            options={"key": "value"},
            schema="public",
            dialect="postgresql",
        )
        result = fdw.to_dict()
        assert result == {
            "name": "test_fdw",
            "schema": "public",
            "dialect": "postgresql",
            "handler": "handler_func",
            "validator": "validator_func",
            "options": {"key": "value"},
        }

    def test_to_dict_minimal(self):
        """Test serialization with minimal FDW."""
        fdw = ForeignDataWrapper("test_fdw")
        result = fdw.to_dict()
        assert result["name"] == "test_fdw"
        assert result["handler"] is None
        assert result["validator"] is None
        assert result["options"] == {}

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "name": "test_fdw",
            "handler": "handler_func",
            "validator": "validator_func",
            "options": {"key": "value"},
            "schema": "public",
            "dialect": "postgresql",
        }
        fdw = ForeignDataWrapper.from_dict(data)
        assert fdw.name == "test_fdw"
        assert fdw.handler == "handler_func"
        assert fdw.validator == "validator_func"
        assert fdw.options == {"key": "value"}
        assert fdw.schema == "public"
        assert fdw.dialect == "postgresql"

    def test_from_dict_minimal(self):
        """Test deserialization with minimal data."""
        data = {"name": "test_fdw"}
        fdw = ForeignDataWrapper.from_dict(data)
        assert fdw.name == "test_fdw"
        assert fdw.handler is None
        assert fdw.validator is None
        assert fdw.options == {}

    def test_from_dict_empty_name(self):
        """Test deserialization with empty name."""
        data = {}
        fdw = ForeignDataWrapper.from_dict(data)
        assert fdw.name == ""
