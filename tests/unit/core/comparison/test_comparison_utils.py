"""Unit tests for core.comparison.comparison_utils module."""

import pytest

from core.comparison.comparison_utils import (
    extract_base_identity_type,
    is_system_generated_constraint_name,
    normalize_expression,
    normalize_identifier,
    normalize_package_code,
    normalize_parameters,
    normalize_view_definition,
)


@pytest.mark.unit
class TestIsSystemGeneratedConstraintName:
    """Test is_system_generated_constraint_name function."""

    def test_oracle_sys_c_pattern(self):
        """Test Oracle SYS_C pattern."""
        assert is_system_generated_constraint_name("SYS_C0013220") is True
        assert is_system_generated_constraint_name("SYS_C123") is True
        assert is_system_generated_constraint_name("sys_c0013220") is True

    def test_oracle_sys_c_invalid(self):
        """Test Oracle SYS_C with non-numeric suffix."""
        assert is_system_generated_constraint_name("SYS_CABC") is False
        assert is_system_generated_constraint_name("SYS_C") is False

    def test_sql_server_pk_pattern(self):
        """Test SQL Server PK__ pattern."""
        assert is_system_generated_constraint_name("PK__TableName__Hash") is True
        assert is_system_generated_constraint_name("PK__users__3213E83F") is True
        assert is_system_generated_constraint_name("pk__tablename__hash") is True

    def test_sql_server_fk_pattern(self):
        """Test SQL Server FK__ pattern."""
        assert is_system_generated_constraint_name("FK__TableName__Hash") is True
        assert is_system_generated_constraint_name("FK__users__3213E83F") is True

    def test_postgresql_pkey(self):
        """Test PostgreSQL _pkey suffix."""
        assert is_system_generated_constraint_name("users_pkey") is True
        assert is_system_generated_constraint_name("tablename_pkey") is True

    def test_postgresql_fkey(self):
        """Test PostgreSQL _fkey suffix."""
        assert is_system_generated_constraint_name("users_fkey") is True
        assert is_system_generated_constraint_name("tablename_fkey") is True

    def test_postgresql_key_pattern(self):
        """Test PostgreSQL _key pattern with underscore."""
        assert is_system_generated_constraint_name("users_email_key") is True
        assert is_system_generated_constraint_name("tablename_columnname_key") is True

    def test_postgresql_key_single_word(self):
        """Test single-word _key (user-defined)."""
        assert is_system_generated_constraint_name("apikey") is False
        assert is_system_generated_constraint_name("mykey") is False

    def test_postgresql_key_user_defined_keywords(self):
        """Test _key with user-defined keywords."""
        assert is_system_generated_constraint_name("my_api_key") is False
        assert is_system_generated_constraint_name("primary_key_override") is False
        assert is_system_generated_constraint_name("foreign_key_constraint") is False

    def test_postgresql_check_pattern(self):
        """Test PostgreSQL _check pattern."""
        assert is_system_generated_constraint_name("users_age_check") is True
        assert is_system_generated_constraint_name("tablename_columnname_check") is True

    def test_postgresql_check_single_word(self):
        """Test single-word _check (user-defined)."""
        assert is_system_generated_constraint_name("check") is False

    def test_postgresql_check_user_defined_keywords(self):
        """Test _check with user-defined keywords."""
        assert is_system_generated_constraint_name("health_check") is False
        assert is_system_generated_constraint_name("data_check_validation") is False

    def test_unnamed_pattern(self):
        """Test unnamed_ pattern."""
        assert is_system_generated_constraint_name("unnamed_1") is True
        assert is_system_generated_constraint_name("unnamed_123") is True

    def test_user_defined_names(self):
        """Test user-defined constraint names."""
        assert is_system_generated_constraint_name("pk_users_id") is False
        assert is_system_generated_constraint_name("fk_orders_users") is False
        assert is_system_generated_constraint_name("unique_email") is False
        assert is_system_generated_constraint_name("check_age_positive") is False

    def test_empty_or_none(self):
        """Test empty or None names."""
        assert is_system_generated_constraint_name("") is False
        assert is_system_generated_constraint_name(None) is False


