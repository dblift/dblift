"""Unit tests for core.sql_model.module module."""

import pytest

from core.sql_model.module import Module


@pytest.mark.unit
class TestModule:
    """Test Module class."""

    def test_init_basic(self):
        """Test basic initialization."""
        module = Module("test_module", "CREATE MODULE test_module END MODULE;", dialect="db2")
        assert module.name == "test_module"
        assert module.definition == "CREATE MODULE test_module END MODULE;"
        assert module.schema is None
        assert module.dialect == "db2"

    def test_init_with_schema(self):
        """Test initialization with schema."""
        module = Module(
            "test_module",
            "CREATE MODULE test_module END MODULE;",
            schema="test_schema",
            dialect="db2",
        )
        assert module.name == "test_module"
        assert module.definition == "CREATE MODULE test_module END MODULE;"
        assert module.schema == "test_schema"
        assert module.dialect == "db2"

    def test_init_with_dialect(self):
        """Test initialization with custom dialect."""
        module = Module("test_module", "CREATE MODULE test_module END MODULE;", dialect="db2")
        assert module.dialect == "db2"

    def test_create_statement_with_definition(self):
        """Test create_statement with definition."""
        definition = "CREATE MODULE test_module\n  PROCEDURE test_proc()\nEND MODULE;"
        module = Module("test_module", definition)
        result = module.create_statement
        assert result == definition

    def test_create_statement_without_definition(self):
        """Test create_statement without definition (minimal template)."""
        module = Module("test_module", "")
        result = module.create_statement
        assert "CREATE OR REPLACE MODULE" in result
        assert "test_module" in result
        assert "END MODULE" in result

    def test_create_statement_without_definition_with_schema(self):
        """Test create_statement without definition but with schema."""
        module = Module("test_module", "", schema="test_schema")
        result = module.create_statement
        assert "CREATE OR REPLACE MODULE" in result
        assert "test_schema" in result
        assert "test_module" in result
        assert "END MODULE" in result

    def test_drop_statement(self):
        """Test drop statement generation."""
        module = Module("test_module", "CREATE MODULE test_module END MODULE;")
        result = module.drop_statement
        assert result == 'DROP MODULE "test_module";'

    def test_drop_statement_with_schema(self):
        """Test drop statement with schema."""
        module = Module(
            "test_module", "CREATE MODULE test_module END MODULE;", schema="test_schema"
        )
        result = module.drop_statement
        assert "DROP MODULE" in result
        assert '"test_schema"."test_module"' in result

    def test_str_representation_basic(self):
        """Test string representation without schema."""
        module = Module("test_module", "line1\nline2\nline3")
        result = str(module)
        assert "MODULE test_module" in result
        assert "3 lines" in result

    def test_str_representation_with_schema(self):
        """Test string representation with schema."""
        module = Module("test_module", "line1\nline2", schema="test_schema")
        result = str(module)
        assert "MODULE test_schema.test_module" in result
        assert "2 lines" in result

    def test_str_representation_empty_definition(self):
        """Test string representation with empty definition."""
        module = Module("test_module", "")
        result = str(module)
        assert "MODULE test_module" in result
        assert "0 lines" in result

    def test_eq_same_module(self):
        """Test equality with same module."""
        definition = "CREATE MODULE test_module END MODULE;"
        module1 = Module("test_module", definition, schema="test_schema")
        module2 = Module("test_module", definition, schema="test_schema")
        assert module1 == module2

    def test_eq_different_type(self):
        """Test equality with different type."""
        module = Module("test_module", "definition")
        assert module != "not_a_module"

    def test_eq_different_definition(self):
        """Test equality with different definition."""
        module1 = Module("test_module", "definition1")
        module2 = Module("test_module", "definition2")
        assert module1 != module2

    def test_eq_different_name(self):
        """Test equality with different name."""
        definition = "CREATE MODULE test_module END MODULE;"
        module1 = Module("module1", definition)
        module2 = Module("module2", definition)
        assert module1 != module2

    def test_hash(self):
        """Test hash generation."""
        definition = "CREATE MODULE test_module END MODULE;"
        module1 = Module("test_module", definition, schema="test_schema")
        module2 = Module("test_module", definition, schema="test_schema")
        assert hash(module1) == hash(module2)

    def test_hash_different_name(self):
        """Test hash differs with different name."""
        definition = "CREATE MODULE test_module END MODULE;"
        module1 = Module("module1", definition)
        module2 = Module("module2", definition)
        assert hash(module1) != hash(module2)

    def test_hash_different_schema(self):
        """Test hash differs with different schema."""
        definition = "CREATE MODULE test_module END MODULE;"
        module1 = Module("test_module", definition, schema="schema1")
        module2 = Module("test_module", definition, schema="schema2")
        assert hash(module1) != hash(module2)

    def test_to_dict(self):
        """Test to_dict serializes all fields."""
        definition = "CREATE MODULE m END MODULE;"
        module = Module("m", definition, schema="myschema", dialect="db2")
        d = module.to_dict()
        assert d["name"] == "m"
        assert d["definition"] == definition
        assert d["schema"] == "myschema"
        assert d["dialect"] == "db2"

    def test_from_dict_round_trip(self):
        """Test from_dict round-trip."""
        definition = "CREATE MODULE m END MODULE;"
        module = Module("m", definition, schema="myschema")
        assert Module.from_dict(module.to_dict()) == module

    def test_from_dict_minimal(self):
        """Test from_dict with minimal fields uses defaults."""
        d = {"name": "m", "definition": ""}
        module = Module.from_dict(d)
        assert module.name == "m"
        assert module.schema is None
