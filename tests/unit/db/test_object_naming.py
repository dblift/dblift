"""Tests for db.object_naming module."""

import pytest

from db.object_naming import get_normalized_object_name, normalized_quoted_identifier


@pytest.mark.unit
class TestNormalizedQuotedIdentifier:
    """normalize-to-dialect-case then quote, for driver-cased identifiers."""

    def test_oracle_uppercases_then_quotes(self):
        # Driver-cased lowercase 'id' must become the DB-cased quoted "ID" so the
        # emitted SQL targets the real Oracle column (else ORA-00904).
        assert normalized_quoted_identifier("id", "oracle") == '"ID"'

    def test_postgresql_lowercase_quoted(self):
        assert normalized_quoted_identifier("id", "postgresql") == '"id"'

    def test_sqlserver_uses_brackets(self):
        assert normalized_quoted_identifier("id", "sqlserver") == "[id]"


@pytest.mark.unit
class TestGetNormalizedObjectName:
    """Test get_normalized_object_name function."""

    def test_oracle_uppercase(self):
        """Test Oracle returns UPPERCASE."""
        result = get_normalized_object_name("dblift_schema_history", "oracle")
        assert result == "DBLIFT_SCHEMA_HISTORY"

    def test_db2_uppercase(self):
        """Test DB2 returns UPPERCASE."""
        result = get_normalized_object_name("dblift_schema_history", "db2")
        assert result == "DBLIFT_SCHEMA_HISTORY"

    def test_postgresql_lowercase(self):
        """Test PostgreSQL returns lowercase."""
        result = get_normalized_object_name("DBLIFT_SCHEMA_HISTORY", "postgresql")
        assert result == "dblift_schema_history"

    def test_sqlserver_lowercase(self):
        """Test SQL Server returns lowercase."""
        result = get_normalized_object_name("DBLIFT_SCHEMA_HISTORY", "sqlserver")
        assert result == "dblift_schema_history"

    def test_mysql_lowercase(self):
        """Test MySQL returns lowercase."""
        result = get_normalized_object_name("DBLIFT_SCHEMA_HISTORY", "mysql")
        assert result == "dblift_schema_history"

    def test_sqlite_lowercase(self):
        """Test SQLite returns lowercase."""
        result = get_normalized_object_name("DBLIFT_SCHEMA_HISTORY", "sqlite")
        assert result == "dblift_schema_history"

    def test_cosmosdb_lowercase(self):
        """Test CosmosDB returns lowercase."""
        result = get_normalized_object_name("DBLIFT_SCHEMA_HISTORY", "cosmosdb")
        assert result == "dblift_schema_history"

    def test_case_insensitive_dialect(self):
        """Test dialect matching is case-insensitive."""
        assert get_normalized_object_name("test", "ORACLE") == "TEST"
        assert get_normalized_object_name("test", "Oracle") == "TEST"
        assert get_normalized_object_name("test", "DB2") == "TEST"
        assert get_normalized_object_name("TEST", "PostgreSQL") == "test"

    def test_empty_dialect_defaults_to_lowercase(self):
        """Test empty dialect returns lowercase."""
        result = get_normalized_object_name("TEST", "")
        assert result == "test"

    def test_none_dialect_defaults_to_lowercase(self):
        """Test None dialect returns lowercase."""
        result = get_normalized_object_name("TEST", None)  # type: ignore
        assert result == "test"

    def test_unknown_dialect_defaults_to_lowercase(self):
        """Test unknown dialect returns lowercase."""
        result = get_normalized_object_name("TEST", "unknown_db")
        assert result == "test"

    def test_mixed_case_input_oracle(self):
        """Test mixed case input with Oracle."""
        result = get_normalized_object_name("Dblift_Schema_History", "oracle")
        assert result == "DBLIFT_SCHEMA_HISTORY"

    def test_mixed_case_input_postgresql(self):
        """Test mixed case input with PostgreSQL."""
        result = get_normalized_object_name("Dblift_Schema_History", "postgresql")
        assert result == "dblift_schema_history"


@pytest.mark.unit
class TestCaseDerivedFromQuirks:
    """The identifier case is sourced from the dialect's quirks
    (``unquoted_identifier_case``), not a hardcoded dialect list."""

    def test_uppercase_quirk_dialect_upper(self):
        """A dialect whose quirks report 'uppercase' upper-cases the name."""
        # oracle quirks -> unquoted_identifier_case == "uppercase"
        assert get_normalized_object_name("Tbl", "oracle") == "TBL"

    def test_case_insensitive_quirk_dialect_lower(self):
        """A 'case_insensitive' quirk falls through to lowercase."""
        # sqlserver quirks -> unquoted_identifier_case == "case_insensitive"
        assert get_normalized_object_name("Tbl", "sqlserver") == "tbl"

    def test_none_dialect_lower(self):
        """No dialect short-circuits to lowercase without touching quirks."""
        assert get_normalized_object_name("Tbl", None) == "tbl"  # type: ignore[arg-type]

    def test_case_matches_registry_quirks_for_all_dialects(self):
        """Casing for every known dialect follows its quirks, not a literal set."""
        from db.provider_registry import ProviderRegistry

        for dialect in (
            "oracle",
            "db2",
            "postgresql",
            "sqlserver",
            "mysql",
            "sqlite",
            "cosmosdb",
        ):
            case = ProviderRegistry.get_quirks(dialect).unquoted_identifier_case
            expected = "ABC" if case == "uppercase" else "abc"
            assert get_normalized_object_name("AbC", dialect) == expected

    def test_no_hardcoded_dialect_sets(self):
        """The hardcoded dialect frozensets must not exist on the module."""
        from db import object_naming

        assert not hasattr(object_naming, "UPPERCASE_DIALECTS")
        assert not hasattr(object_naming, "LOWERCASE_DIALECTS")
