"""Tests for SafetyChecker class."""

from unittest.mock import MagicMock, patch

import pytest

from core.sql_generator.safety_checker import (
    PRECISION_BASED_TYPES,
    SAFE_TYPE_CONVERSIONS,
    SIZE_BASED_TYPES,
    SafetyChecker,
    SafetyCheckResult,
)
from core.sql_model.base import SqlColumn
from core.sql_model.table import Table


@pytest.mark.unit
class TestSafetyCheckResult:
    """Tests for SafetyCheckResult dataclass."""

    def test_init_safe(self):
        """Test initialization with safe=True."""
        result = SafetyCheckResult(safe=True)
        assert result.safe is True
        assert result.error is None
        assert result.suggestion is None
        assert result.warnings == []
        assert result.details == {}

    def test_init_unsafe(self):
        """Test initialization with safe=False."""
        result = SafetyCheckResult(safe=False, error="Test error")
        assert result.safe is False
        assert result.error == "Test error"

    def test_str_safe(self):
        """Test string representation for safe result."""
        result = SafetyCheckResult(safe=True)
        assert str(result) == "Safe"

    def test_str_safe_with_warnings(self):
        """Test string representation for safe result with warnings."""
        result = SafetyCheckResult(safe=True, warnings=["Warning 1", "Warning 2"])
        assert "Safe" in str(result)
        assert "Warning 1" in str(result)
        assert "Warning 2" in str(result)

    def test_str_unsafe(self):
        """Test string representation for unsafe result."""
        result = SafetyCheckResult(safe=False, error="Test error")
        assert str(result) == "Unsafe: Test error"

    def test_add_warning(self):
        """Test adding warnings."""
        result = SafetyCheckResult(safe=True)
        result.add_warning("Warning 1")
        result.add_warning("Warning 2")
        assert len(result.warnings) == 2
        assert "Warning 1" in result.warnings
        assert "Warning 2" in result.warnings


@pytest.mark.unit
class TestSafetyCheckerInit:
    """Tests for SafetyChecker initialization."""

    def test_init_default(self):
        """Test initialization with default dialect."""
        checker = SafetyChecker()
        assert checker.dialect == "postgresql"

    def test_init_postgresql(self):
        """Test initialization with PostgreSQL dialect."""
        checker = SafetyChecker(dialect="postgresql")
        assert checker.dialect == "postgresql"

    def test_init_sqlserver(self):
        """Test initialization with SQL Server dialect."""
        checker = SafetyChecker(dialect="sqlserver")
        assert checker.dialect == "sqlserver"

    def test_init_mysql(self):
        """Test initialization with MySQL dialect."""
        checker = SafetyChecker(dialect="mysql")
        assert checker.dialect == "mysql"

    def test_init_oracle(self):
        """Test initialization with Oracle dialect."""
        checker = SafetyChecker(dialect="oracle")
        assert checker.dialect == "oracle"

    def test_init_db2(self):
        """Test initialization with DB2 dialect."""
        checker = SafetyChecker(dialect="db2")
        assert checker.dialect == "db2"

    def test_init_lowercase(self):
        """Test initialization converts dialect to lowercase."""
        checker = SafetyChecker(dialect="POSTGRESQL")
        assert checker.dialect == "postgresql"


