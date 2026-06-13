"""Tests for DataTypeNormalizer.

This module tests the data type normalization functionality across all
supported SQL dialects.
"""

import pytest

from core.comparison.type_normalizer import DataTypeNormalizer

pytestmark = [pytest.mark.unit]


class TestDataTypeNormalizer:
    """Test DataTypeNormalizer class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()

    # ========== PostgreSQL Type Normalization ==========

    def test_postgresql_int_to_integer(self):
        """Test INT → INTEGER normalization for PostgreSQL."""
        result = self.normalizer.normalize("INT", "postgresql")
        assert result == "INTEGER"

    def test_postgresql_serial_to_integer(self):
        """Test SERIAL → INTEGER normalization for PostgreSQL."""
        result = self.normalizer.normalize("SERIAL", "postgresql")
        assert result == "INTEGER"

    def test_postgresql_character_varying_to_varchar(self):
        """Test CHARACTER VARYING → VARCHAR normalization for PostgreSQL."""
        result = self.normalizer.normalize("CHARACTER VARYING", "postgresql")
        assert result == "VARCHAR"

    def test_postgresql_bool_to_boolean(self):
        """Test BOOL → BOOLEAN normalization for PostgreSQL."""
        result = self.normalizer.normalize("BOOL", "postgresql")
        assert result == "BOOLEAN"

    # ========== Oracle Type Normalization ==========

    def test_oracle_varchar2_to_varchar(self):
        """Test VARCHAR2 → VARCHAR normalization for Oracle."""
        result = self.normalizer.normalize("VARCHAR2", "oracle")
        assert result == "VARCHAR"

    def test_oracle_varchar2_with_precision(self):
        """Test VARCHAR2(100) → VARCHAR(100) for Oracle."""
        result = self.normalizer.normalize("VARCHAR2(100)", "oracle")
        assert result == "VARCHAR(100)"

    def test_oracle_int_to_number(self):
        """Test INT → NUMBER normalization for Oracle."""
        result = self.normalizer.normalize("INT", "oracle")
        assert result == "NUMBER"

    # ========== MySQL Type Normalization ==========

    def test_mysql_int_to_integer(self):
        """Test INT → INTEGER normalization for MySQL."""
        result = self.normalizer.normalize("INT", "mysql")
        assert result == "INTEGER"

    def test_mysql_bool_to_boolean(self):
        """Test BOOL → BOOLEAN normalization for MySQL."""
        result = self.normalizer.normalize("BOOL", "mysql")
        assert result == "BOOLEAN"

    def test_mysql_double_precision_to_double(self):
        """Test DOUBLE PRECISION → DOUBLE normalization for MySQL."""
        result = self.normalizer.normalize("DOUBLE PRECISION", "mysql")
        assert result == "DOUBLE"

    # ========== SQL Server Type Normalization ==========

    def test_sqlserver_int_to_integer(self):
        """Test INT → INTEGER normalization for SQL Server."""
        result = self.normalizer.normalize("INT", "sqlserver")
        assert result == "INTEGER"

    def test_sqlserver_text_to_varchar(self):
        """Test TEXT → VARCHAR normalization for SQL Server."""
        result = self.normalizer.normalize("TEXT", "sqlserver")
        assert result == "VARCHAR"

    # ========== DB2 Type Normalization ==========

    def test_db2_int_to_integer(self):
        """Test INT → INTEGER normalization for DB2."""
        result = self.normalizer.normalize("INT", "db2")
        assert result == "INTEGER"

    def test_db2_character_varying_to_varchar(self):
        """Test CHARACTER VARYING → VARCHAR normalization for DB2."""
        result = self.normalizer.normalize("CHARACTER VARYING", "db2")
        assert result == "VARCHAR"

    # ========== Precision/Scale Extraction ==========

    def test_extract_precision_only(self):
        """Test extracting precision without scale."""
        precision, scale = self.normalizer.extract_precision_scale("VARCHAR(100)")
        assert precision == 100
        assert scale is None

    def test_extract_precision_and_scale(self):
        """Test extracting both precision and scale."""
        precision, scale = self.normalizer.extract_precision_scale("NUMBER(10,2)")
        assert precision == 10
        assert scale == 2

    def test_extract_precision_scale_no_match(self):
        """Test extraction with no precision/scale."""
        precision, scale = self.normalizer.extract_precision_scale("INTEGER")
        assert precision is None
        assert scale is None

    def test_extract_precision_with_spaces(self):
        """Test extraction with spaces in type."""
        precision, scale = self.normalizer.extract_precision_scale("DECIMAL(15, 4)")
        assert precision == 15
        assert scale == 4

    # ========== Precision/Scale Preservation ==========

    def test_normalize_with_precision(self):
        """Test normalization preserves precision."""
        result = self.normalizer.normalize("VARCHAR(255)", "postgresql")
        assert result == "VARCHAR(255)"

    def test_normalize_with_precision_and_scale(self):
        """Test normalization preserves precision and scale."""
        result = self.normalizer.normalize("NUMBER(10,2)", "oracle")
        assert result == "NUMBER(10,2)"

    def test_normalize_oracle_varchar2_preserves_precision(self):
        """Test VARCHAR2(100) → VARCHAR(100) preserves precision."""
        result = self.normalizer.normalize("VARCHAR2(100)", "oracle")
        assert result == "VARCHAR(100)"

    # ========== Base Type Extraction ==========

    def test_extract_base_type_simple(self):
        """Test extracting base type from simple type."""
        base_type = self.normalizer._extract_base_type("INTEGER")
        assert base_type == "INTEGER"

    def test_extract_base_type_with_precision(self):
        """Test extracting base type with precision."""
        base_type = self.normalizer._extract_base_type("VARCHAR(100)")
        assert base_type == "VARCHAR"

    def test_extract_base_type_with_precision_and_scale(self):
        """Test extracting base type with precision and scale."""
        base_type = self.normalizer._extract_base_type("NUMBER(10,2)")
        assert base_type == "NUMBER"

    # ========== Cross-Dialect Equivalence ==========

    def test_are_equivalent_same_normalized_type(self):
        """Test equivalence when normalized types match."""
        result = self.normalizer.are_equivalent("INT", "INTEGER", "postgresql", "postgresql")
        assert result is True

    def test_are_equivalent_cross_dialect_integer(self):
        """Test INT (PostgreSQL) is equivalent to NUMBER (Oracle)."""
        result = self.normalizer.are_equivalent("INT", "INT", "postgresql", "oracle")
        assert result is True

    def test_are_equivalent_text_types(self):
        """Test TEXT (PostgreSQL) is equivalent to CLOB (Oracle)."""
        result = self.normalizer.are_equivalent("TEXT", "CLOB", "postgresql", "oracle")
        assert result is True

    def test_are_equivalent_varchar_types(self):
        """Test VARCHAR is equivalent to VARCHAR2."""
        result = self.normalizer.are_equivalent("VARCHAR", "VARCHAR2", "postgresql", "oracle")
        assert result is True

    def test_are_not_equivalent_different_types(self):
        """Test INT and VARCHAR are not equivalent."""
        result = self.normalizer.are_equivalent("INT", "VARCHAR", "mysql", "mysql")
        assert result is False

    def test_are_equivalent_with_precision(self):
        """Test equivalence preserves precision match."""
        result = self.normalizer.are_equivalent(
            "VARCHAR(100)", "VARCHAR2(100)", "postgresql", "oracle"
        )
        assert result is True

    # ========== Case Insensitivity ==========

    def test_normalize_lowercase_type(self):
        """Test normalization handles lowercase types."""
        result = self.normalizer.normalize("int", "postgresql")
        assert result == "INTEGER"

    def test_normalize_mixed_case_type(self):
        """Test normalization handles mixed case types."""
        result = self.normalizer.normalize("VarChar", "postgresql")
        assert result == "VARCHAR"

    # ========== Edge Cases ==========

    def test_normalize_empty_string(self):
        """Test normalizing empty string returns empty string."""
        result = self.normalizer.normalize("", "postgresql")
        assert result == ""

    def test_normalize_unknown_type(self):
        """Test normalizing unknown type returns original."""
        result = self.normalizer.normalize("CUSTOM_TYPE", "postgresql")
        assert result == "CUSTOM_TYPE"

    def test_normalize_unknown_dialect(self):
        """Test normalizing with unknown dialect returns original."""
        result = self.normalizer.normalize("INT", "unknown_dialect")
        assert result == "INT"

    # ========== Complex Type Names ==========

    def test_normalize_timestamp_with_timezone(self):
        """Test normalizing TIMESTAMPTZ → TIMESTAMP WITH TIME ZONE."""
        result = self.normalizer.normalize("TIMESTAMPTZ", "postgresql")
        assert result == "TIMESTAMP WITH TIME ZONE"

    def test_normalize_double_precision(self):
        """Test normalizing DOUBLE PRECISION stays DOUBLE PRECISION in PostgreSQL."""
        result = self.normalizer.normalize("DOUBLE PRECISION", "postgresql")
        assert result == "DOUBLE PRECISION"

    def test_normalize_national_character_varying(self):
        """Test normalizing NATIONAL CHARACTER VARYING → NVARCHAR in SQL Server."""
        result = self.normalizer.normalize("NATIONAL CHARACTER VARYING", "sqlserver")
        assert result == "NVARCHAR"

    # ========== Regression Tests ==========

    def test_postgresql_bigserial_to_bigint(self):
        """Test BIGSERIAL → BIGINT normalization for PostgreSQL."""
        result = self.normalizer.normalize("BIGSERIAL", "postgresql")
        assert result == "BIGINT"

    def test_mysql_tinyint_stays_tinyint(self):
        """Test TINYINT stays TINYINT for MySQL (not normalized to INTEGER)."""
        result = self.normalizer.normalize("TINYINT", "mysql")
        assert result == "TINYINT"

    def test_mysql_tinyint_with_precision(self):
        """Test TINYINT(1) normalizes to BOOLEAN (MySQL uses TINYINT(1) for boolean)."""
        result = self.normalizer.normalize("TINYINT(1)", "mysql")
        assert result == "BOOLEAN"

    def test_oracle_long_to_clob(self):
        """Test LONG → CLOB normalization for Oracle."""
        result = self.normalizer.normalize("LONG", "oracle")
        assert result == "CLOB"

    # ========== Integration Tests ==========

    def test_full_workflow_postgresql_to_oracle(self):
        """Test full normalization workflow from PostgreSQL to Oracle."""
        pg_type = "TEXT"
        oracle_type = "CLOB"

        # Normalize both
        norm_pg = self.normalizer.normalize(pg_type, "postgresql")
        norm_oracle = self.normalizer.normalize(oracle_type, "oracle")

        # Check equivalence
        are_equiv = self.normalizer.are_equivalent(pg_type, oracle_type, "postgresql", "oracle")

        assert norm_pg == "TEXT"
        assert norm_oracle == "CLOB"
        assert are_equiv is True

    def test_full_workflow_varchar_with_precision(self):
        """Test full workflow with VARCHAR precision preservation."""
        pg_type = "CHARACTER VARYING(255)"
        oracle_type = "VARCHAR2(255)"

        # Normalize both
        norm_pg = self.normalizer.normalize(pg_type, "postgresql")
        norm_oracle = self.normalizer.normalize(oracle_type, "oracle")

        # Both should normalize to VARCHAR(255)
        assert norm_pg == "VARCHAR(255)"
        assert norm_oracle == "VARCHAR(255)"

        # Check equivalence
        are_equiv = self.normalizer.are_equivalent(pg_type, oracle_type, "postgresql", "oracle")
        assert are_equiv is True

    # ========== None Guard Tests (Story 16-5) ==========

    def test_are_equivalent_none_type1_returns_false(self):
        """AC#1: type1 None → False sans exception."""
        result = self.normalizer.are_equivalent(None, "INTEGER", "postgresql", "postgresql")
        assert result is False

    def test_are_equivalent_none_type2_returns_false(self):
        """AC#1 bis: type2 None → False sans exception."""
        result = self.normalizer.are_equivalent("INT", None, "mysql", "mysql")
        assert result is False

    def test_are_equivalent_both_none_returns_false(self):
        """AC#2: double None → False."""
        result = self.normalizer.are_equivalent(None, None, "oracle", "oracle")
        assert result is False

    def test_are_equivalent_empty_string_returns_false(self):
        """AC#3: chaîne vide → False."""
        result = self.normalizer.are_equivalent("", "INTEGER", "postgresql", "postgresql")
        assert result is False

    def test_are_equivalent_none_cross_dialect_no_exception(self):
        """AC#4: None + cross-dialect → False sans TypeError."""
        result = self.normalizer.are_equivalent(None, "INT", "postgresql", "oracle")
        assert result is False

    def test_are_equivalent_empty_type2_returns_false(self):
        """AC#3 bis: type2 chaîne vide → False (symétrie avec type1 vide)."""
        result = self.normalizer.are_equivalent("INTEGER", "", "postgresql", "postgresql")
        assert result is False