@pytest.mark.unit
class TestExtractBaseIdentityType:
    """Test extract_base_identity_type function."""

    def test_postgresql_serial(self):
        """Test PostgreSQL SERIAL types."""
        assert extract_base_identity_type("SERIAL", "postgresql") == "INTEGER"
        assert extract_base_identity_type("BIGSERIAL", "postgresql") == "BIGINT"
        assert extract_base_identity_type("SMALLSERIAL", "postgresql") == "SMALLINT"

    def test_postgresql_serial_with_modifiers(self):
        """Test PostgreSQL SERIAL with modifiers."""
        assert extract_base_identity_type("SERIAL NOT NULL", "postgresql") == "INTEGER"
        assert extract_base_identity_type("BIGSERIAL PRIMARY KEY", "postgresql") == "BIGINT"

    def test_sql_server_identity(self):
        """Test SQL Server IDENTITY syntax."""
        assert extract_base_identity_type("INT IDENTITY(1,1)", "sqlserver") == "INT"
        assert extract_base_identity_type("BIGINT IDENTITY(1,1)", "sqlserver") == "BIGINT"

    def test_oracle_generated_always(self):
        """Test Oracle GENERATED ALWAYS AS IDENTITY."""
        result = extract_base_identity_type("NUMBER GENERATED ALWAYS AS IDENTITY", "oracle")
        assert "NUMBER" in result or result == "NUMBER"

    def test_oracle_generated_by_default(self):
        """Test Oracle GENERATED BY DEFAULT AS IDENTITY."""
        result = extract_base_identity_type("NUMBER GENERATED BY DEFAULT AS IDENTITY", "oracle")
        assert "NUMBER" in result or result == "NUMBER"

    def test_mysql_auto_increment(self):
        """Test MySQL AUTO_INCREMENT."""
        assert extract_base_identity_type("INT AUTO_INCREMENT", "mysql") == "INT"
        assert extract_base_identity_type("BIGINT AUTO_INCREMENT", "mysql") == "BIGINT"

    def test_identity_keyword_only(self):
        """Test IDENTITY keyword alone."""
        result = extract_base_identity_type("INTEGER IDENTITY", "sqlserver")
        assert "INTEGER" in result

    def test_no_identity(self):
        """Test types without identity."""
        assert extract_base_identity_type("INTEGER", "postgresql") == "INTEGER"
        assert extract_base_identity_type("VARCHAR(255)", "postgresql") == "VARCHAR(255)"

    def test_empty_or_none(self):
        """Test empty or None input."""
        assert extract_base_identity_type("", "postgresql") == ""
        assert extract_base_identity_type(None, "postgresql") == ""


@pytest.mark.unit
class TestNormalizeIdentifier:
    """Test normalize_identifier function."""

    def test_basic_normalization(self):
        """Test basic identifier normalization."""
        assert normalize_identifier("Users") == "users"
        assert normalize_identifier("USERS") == "users"
        assert normalize_identifier("users") == "users"

    def test_none_or_empty(self):
        """Test None or empty identifiers."""
        assert normalize_identifier(None) == ""
        assert normalize_identifier("") == ""

    def test_java_string_object(self):
        """Test handling of Java string objects."""

        class JavaString:
            def __str__(self):
                return "TestTable"

        java_str = JavaString()
        assert normalize_identifier(java_str) == "testtable"


@pytest.mark.unit
class TestNormalizeExpression:
    """Test normalize_expression function."""

    def test_basic_normalization(self):
        """Test basic expression normalization."""
        assert normalize_expression("price * quantity") == "PRICE * QUANTITY"
        assert normalize_expression("  price   *   quantity  ") == "PRICE * QUANTITY"

    def test_none_or_empty(self):
        """Test None or empty expressions."""
        assert normalize_expression(None) is None
        assert normalize_expression("") == ""

    def test_check_keyword_removal(self):
        """Test CHECK keyword removal."""
        assert normalize_expression("CHECK (price >= 0)") == "PRICE >= 0"
        assert normalize_expression("check (price >= 0)") == "PRICE >= 0"

    def test_parentheses_removal(self):
        """Test outer parentheses removal."""
        assert normalize_expression("(price >= 0)") == "PRICE >= 0"
        assert normalize_expression("((price >= 0))") == "PRICE >= 0"

    def test_oracle_quoted_identifiers(self):
        """Test Oracle quoted identifier removal."""
        assert normalize_expression('"PRICE" * "QUANTITY"') == "PRICE * QUANTITY"
        assert normalize_expression('"Price" * "Quantity"') == "PRICE * QUANTITY"

    def test_mysql_backticks(self):
        """Test MySQL backtick removal."""
        assert normalize_expression("`price` * `quantity`") == "PRICE * QUANTITY"

    def test_mysql_character_set_introducers(self):
        """Test MySQL character set introducer removal."""
        assert normalize_expression("_utf8mb4'text'") == "'text'"
        assert normalize_expression("_utf8'text'") == "'text'"

    def test_postgresql_type_casts(self):
        """Test PostgreSQL type cast removal."""
        assert normalize_expression("price::TEXT") == "PRICE"
        assert normalize_expression("data::JSONB") == "DATA"

    def test_operator_spacing(self):
        """Test operator spacing normalization."""
        assert normalize_expression("price*quantity") == "PRICE * QUANTITY"
        assert normalize_expression("price >= quantity") == "PRICE >= QUANTITY"
        assert normalize_expression("price<=quantity") == "PRICE <= QUANTITY"

    def test_compound_operators(self):
        """Test compound operator handling."""
        assert normalize_expression("price>=0") == "PRICE >= 0"
        assert normalize_expression("price<=100") == "PRICE <= 100"
        assert normalize_expression("price<>0") == "PRICE <> 0"

    def test_boolean_wrapper_removal(self):
        """Test boolean wrapper removal."""
        # This is complex logic, test basic cases
        result = normalize_expression("((price >= 0))")
        assert "PRICE" in result
        assert ">=" in result
        assert "0" in result

    def test_non_string_input(self):
        """Test non-string input conversion."""
        assert normalize_expression(123) == "123"
        assert normalize_expression(True) == "TRUE"


