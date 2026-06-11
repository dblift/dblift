"""Unit tests for core.sql_model.extension module."""

import pytest

from core.sql_model.extension import Extension


@pytest.mark.unit
class TestExtension:
    """Test Extension class."""

    def test_init_basic(self):
        """Test basic initialization."""
        ext = Extension("postgis")
        assert ext.name == "postgis"
        assert ext.version is None
        assert ext.schema is None
        assert ext.description is None
        assert ext.relocatable is False
        assert ext.dialect == "postgresql"

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters."""
        ext = Extension(
            name="postgis",
            version="3.0.0",
            schema="public",
            description="PostGIS spatial and geographic objects",
            relocatable=True,
            dialect="postgresql",
        )
        assert ext.name == "postgis"
        assert ext.version == "3.0.0"
        assert ext.schema == "public"
        assert ext.description == "PostGIS spatial and geographic objects"
        assert ext.relocatable is True
        assert ext.dialect == "postgresql"

    def test_init_relocatable_false(self):
        """Test initialization with relocatable=False."""
        ext = Extension("postgis", relocatable=False)
        assert ext.relocatable is False

    def test_generate_basic_create_statement_minimal(self):
        """Test basic create statement generation with minimal extension."""
        ext = Extension("postgis")
        result = ext._generate_basic_create_statement()
        assert "CREATE EXTENSION IF NOT EXISTS" in result
        assert "postgis" in result

    def test_generate_basic_create_statement_with_schema(self):
        """Test basic create statement with schema."""
        ext = Extension("postgis", schema="public")
        result = ext._generate_basic_create_statement()
        assert "CREATE EXTENSION IF NOT EXISTS" in result
        assert "SCHEMA" in result
        assert "public" in result

    def test_generate_basic_create_statement_with_version(self):
        """Test basic create statement with version."""
        ext = Extension("postgis", version="3.0.0")
        result = ext._generate_basic_create_statement()
        assert "CREATE EXTENSION IF NOT EXISTS" in result
        assert "VERSION" in result
        assert "3.0.0" in result

    def test_generate_basic_create_statement_complete(self):
        """Test basic create statement with all components."""
        ext = Extension("postgis", version="3.0.0", schema="public")
        result = ext._generate_basic_create_statement()
        assert "CREATE EXTENSION IF NOT EXISTS" in result
        assert "SCHEMA" in result
        assert "VERSION" in result
        assert "public" in result
        assert "3.0.0" in result

    def test_drop_statement(self):
        """Test drop statement generation."""
        ext = Extension("postgis")
        result = ext.drop_statement
        assert result == 'DROP EXTENSION IF EXISTS "postgis"'

    def test_str_representation_basic(self):
        """Test string representation without version or description."""
        ext = Extension("postgis")
        result = str(ext)
        assert "EXTENSION postgis" in result

    def test_str_representation_with_version(self):
        """Test string representation with version."""
        ext = Extension("postgis", version="3.0.0")
        result = str(ext)
        assert "EXTENSION postgis" in result
        assert "(v3.0.0)" in result

    def test_str_representation_with_description(self):
        """Test string representation with description."""
        ext = Extension("postgis", description="PostGIS spatial extension")
        result = str(ext)
        assert "EXTENSION postgis" in result
        assert "- PostGIS spatial extension" in result

    def test_str_representation_complete(self):
        """Test string representation with version and description."""
        ext = Extension("postgis", version="3.0.0", description="PostGIS spatial extension")
        result = str(ext)
        assert "EXTENSION postgis" in result
        assert "(v3.0.0)" in result
        assert "- PostGIS spatial extension" in result

    def test_eq_same_extension(self):
        """Test equality with same extension."""
        ext1 = Extension("postgis", version="3.0.0", schema="public")
        ext2 = Extension("postgis", version="3.0.0", schema="public")
        assert ext1 == ext2

    def test_eq_different_type(self):
        """Test equality with different type."""
        ext = Extension("postgis")
        assert ext != "not_an_extension"

    def test_eq_different_version(self):
        """Test equality with different version."""
        ext1 = Extension("postgis", version="3.0.0")
        ext2 = Extension("postgis", version="2.5.0")
        assert ext1 != ext2

    def test_eq_none_version(self):
        """Test equality with None version."""
        ext1 = Extension("postgis")
        ext2 = Extension("postgis")
        assert ext1 == ext2

    def test_hash(self):
        """Test hash generation."""
        ext1 = Extension("postgis", version="3.0.0", schema="public")
        ext2 = Extension("postgis", version="3.0.0", schema="public")
        assert hash(ext1) == hash(ext2)

    def test_hash_different_version(self):
        """Test hash differs with different version."""
        ext1 = Extension("postgis", version="3.0.0")
        ext2 = Extension("postgis", version="2.5.0")
        assert hash(ext1) != hash(ext2)

    def test_hash_different_schema(self):
        """Test hash differs with different schema."""
        ext1 = Extension("postgis", schema="public")
        ext2 = Extension("postgis", schema="extensions")
        assert hash(ext1) != hash(ext2)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        ext = Extension(
            "postgis",
            version="3.0.0",
            schema="public",
            description="PostGIS spatial extension",
            relocatable=True,
            dialect="postgresql",
        )
        result = ext.to_dict()
        assert result == {
            "name": "postgis",
            "schema": "public",
            "dialect": "postgresql",
            "version": "3.0.0",
            "description": "PostGIS spatial extension",
            "relocatable": True,
        }

    def test_to_dict_minimal(self):
        """Test serialization with minimal extension."""
        ext = Extension("postgis")
        result = ext.to_dict()
        assert result["name"] == "postgis"
        assert result["version"] is None
        assert result["schema"] is None
        assert result["description"] is None
        assert result["relocatable"] is False

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "name": "postgis",
            "version": "3.0.0",
            "schema": "public",
            "description": "PostGIS spatial extension",
            "relocatable": True,
            "dialect": "postgresql",
        }
        ext = Extension.from_dict(data)
        assert ext.name == "postgis"
        assert ext.version == "3.0.0"
        assert ext.schema == "public"
        assert ext.description == "PostGIS spatial extension"
        assert ext.relocatable is True
        assert ext.dialect == "postgresql"

    def test_from_dict_minimal(self):
        """Test deserialization with minimal data."""
        data = {"name": "postgis"}
        ext = Extension.from_dict(data)
        assert ext.name == "postgis"
        assert ext.version is None
        assert ext.schema is None
        assert ext.description is None
        assert ext.relocatable is False

    def test_from_dict_empty_name(self):
        """Test deserialization with empty name."""
        data = {}
        ext = Extension.from_dict(data)
        assert ext.name == ""
