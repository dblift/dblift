"""
Unit tests for CanonicalTypeMapper.
"""

import pytest

from core.normalization.type_mapper import CanonicalTypeMapper

pytestmark = [pytest.mark.unit]


class TestCanonicalTypeMapper:
    """Test cases for CanonicalTypeMapper."""

    def test_to_canonical_basic_types(self):
        """Test basic type canonicalization."""
        mapper = CanonicalTypeMapper()

        assert mapper.to_canonical("INT") == "INTEGER"
        assert mapper.to_canonical("INTEGER") == "INTEGER"
        assert mapper.to_canonical("INT4") == "INTEGER"
        assert mapper.to_canonical("VARCHAR") == "VARCHAR"
        assert mapper.to_canonical("VARCHAR2") == "VARCHAR"
        assert mapper.to_canonical("CHAR") == "CHAR"
        assert mapper.to_canonical("TEXT") == "TEXT"

    def test_to_canonical_with_dialect(self):
        """Test canonicalization with dialect context."""
        mapper = CanonicalTypeMapper()

        # PostgreSQL
        assert mapper.to_canonical("INT", "postgresql") == "INTEGER"
        assert mapper.to_canonical("INT4", "postgresql") == "INTEGER"

        # Oracle
        assert mapper.to_canonical("VARCHAR2(100)", "oracle") == "VARCHAR"
        assert mapper.to_canonical("NUMBER(10,0)", "oracle") == "INTEGER"

        # MySQL
        assert mapper.to_canonical("INT", "mysql") == "INTEGER"
        assert mapper.to_canonical("TINYINT", "mysql") == "SMALLINT"

    def test_to_canonical_with_precision(self):
        """Test canonicalization preserves precision/scale info conceptually."""
        mapper = CanonicalTypeMapper()

        # Base type should be extracted correctly
        assert mapper.to_canonical("VARCHAR(100)") == "VARCHAR"
        assert mapper.to_canonical("DECIMAL(10,2)") == "NUMERIC"
        assert mapper.to_canonical("NUMBER(10,0)") == "INTEGER"

    def test_from_canonical_basic(self):
        """Test reverse mapping from canonical to vendor types."""
        mapper = CanonicalTypeMapper()

        # PostgreSQL
        assert mapper.from_canonical("INTEGER", "postgresql") == "INTEGER"
        assert mapper.from_canonical("VARCHAR", "postgresql") == "VARCHAR"

        # Oracle
        assert mapper.from_canonical("INTEGER", "oracle") == "NUMBER"
        assert mapper.from_canonical("VARCHAR", "oracle") == "VARCHAR2"

        # MySQL
        assert mapper.from_canonical("INTEGER", "mysql") == "INT"
        assert mapper.from_canonical("TIMESTAMP", "mysql") == "DATETIME"

        # SQL Server
        assert mapper.from_canonical("INTEGER", "sqlserver") == "INT"
        assert mapper.from_canonical("TIMESTAMP", "sqlserver") == "DATETIME2"

    def test_get_canonical_variants(self):
        """Test getting all variants for a canonical type."""
        mapper = CanonicalTypeMapper()

        variants = mapper.get_canonical_variants("INTEGER")
        assert "INTEGER" in variants
        assert "INT" in variants
        assert "INT4" in variants
        assert "NUMBER" in variants

        variants = mapper.get_canonical_variants("VARCHAR")
        assert "VARCHAR" in variants
        assert "VARCHAR2" in variants
        assert "CHARACTER VARYING" in variants

    def test_are_same_canonical(self):
        """Test checking if two types map to same canonical type."""
        mapper = CanonicalTypeMapper()

        assert mapper.are_same_canonical("INT", "INTEGER")
        assert mapper.are_same_canonical("VARCHAR2", "VARCHAR")
        assert mapper.are_same_canonical("INT", "INT4", "postgresql", "postgresql")
        assert not mapper.are_same_canonical("INT", "VARCHAR")
        assert not mapper.are_same_canonical("INTEGER", "SMALLINT")

    def test_version_specific_mappings(self):
        """Test version-specific type mappings."""
        from core.normalization.type_mappings import VERSION_SPECIFIC_MAPPINGS

        assert VERSION_SPECIFIC_MAPPINGS
        assert ("postgresql", "9.4+") in VERSION_SPECIFIC_MAPPINGS
        assert ("oracle", "12.2+") in VERSION_SPECIFIC_MAPPINGS
        assert ("mysql", "5.7+") in VERSION_SPECIFIC_MAPPINGS
        assert ("sqlserver", "13.0+") in VERSION_SPECIFIC_MAPPINGS
        assert ("mariadb", "10.2+") in VERSION_SPECIFIC_MAPPINGS

        mapper = CanonicalTypeMapper()

        # JSONB in PostgreSQL 9.4+
        result = mapper.to_canonical("JSONB", "postgresql", "9.4")
        assert result == "JSON"

        # JSON in Oracle 12.2+
        result = mapper.to_canonical("JSON", "oracle", "12.2")
        assert result == "JSON"

        # JSON in MariaDB 10.2+
        assert mapper.to_canonical("JSON", "mariadb", "10.5") == "JSON"

    def test_type_aliases(self):
        """Test type alias resolution."""
        mapper = CanonicalTypeMapper()

        # Should handle aliases
        assert mapper.to_canonical("INT4") == "INTEGER"
        assert mapper.to_canonical("FLOAT4") == "REAL"
        assert mapper.to_canonical("FLOAT8") == "DOUBLE"