@pytest.mark.unit
class TestSafetyCheckerNotNullConstraint:
    """Tests for check_not_null_constraint method."""

    def test_check_not_null_no_provider(self):
        """Test checking NOT NULL without provider."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        result = checker.check_not_null_constraint(table, "id")
        assert result.safe is False
        assert "database connection" in result.error.lower()

    def test_check_not_null_with_null_values(self):
        """Test checking NOT NULL when column has NULL values."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.return_value = [{"null_count": 5}]

        result = checker.check_not_null_constraint(table, "id", provider)
        assert result.safe is False
        assert "5" in result.error
        assert "NULL values" in result.error

    def test_check_not_null_no_null_values(self):
        """Test checking NOT NULL when column has no NULL values."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.return_value = [{"null_count": 0}]

        result = checker.check_not_null_constraint(table, "id", provider)
        assert result.safe is True
        assert result.details["null_count"] == 0

    def test_check_not_null_case_insensitive_count(self):
        """Test checking NOT NULL with case-insensitive column name."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.return_value = [{"NULL_COUNT": 0}]

        result = checker.check_not_null_constraint(table, "id", provider)
        assert result.safe is True

    def test_check_not_null_provider_no_execute_query(self):
        """Test checking NOT NULL when provider lacks execute_query."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        del provider.execute_query

        result = checker.check_not_null_constraint(table, "id", provider)
        assert result.safe is False
        assert "does not support" in result.error.lower()

    def test_check_not_null_exception(self):
        """Test checking NOT NULL when query raises exception."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.side_effect = Exception("Connection error")

        result = checker.check_not_null_constraint(table, "id", provider)
        assert result.safe is False
        assert "error" in result.error.lower()

    def test_check_not_null_with_schema(self):
        """Test checking NOT NULL with schema."""
        checker = SafetyChecker()
        table = Table(
            name="users",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        provider = MagicMock()
        provider.execute_query.return_value = [{"null_count": 0}]

        result = checker.check_not_null_constraint(table, "id", provider)
        assert result.safe is True
        # Verify query includes schema
        call_args = provider.execute_query.call_args[0][0]
        assert "public" in call_args.lower() or '"public"' in call_args


@pytest.mark.unit
class TestSafetyCheckerTypeCompatibility:
    """Tests for check_type_compatibility method."""

    def test_same_type(self):
        """Test checking same type."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("INTEGER", "INTEGER")
        assert result.safe is True

    def test_same_type_case_insensitive(self):
        """Test checking same type with different case."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("integer", "INTEGER")
        assert result.safe is True

    def test_safe_conversion_tinyint_to_int(self):
        """Test safe conversion from TINYINT to INT."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("TINYINT", "INT")
        assert result.safe is True

    def test_safe_conversion_int_to_bigint(self):
        """Test safe conversion from INT to BIGINT."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("INT", "BIGINT")
        assert result.safe is True

    def test_safe_conversion_varchar_to_text(self):
        """Test safe conversion from VARCHAR to TEXT."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("VARCHAR(100)", "TEXT")
        assert result.safe is True

    def test_size_reduction_unsafe(self):
        """Test reducing VARCHAR size is unsafe."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("VARCHAR(100)", "VARCHAR(50)")
        assert result.safe is False
        assert "truncate" in result.error.lower()

    def test_size_increase_safe(self):
        """Test increasing VARCHAR size is safe."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("VARCHAR(50)", "VARCHAR(100)")
        assert result.safe is True

    def test_precision_reduction_unsafe(self):
        """Test reducing NUMERIC precision is unsafe."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("NUMERIC(10,2)", "NUMERIC(5,1)")
        assert result.safe is False
        assert "precision" in result.error.lower()

    def test_precision_increase_safe(self):
        """Test increasing NUMERIC precision is safe."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("NUMERIC(5,1)", "NUMERIC(10,2)")
        assert result.safe is True

    def test_precision_scale_reduction_warning(self):
        """Test reducing scale adds warning."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("NUMERIC(10,5)", "NUMERIC(10,2)")
        assert result.safe is False
        assert len(result.warnings) > 0
        assert any("scale" in w.lower() for w in result.warnings)

    def test_precision_precision_reduction_warning(self):
        """Test reducing precision adds warning."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("NUMERIC(10,2)", "NUMERIC(5,2)")
        assert result.safe is False
        assert len(result.warnings) > 0
        assert any("precision" in w.lower() for w in result.warnings)

    def test_unsafe_conversion_numeric_to_varchar(self):
        """Test conversion from NUMERIC to VARCHAR is unsafe."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("NUMERIC(10,2)", "VARCHAR(50)")
        assert result.safe is False
        assert "data loss" in result.error.lower()

    def test_unsafe_conversion_datetime_to_date(self):
        """Test conversion from DATETIME to DATE is unsafe."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("DATETIME", "DATE")
        assert result.safe is False
        assert "data loss" in result.error.lower()

    def test_unknown_conversion_unsafe(self):
        """Test unknown conversion is marked unsafe."""
        checker = SafetyChecker()
        result = checker.check_type_compatibility("UNKNOWN_TYPE", "OTHER_TYPE")
        assert result.safe is False
        assert "data loss" in result.error.lower()

    def test_custom_dialect(self):
        """Test type compatibility check with custom dialect."""
        checker = SafetyChecker(dialect="mysql")
        result = checker.check_type_compatibility("INT", "BIGINT", dialect="postgresql")
        assert result.safe is True


@pytest.mark.unit
class TestSafetyCheckerColumnReferences:
    """Tests for check_column_references method."""

    def test_check_references_no_provider(self):
        """Test checking references without provider."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        result = checker.check_column_references(table, "id")
        assert result.safe is False
        assert "database connection" in result.error.lower()

    def test_check_references_with_fk(self):
        """Test checking references when foreign key exists."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.return_value = [
            {"constraint_name": "fk_orders_user", "table_name": "orders"}
        ]

        result = checker.check_column_references(table, "id", provider)
        assert result.safe is False
        assert "FOREIGN_KEY" in result.error or "fk_orders_user" in result.error

    def test_check_references_with_index(self):
        """Test checking references when index exists."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()

        # First call returns empty (FK check), second returns index
        provider.execute_query.side_effect = [
            [],  # FK query
            [{"index_name": "idx_users_id"}],  # Index query
        ]

        result = checker.check_column_references(table, "id", provider)
        assert result.safe is False
        assert "INDEX" in result.error or "idx_users_id" in result.error

    def test_check_references_no_references(self):
        """Test checking references when no references exist."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.return_value = []

        result = checker.check_column_references(table, "id", provider)
        assert result.safe is True
        assert result.details["references"] == []

    def test_check_references_exception(self):
        """Test checking references when query raises exception."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.side_effect = Exception("Query error")

        result = checker.check_column_references(table, "id", provider)
        assert result.safe is False
        assert "error" in result.error.lower()


@pytest.mark.unit
class TestSafetyCheckerTableHasData:
    """Tests for check_table_has_data method."""

    def test_check_table_data_no_provider(self):
        """Test checking table data without provider."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        result = checker.check_table_has_data(table)
        assert result.safe is False
        assert "database connection" in result.error.lower()

    def test_check_table_data_has_data(self):
        """Test checking table data when table has data."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.return_value = [{"has_data": 1}]

        result = checker.check_table_has_data(table, provider)
        assert result.safe is False
        assert "contains data" in result.error.lower()

    def test_check_table_data_no_data(self):
        """Test checking table data when table is empty."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.return_value = [{"has_data": 0}]

        result = checker.check_table_has_data(table, provider)
        assert result.safe is True
        assert result.details["has_data"] is False

    def test_check_table_data_sqlserver(self):
        """Test checking table data for SQL Server dialect."""
        checker = SafetyChecker(dialect="sqlserver")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="sqlserver")
        provider = MagicMock()
        provider.execute_query.return_value = [{"has_data": 0}]

        result = checker.check_table_has_data(table, provider)
        assert result.safe is True
        # Verify SQL Server specific query
        call_args = provider.execute_query.call_args[0][0]
        assert "TOP 1" in call_args.upper()

    def test_check_table_data_oracle(self):
        """Test checking table data for Oracle dialect."""
        checker = SafetyChecker(dialect="oracle")
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="oracle")
        provider = MagicMock()
        provider.execute_query.return_value = [{"has_data": 0}]

        result = checker.check_table_has_data(table, provider)
        assert result.safe is True
        # Verify Oracle specific query
        call_args = provider.execute_query.call_args[0][0]
        assert "ROWNUM" in call_args.upper() or "DUAL" in call_args.upper()

    def test_check_table_data_exception(self):
        """Test checking table data when query raises exception."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        provider.execute_query.side_effect = Exception("Query error")

        result = checker.check_table_has_data(table, provider)
        assert result.safe is False
        assert "error" in result.error.lower()

    def test_check_table_data_provider_no_execute_query(self):
        """Test checking table data when provider lacks execute_query."""
        checker = SafetyChecker()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        provider = MagicMock()
        del provider.execute_query

        result = checker.check_table_has_data(table, provider)
        assert result.safe is False
        assert "does not support" in result.error.lower()


@pytest.mark.unit
class TestSafetyCheckerHelperMethods:
    """Tests for SafetyChecker helper methods."""

    def test_get_default_schema_postgresql(self):
        """Test getting default schema for PostgreSQL."""
        checker = SafetyChecker(dialect="postgresql")
        assert checker._get_default_schema() == "public"

    def test_get_default_schema_sqlserver(self):
        """Test getting default schema for SQL Server."""
        checker = SafetyChecker(dialect="sqlserver")
        assert checker._get_default_schema() == "dbo"

    def test_get_default_schema_mysql(self):
        """Test getting default schema for MySQL."""
        checker = SafetyChecker(dialect="mysql")
        assert checker._get_default_schema() == ""

    def test_get_default_schema_oracle(self):
        """Test getting default schema for Oracle."""
        checker = SafetyChecker(dialect="oracle")
        assert checker._get_default_schema() == ""

    def test_get_default_schema_db2(self):
        """Test getting default schema for DB2."""
        checker = SafetyChecker(dialect="db2")
        assert checker._get_default_schema() == ""

    def test_get_default_schema_unknown(self):
        """Unregistered dialects keep historical ``public`` fallback (PG-safe)."""
        checker = SafetyChecker(dialect="unknown")
        assert checker._get_default_schema() == "public"

    def test_format_table_name_postgresql(self):
        """Test formatting table name for PostgreSQL."""
        checker = SafetyChecker(dialect="postgresql")
        result = checker._format_table_name("public", "users")
        assert result == '"public"."users"'

    def test_format_table_name_postgresql_no_schema(self):
        """Test formatting table name for PostgreSQL without schema."""
        checker = SafetyChecker(dialect="postgresql")
        result = checker._format_table_name("", "users")
        assert result == '"users"'

    def test_format_table_name_sqlserver(self):
        """Test formatting table name for SQL Server."""
        checker = SafetyChecker(dialect="sqlserver")
        result = checker._format_table_name("dbo", "users")
        assert result == "[dbo].[users]"

    def test_format_table_name_sqlserver_escape(self):
        """Test formatting table name for SQL Server with brackets."""
        checker = SafetyChecker(dialect="sqlserver")
        result = checker._format_table_name("dbo]", "users]")
        assert result == "[dbo]]].[users]]]"

    def test_format_table_name_mysql(self):
        """Test formatting table name for MySQL."""
        checker = SafetyChecker(dialect="mysql")
        result = checker._format_table_name("test", "users")
        assert result == "`test`.`users`"

    def test_format_table_name_mysql_no_schema(self):
        """Test formatting table name for MySQL without schema."""
        checker = SafetyChecker(dialect="mysql")
        result = checker._format_table_name("", "users")
        assert result == "`users`"

    def test_format_table_name_mysql_escape(self):
        """Test formatting table name for MySQL with backticks."""
        checker = SafetyChecker(dialect="mysql")
        result = checker._format_table_name("test`", "users`")
        assert result == "`test```.`users```"

    def test_format_table_name_postgresql_escape(self):
        """Test formatting table name for PostgreSQL with quotes."""
        checker = SafetyChecker(dialect="postgresql")
        result = checker._format_table_name('public"', 'users"')
        assert result == '"public"""."users"""'

    def test_quote_identifier_postgresql(self):
        """Test quoting identifier for PostgreSQL."""
        checker = SafetyChecker(dialect="postgresql")
        result = checker._quote_identifier("users")
        assert result == '"users"'

    def test_quote_identifier_sqlserver(self):
        """Test quoting identifier for SQL Server."""
        checker = SafetyChecker(dialect="sqlserver")
        result = checker._quote_identifier("users")
        assert result == "[users]"

    def test_quote_identifier_mysql(self):
        """Test quoting identifier for MySQL."""
        checker = SafetyChecker(dialect="mysql")
        result = checker._quote_identifier("users")
        assert result == "`users`"

    def test_quote_identifier_escape(self):
        """Test quoting identifier with special characters."""
        checker = SafetyChecker(dialect="postgresql")
        result = checker._quote_identifier('users"')
        assert result == '"users"""'

    def test_normalize_type(self):
        """Test normalizing type string."""
        checker = SafetyChecker()
        assert checker._normalize_type("INTEGER") == "integer"
        assert checker._normalize_type("  VARCHAR(100)  ") == "varchar(100)"

    def test_extract_base_type(self):
        """Test extracting base type."""
        checker = SafetyChecker()
        # _extract_base_type returns the type as-is (case preserved)
        assert checker._extract_base_type("VARCHAR(100)") == "VARCHAR"
        assert checker._extract_base_type("NUMERIC(10,2)") == "NUMERIC"
        assert checker._extract_base_type("INTEGER") == "INTEGER"

    def test_is_size_based_type(self):
        """Test checking if type is size-based."""
        checker = SafetyChecker()
        assert checker._is_size_based_type("VARCHAR") is True
        assert checker._is_size_based_type("CHAR") is True
        assert checker._is_size_based_type("NUMERIC") is False

    def test_is_precision_based_type(self):
        """Test checking if type is precision-based."""
        checker = SafetyChecker()
        assert checker._is_precision_based_type("NUMERIC") is True
        assert checker._is_precision_based_type("DECIMAL") is True
        assert checker._is_precision_based_type("VARCHAR") is False

    def test_extract_size(self):
        """Test extracting size from type."""
        checker = SafetyChecker()
        assert checker._extract_size("VARCHAR(100)") == 100
        assert checker._extract_size("CHAR(50)") == 50
        assert checker._extract_size("NUMERIC(10,2)") is None  # Not size-based
        assert checker._extract_size("INTEGER") is None
        assert checker._extract_size("VARCHAR") is None  # No parentheses

    def test_extract_precision(self):
        """Test extracting precision from type."""
        checker = SafetyChecker()
        assert checker._extract_precision("NUMERIC(10,2)") == (10, 2)
        assert checker._extract_precision("DECIMAL(5,1)") == (5, 1)
        assert checker._extract_precision("NUMERIC(10)") == (10, 0)
        assert checker._extract_precision("VARCHAR(100)") is None  # Not precision-based
        assert checker._extract_precision("INTEGER") is None
        assert checker._extract_precision("NUMERIC") is None  # No parentheses


@pytest.mark.unit
class TestSafetyCheckerFKQueries:
    """Tests for foreign key reference queries."""

    def test_get_fk_reference_query_sqlserver(self):
        """Test FK reference query for SQL Server."""
        checker = SafetyChecker(dialect="sqlserver")
        query, params = checker._get_fk_reference_query("dbo", "users", "id")
        assert query is not None
        assert len(params) == 3
        assert "sys.foreign_keys" in query.lower()

    def test_get_fk_reference_query_postgresql(self):
        """Test FK reference query for PostgreSQL."""
        checker = SafetyChecker(dialect="postgresql")
        query, params = checker._get_fk_reference_query("public", "users", "id")
        assert query is not None
        assert len(params) == 3
        assert "information_schema" in query.lower()

    def test_get_fk_reference_query_mysql(self):
        """Test FK reference query for MySQL."""
        checker = SafetyChecker(dialect="mysql")
        query, params = checker._get_fk_reference_query("test", "users", "id")
        assert query is not None
        assert len(params) == 3
        assert "information_schema" in query.lower()

    def test_get_fk_reference_query_oracle(self):
        """Test FK reference query for Oracle."""
        checker = SafetyChecker(dialect="oracle")
        query, params = checker._get_fk_reference_query("SCHEMA", "users", "id")
        assert query is not None
        assert len(params) == 4
        assert "all_constraints" in query.lower()

    def test_get_fk_reference_query_db2(self):
        """Test FK reference query for DB2."""
        checker = SafetyChecker(dialect="db2")
        query, params = checker._get_fk_reference_query("SCHEMA", "users", "id")
        assert query is not None
        assert len(params) == 3
        assert "syscat.references" in query.lower()

    def test_get_fk_reference_query_unknown(self):
        """Test FK reference query for unknown dialect."""
        checker = SafetyChecker(dialect="unknown")
        query, params = checker._get_fk_reference_query("schema", "users", "id")
        assert query is None
        assert params == []


@pytest.mark.unit
class TestSafetyCheckerIndexQueries:
    """Tests for index reference queries."""

    def test_get_index_reference_query_sqlserver(self):
        """Test index reference query for SQL Server."""
        checker = SafetyChecker(dialect="sqlserver")
        query, params = checker._get_index_reference_query("dbo", "users", "id")
        assert query is not None
        assert len(params) == 3
        assert "sys.indexes" in query.lower()

    def test_get_index_reference_query_postgresql(self):
        """Test index reference query for PostgreSQL."""
        checker = SafetyChecker(dialect="postgresql")
        query, params = checker._get_index_reference_query("public", "users", "id")
        assert query is not None
        assert len(params) == 3
        assert "pg_index" in query.lower()

    def test_get_index_reference_query_mysql(self):
        """Test index reference query for MySQL."""
        checker = SafetyChecker(dialect="mysql")
        query, params = checker._get_index_reference_query("test", "users", "id")
        assert query is not None
        assert len(params) == 3
        assert "information_schema" in query.lower()

    def test_get_index_reference_query_oracle(self):
        """Test index reference query for Oracle."""
        checker = SafetyChecker(dialect="oracle")
        query, params = checker._get_index_reference_query("SCHEMA", "users", "id")
        assert query is not None
        assert len(params) == 3
        assert "all_ind_columns" in query.lower()

    def test_get_index_reference_query_db2(self):
        """Test index reference query for DB2."""
        checker = SafetyChecker(dialect="db2")
        query, params = checker._get_index_reference_query("SCHEMA", "users", "id")
        assert query is not None
        assert len(params) == 3
        assert "syscat.indexcoluse" in query.lower()

    def test_get_index_reference_query_unknown(self):
        """Test index reference query for unknown dialect."""
        checker = SafetyChecker(dialect="unknown")
        query, params = checker._get_index_reference_query("schema", "users", "id")
        assert query is None
        assert params == []


class TestSafetyCheckerQuirksRefactor:
    """Verify SafetyChecker uses quirks system, not hardcoded dispatch dicts."""

    def test_get_default_schema_via_quirks(self):
        import inspect

        from core.sql_generator.safety_checker import SafetyChecker

        src = inspect.getsource(SafetyChecker._get_default_schema)
        assert "postgresql" not in src
        assert "sqlserver" not in src
        assert "dbo" not in src

    def test_format_table_name_mysql_uses_backtick(self):
        from core.sql_generator.safety_checker import SafetyChecker

        checker = SafetyChecker("mysql")
        result = checker._format_table_name("mydb", "orders")
        assert result == "`mydb`.`orders`"

    def test_format_table_name_sqlserver_uses_brackets(self):
        from core.sql_generator.safety_checker import SafetyChecker

        checker = SafetyChecker("sqlserver")
        result = checker._format_table_name("dbo", "orders")
        assert result == "[dbo].[orders]"

    def test_format_table_name_postgresql_uses_double_quotes(self):
        from core.sql_generator.safety_checker import SafetyChecker

        checker = SafetyChecker("postgresql")
        result = checker._format_table_name("public", "orders")
        assert result == '"public"."orders"'

    def test_existence_check_oracle_via_quirks(self):
        from core.sql_generator.safety_checker import SafetyChecker

        checker = SafetyChecker("oracle")
        table_name = '"HR"."EMPLOYEES"'
        sql = checker._quirks.existence_check_sql(table_name)
        assert "ROWNUM" in sql

    def test_fk_query_uses_quirks_not_dispatch_dict(self):
        import inspect

        from core.sql_generator.safety_checker import SafetyChecker

        src = inspect.getsource(SafetyChecker._get_fk_reference_query)
        assert "_FK_REFERENCE_QUERIES" not in src
        assert "quirks" in src

    def test_index_query_uses_quirks_not_dispatch_dict(self):
        import inspect

        from core.sql_generator.safety_checker import SafetyChecker

        src = inspect.getsource(SafetyChecker._get_index_reference_query)
        assert "_INDEX_REFERENCE_QUERIES" not in src
        assert "quirks" in src

    def test_no_dispatch_dict_at_module_level(self):
        import inspect

        from core.sql_generator import safety_checker

        src = inspect.getsource(safety_checker)
        assert "_FK_REFERENCE_QUERIES" not in src
        assert "_INDEX_REFERENCE_QUERIES" not in src
        assert "_EXISTENCE_CHECK_BUILDERS" not in src
        assert "_IDENTIFIER_QUOTE_CHAR" not in src
