"""Unit tests for core.sql_model.user_defined_type module."""

from unittest.mock import Mock, patch

import pytest

from core.sql_model.user_defined_type import UserDefinedType


@pytest.mark.unit
class TestUserDefinedType:
    """Test UserDefinedType class."""

    def test_init_basic(self):
        """Test basic initialization."""
        udt = UserDefinedType("test_type", "COMPOSITE")
        assert udt.name == "test_type"
        assert udt.type_category == "COMPOSITE"
        assert udt.data_type is None
        assert udt.definition is None
        assert udt.attributes == []
        assert udt.enum_values == []
        assert udt.base_type is None
        assert udt.comment is None
        assert udt.schema is None

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters."""
        attributes = [{"name": "attr1", "type": "INTEGER"}]
        enum_values = ["value1", "value2"]
        udt = UserDefinedType(
            name="test_type",
            type_category="COMPOSITE",
            schema="public",
            data_type="STRUCTURED",
            definition="CREATE TYPE test_type AS ...",
            attributes=attributes,
            enum_values=enum_values,
            base_type="INTEGER",
            comment="Test type",
            dialect="postgresql",
        )
        assert udt.name == "test_type"
        assert udt.type_category == "COMPOSITE"
        assert udt.schema == "public"
        assert udt.data_type == "STRUCTURED"
        assert udt.definition == "CREATE TYPE test_type AS ..."
        assert udt.attributes == attributes
        assert udt.enum_values == enum_values
        assert udt.base_type == "INTEGER"
        assert udt.comment == "Test type"
        assert udt.dialect == "postgresql"

    def test_init_type_category_uppercase(self):
        """Test that type_category is converted to uppercase."""
        udt = UserDefinedType("test_type", "composite")
        assert udt.type_category == "COMPOSITE"

    def test_init_attributes_default(self):
        """Test that attributes defaults to empty list."""
        udt = UserDefinedType("test_type", "COMPOSITE", attributes=None)
        assert udt.attributes == []

    def test_init_enum_values_default(self):
        """Test that enum_values defaults to empty list."""
        udt = UserDefinedType("test_type", "ENUM", enum_values=None)
        assert udt.enum_values == []

    def test_is_composite_true(self):
        """Test is_composite property returns True for composite types."""
        assert UserDefinedType("test", "COMPOSITE").is_composite is True
        assert UserDefinedType("test", "C").is_composite is True
        assert UserDefinedType("test", "STRUCT").is_composite is True
        assert UserDefinedType("test", "OBJECT").is_composite is True

    def test_is_composite_false(self):
        """Test is_composite property returns False for non-composite types."""
        assert UserDefinedType("test", "ENUM").is_composite is False
        assert UserDefinedType("test", "DOMAIN").is_composite is False
        assert UserDefinedType("test", "DISTINCT").is_composite is False

    def test_is_enum_true(self):
        """Test is_enum property returns True for enum types."""
        assert UserDefinedType("test", "ENUM").is_enum is True
        assert UserDefinedType("test", "E").is_enum is True

    def test_is_enum_false(self):
        """Test is_enum property returns False for non-enum types."""
        assert UserDefinedType("test", "COMPOSITE").is_enum is False
        assert UserDefinedType("test", "DOMAIN").is_enum is False

    def test_is_domain_true(self):
        """Test is_domain property returns True for domain types."""
        assert UserDefinedType("test", "DOMAIN").is_domain is True
        assert UserDefinedType("test", "D").is_domain is True

    def test_is_domain_false(self):
        """Test is_domain property returns False for non-domain types."""
        assert UserDefinedType("test", "COMPOSITE").is_domain is False
        assert UserDefinedType("test", "ENUM").is_domain is False

    def test_is_distinct_true(self):
        """Test is_distinct property returns True for distinct types."""
        assert UserDefinedType("test", "DISTINCT").is_distinct is True

    def test_is_distinct_false(self):
        """Test is_distinct property returns False for non-distinct types."""
        assert UserDefinedType("test", "COMPOSITE").is_distinct is False
        assert UserDefinedType("test", "ENUM").is_distinct is False

    def test_create_statement_with_generator(self):
        """Test create_statement using generator."""
        udt = UserDefinedType("test_type", "COMPOSITE", schema="public")
        mock_generator = Mock()
        mock_generator.generate_create_statement = Mock(return_value="CREATE TYPE test_type;")

        with patch(
            "core.sql_generator.generator_factory.SqlGeneratorFactory.create",
            return_value=mock_generator,
        ):
            result = udt.create_statement
            assert result == "CREATE TYPE test_type;"
            mock_generator.generate_create_statement.assert_called_once_with(udt)

    def test_create_statement_fallback_no_generator_method(self):
        """Test create_statement fallback when generator lacks method."""
        udt = UserDefinedType(
            "test_type", "COMPOSITE", attributes=[{"name": "attr1", "type": "INTEGER"}]
        )
        mock_generator = Mock()
        del mock_generator.generate_create_statement  # Simulate missing method

        with patch(
            "core.sql_generator.generator_factory.SqlGeneratorFactory.create",
            return_value=mock_generator,
        ):
            result = udt.create_statement
            assert "CREATE TYPE" in result

    def test_create_statement_fallback_exception(self):
        """Test create_statement fallback on exception."""
        udt = UserDefinedType("test_type", "ENUM", enum_values=["val1", "val2"])

        with patch(
            "core.sql_generator.generator_factory.SqlGeneratorFactory.create",
            side_effect=ValueError("Error"),
        ):
            result = udt.create_statement
            assert "CREATE TYPE" in result

    def test_generate_basic_create_statement_composite(self):
        """Test basic create statement for composite type."""
        udt = UserDefinedType(
            "test_type",
            "COMPOSITE",
            attributes=[
                {"name": "attr1", "type": "INTEGER"},
                {"name": "attr2", "type": "VARCHAR(50)"},
            ],
            schema="public",
        )
        result = udt._generate_basic_create_statement()
        assert "CREATE TYPE" in result
        assert "AS" in result
        assert "attr1" in result
        assert "attr2" in result
        assert "INTEGER" in result

    def test_generate_basic_create_statement_composite_oracle_object(self):
        """Test basic create statement for Oracle OBJECT type."""
        udt = UserDefinedType(
            "test_type",
            "OBJECT",
            attributes=[{"name": "attr1", "type": "INTEGER"}],
            dialect="oracle",
        )
        result = udt._generate_basic_create_statement()
        assert "CREATE TYPE" in result
        assert "OBJECT" in result
        assert "AS" in result

    def test_generate_basic_create_statement_enum(self):
        """Test basic create statement for enum type."""
        udt = UserDefinedType(
            "test_type", "ENUM", enum_values=["val1", "val2", "val3"], schema="public"
        )
        result = udt._generate_basic_create_statement()
        assert "CREATE TYPE" in result
        assert "AS ENUM" in result
        assert "val1" in result
        assert "val2" in result
        assert "val3" in result

    def test_generate_basic_create_statement_domain(self):
        """Test basic create statement for domain type."""
        udt = UserDefinedType(
            "test_type",
            "DOMAIN",
            base_type="INTEGER",
            definition="CHECK (value > 0)",
            schema="public",
        )
        result = udt._generate_basic_create_statement()
        assert "CREATE DOMAIN" in result
        assert "AS INTEGER" in result
        assert "CHECK" in result

    def test_generate_basic_create_statement_distinct_sqlserver(self):
        """Test basic create statement for distinct type (SQL Server)."""
        udt = UserDefinedType("test_type", "DISTINCT", base_type="VARCHAR(50)", dialect="sqlserver")
        result = udt._generate_basic_create_statement()
        assert "CREATE TYPE" in result
        assert "FROM VARCHAR(50)" in result

    def test_generate_basic_create_statement_distinct_other(self):
        """Test basic create statement for distinct type (non-SQL Server)."""
        udt = UserDefinedType("test_type", "DISTINCT", base_type="VARCHAR(50)", dialect="db2")
        result = udt._generate_basic_create_statement()
        assert "CREATE DISTINCT TYPE" in result
        assert "AS VARCHAR(50)" in result

    def test_generate_basic_create_statement_generic_with_definition(self):
        """Test basic create statement with generic definition."""
        udt = UserDefinedType(
            "test_type", "OTHER", definition="AS TABLE OF INTEGER", schema="public"
        )
        result = udt._generate_basic_create_statement()
        assert "CREATE TYPE" in result
        assert "AS TABLE OF INTEGER" in result

    def test_generate_basic_create_statement_generic_minimal(self):
        """Test basic create statement minimal fallback."""
        udt = UserDefinedType("test_type", "OTHER")
        result = udt._generate_basic_create_statement()
        assert "CREATE TYPE" in result
        assert "test_type" in result

    def test_drop_statement_domain(self):
        """Test drop statement for domain type."""
        udt = UserDefinedType("test_type", "DOMAIN", schema="public")
        result = udt.drop_statement
        assert "DROP DOMAIN" in result
        assert "test_type" in result

    def test_drop_statement_non_domain(self):
        """Test drop statement for non-domain type."""
        udt = UserDefinedType("test_type", "COMPOSITE", schema="public")
        result = udt.drop_statement
        assert "DROP TYPE" in result
        assert "test_type" in result

    def test_drop_statement_with_schema(self):
        """Test drop statement with schema."""
        udt = UserDefinedType("test_type", "COMPOSITE", schema="public")
        result = udt.drop_statement
        assert "public" in result or '"public"' in result

    def test_str_representation_enum(self):
        """Test string representation for enum type."""
        udt = UserDefinedType("test_type", "ENUM", enum_values=["val1", "val2", "val3"])
        result = str(udt)
        assert "TYPE test_type" in result
        assert "ENUM" in result
        assert "3 values" in result

    def test_str_representation_composite(self):
        """Test string representation for composite type."""
        udt = UserDefinedType(
            "test_type", "COMPOSITE", attributes=[{"name": "attr1"}, {"name": "attr2"}]
        )
        result = str(udt)
        assert "TYPE test_type" in result
        assert "COMPOSITE" in result
        assert "2 attributes" in result

    def test_str_representation_with_base_type(self):
        """Test string representation with base type."""
        udt = UserDefinedType("test_type", "DISTINCT", base_type="INTEGER")
        result = str(udt)
        assert "TYPE test_type" in result
        assert "base: INTEGER" in result

    def test_str_representation_basic(self):
        """Test string representation basic."""
        udt = UserDefinedType("test_type", "OTHER")
        result = str(udt)
        assert "TYPE test_type" in result
        assert "OTHER" in result

    def test_eq_same_type(self):
        """Test equality with same type."""
        udt1 = UserDefinedType("test_type", "COMPOSITE", base_type="INTEGER")
        udt2 = UserDefinedType("test_type", "COMPOSITE", base_type="INTEGER")
        assert udt1 == udt2

    def test_eq_different_type(self):
        """Test equality with different type."""
        udt = UserDefinedType("test_type", "COMPOSITE")
        assert udt != "not_a_type"

    def test_eq_different_type_category(self):
        """Test equality with different type category."""
        udt1 = UserDefinedType("test_type", "COMPOSITE")
        udt2 = UserDefinedType("test_type", "ENUM")
        assert udt1 != udt2

    def test_eq_different_base_type(self):
        """Test equality with different base type."""
        udt1 = UserDefinedType("test_type", "DISTINCT", base_type="INTEGER")
        udt2 = UserDefinedType("test_type", "DISTINCT", base_type="VARCHAR")
        assert udt1 != udt2

    def test_eq_case_insensitive_base_type(self):
        """Test equality is case-insensitive for base_type."""
        udt1 = UserDefinedType("test_type", "DISTINCT", base_type="INTEGER")
        udt2 = UserDefinedType("test_type", "DISTINCT", base_type="integer")
        assert udt1 == udt2

    def test_eq_none_base_type(self):
        """Test equality with None base_type."""
        udt1 = UserDefinedType("test_type", "COMPOSITE")
        udt2 = UserDefinedType("test_type", "COMPOSITE")
        assert udt1 == udt2

    def test_hash(self):
        """Test hash generation."""
        udt1 = UserDefinedType("test_type", "COMPOSITE", schema="public")
        udt2 = UserDefinedType("test_type", "COMPOSITE", schema="public")
        assert hash(udt1) == hash(udt2)

    def test_hash_different_name(self):
        """Test hash differs with different name."""
        udt1 = UserDefinedType("type1", "COMPOSITE")
        udt2 = UserDefinedType("type2", "COMPOSITE")
        assert hash(udt1) != hash(udt2)

    def test_hash_different_type_category(self):
        """Test hash differs with different type category."""
        udt1 = UserDefinedType("test_type", "COMPOSITE")
        udt2 = UserDefinedType("test_type", "ENUM")
        assert hash(udt1) != hash(udt2)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        attributes = [{"name": "attr1", "type": "INTEGER"}]
        enum_values = ["val1", "val2"]
        udt = UserDefinedType(
            "test_type",
            "COMPOSITE",
            schema="public",
            data_type="STRUCTURED",
            definition="CREATE TYPE ...",
            attributes=attributes,
            enum_values=enum_values,
            base_type="INTEGER",
            comment="Test type",
            dialect="postgresql",
        )
        result = udt.to_dict()
        assert result == {
            "name": "test_type",
            "schema": "public",
            "dialect": "postgresql",
            "type_category": "COMPOSITE",
            "data_type": "STRUCTURED",
            "definition": "CREATE TYPE ...",
            "attributes": attributes,
            "enum_values": enum_values,
            "base_type": "INTEGER",
            "comment": "Test type",
        }

    def test_to_dict_minimal(self):
        """Test serialization with minimal type."""
        udt = UserDefinedType("test_type", "COMPOSITE")
        result = udt.to_dict()
        assert result["name"] == "test_type"
        assert result["type_category"] == "COMPOSITE"
        assert result["data_type"] is None
        assert result["attributes"] == []
        assert result["enum_values"] == []

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "name": "test_type",
            "type_category": "COMPOSITE",
            "schema": "public",
            "data_type": "STRUCTURED",
            "definition": "CREATE TYPE ...",
            "attributes": [{"name": "attr1"}],
            "enum_values": ["val1"],
            "base_type": "INTEGER",
            "comment": "Test type",
            "dialect": "postgresql",
        }
        udt = UserDefinedType.from_dict(data)
        assert udt.name == "test_type"
        assert udt.type_category == "COMPOSITE"
        assert udt.schema == "public"
        assert udt.data_type == "STRUCTURED"
        assert udt.definition == "CREATE TYPE ..."
        assert len(udt.attributes) == 1
        assert len(udt.enum_values) == 1
        assert udt.base_type == "INTEGER"
        assert udt.comment == "Test type"
        assert udt.dialect == "postgresql"

    def test_from_dict_minimal(self):
        """Test deserialization with minimal data."""
        data = {"name": "test_type", "type_category": "COMPOSITE"}
        udt = UserDefinedType.from_dict(data)
        assert udt.name == "test_type"
        assert udt.type_category == "COMPOSITE"
        assert udt.schema is None
        assert udt.attributes == []
        assert udt.enum_values == []

    def test_from_dict_empty_name(self):
        """Test deserialization with empty name."""
        data = {}
        udt = UserDefinedType.from_dict(data)
        assert udt.name == ""
        assert udt.type_category == ""