@pytest.mark.unit
class TestNormalizeParameters:
    """Test normalize_parameters function."""

    def test_empty_or_none(self):
        """Test empty or None parameters."""
        assert normalize_parameters(None) == ""
        assert normalize_parameters([]) == ""

    def test_string_parameters(self):
        """Test string parameter list."""
        params = ["IN id INTEGER", "IN name VARCHAR(255)"]
        result = normalize_parameters(params)
        assert "IN ID INTEGER" in result
        assert "IN NAME VARCHAR(255)" in result

    def test_object_parameters(self):
        """Test parameter object list."""

        class Param:
            def __init__(self, name, data_type, direction="IN", default_value=None):
                self.name = name
                self.data_type = data_type
                self.direction = direction
                self.default_value = default_value

        params = [
            Param("id", "INTEGER", "IN"),
            Param("name", "VARCHAR(255)", "IN", "default"),
        ]
        result = normalize_parameters(params)
        assert "IN ID INTEGER" in result
        assert "IN NAME VARCHAR(255) = DEFAULT" in result

    def test_parameter_sorting(self):
        """Test that parameters are sorted."""
        params = ["IN name VARCHAR", "IN id INTEGER"]
        result = normalize_parameters(params)
        # Should be sorted alphabetically
        assert result.index("ID") < result.index("NAME")


@pytest.mark.unit
class TestNormalizePackageCode:
    """Test normalize_package_code function."""

    def test_empty_or_none(self):
        """Test empty or None code."""
        assert normalize_package_code(None) == ""
        assert normalize_package_code("") == ""

    def test_comment_removal(self):
        """Test comment removal."""
        code = """
        CREATE PACKAGE test AS
        -- This is a comment
        PROCEDURE test_proc;
        /* Multi-line
           comment */
        END;
        """
        result = normalize_package_code(code)
        assert "--" not in result
        assert "/*" not in result
        assert "comment" not in result.lower()

    def test_whitespace_normalization(self):
        """Test whitespace normalization."""
        code = "CREATE   PACKAGE    test    AS"
        result = normalize_package_code(code)
        assert "   " not in result
        assert "    " not in result

    def test_case_normalization(self):
        """Test case normalization to uppercase."""
        code = "create package test as procedure test_proc; end;"
        result = normalize_package_code(code)
        assert result.isupper()

    def test_punctuation_spacing(self):
        """Test punctuation spacing removal."""
        code = "CREATE PACKAGE ( test ) AS PROCEDURE test_proc ( ) ; END ;"
        result = normalize_package_code(code)
        # Function uppercases everything, so check for uppercase
        assert "(TEST)" in result or "TEST" in result
        assert "  " not in result

    def test_complex_package(self):
        """Test complex package code normalization."""
        code = """
        CREATE OR REPLACE PACKAGE test_pkg AS
            PROCEDURE proc1 ( p_id IN INTEGER );
            FUNCTION func1 RETURN VARCHAR2;
        END test_pkg;
        """
        result = normalize_package_code(code)
        assert "CREATE" in result
        assert "PACKAGE" in result
        assert "PROCEDURE" in result
        assert "FUNCTION" in result


@pytest.mark.unit
class TestNormalizeViewDefinition:
    """Tests for the shared normalize_view_definition utility (DEDUP-29)."""

    def test_none_returns_empty_string(self):
        """None input returns empty string."""
        assert normalize_view_definition(None) == ""

    def test_empty_string_returns_empty_string(self):
        """Empty string input returns empty string."""
        assert normalize_view_definition("") == ""

    def test_simple_select_uppercased(self):
        """Simple SELECT is normalized to uppercase."""
        result = normalize_view_definition("select id, name from users", "postgresql")
        assert "SELECT" in result
        assert "FROM" in result

    def test_removes_single_line_comments(self):
        """Single-line SQL comments are stripped."""
        definition = "SELECT id -- primary key\nFROM users"
        result = normalize_view_definition(definition)
        assert "--" not in result
        assert "primary key" not in result.lower()

    def test_removes_multiline_comments(self):
        """Multi-line SQL comments are stripped."""
        definition = "SELECT id /* this is a comment */ FROM users"
        result = normalize_view_definition(definition)
        assert "/*" not in result
        assert "this is a comment" not in result.lower()

    def test_normalizes_whitespace(self):
        """Multiple whitespace characters are collapsed."""
        definition = "SELECT   id,   name\n\n  FROM   users"
        result = normalize_view_definition(definition)
        assert "  " not in result

    def test_dialect_parameter_accepted(self):
        """Function accepts an optional dialect argument without error."""
        result = normalize_view_definition("SELECT 1", "mysql")
        assert result != ""

    def test_semantically_identical_definitions_compare_equal(self):
        """Two definitions that differ only in whitespace/case normalize identically."""
        def1 = "select id, name from users where active = 1"
        def2 = "SELECT  id,  name  FROM  users  WHERE  active = 1"
        assert normalize_view_definition(def1) == normalize_view_definition(def2)
