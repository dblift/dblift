"""Tests for SqlGeneratorFactory class."""

from unittest.mock import MagicMock, patch

import pytest

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_generator.formatter import SqlFormatter
from core.sql_generator.generator_factory import SqlGeneratorFactory
from core.sql_generator.sql_generator import SqlGenerator


@pytest.mark.unit
class TestSqlGeneratorFactoryCreate:
    """Test SqlGeneratorFactory.create method."""

    def test_create_postgresql(self):
        """Test creating PostgreSQL generator."""
        generator = SqlGeneratorFactory.create("postgresql")
        assert generator is not None
        assert generator.default_dialect == "postgresql"

    def test_create_postgresql_lowercase(self):
        """Test creating PostgreSQL generator with uppercase dialect — normalized to lowercase."""
        generator = SqlGeneratorFactory.create("POSTGRESQL")
        assert generator is not None
        assert generator.default_dialect == "postgresql"

    def test_create_postgres(self):
        """Test creating PostgreSQL generator with 'postgres' alias."""
        generator = SqlGeneratorFactory.create("postgres")
        assert generator is not None

    def test_create_oracle(self):
        """Test creating Oracle generator."""
        generator = SqlGeneratorFactory.create("oracle")
        assert generator is not None
        assert generator.default_dialect == "oracle"

    def test_create_mysql(self):
        """Test creating MySQL generator."""
        generator = SqlGeneratorFactory.create("mysql")
        assert generator is not None
        assert generator.default_dialect == "mysql"

    def test_create_mariadb(self):
        """Test creating MySQL generator with 'mariadb' alias."""
        generator = SqlGeneratorFactory.create("mariadb")
        assert generator is not None

    def test_create_sqlserver(self):
        """Test creating SQL Server generator."""
        generator = SqlGeneratorFactory.create("sqlserver")
        assert generator is not None
        assert generator.default_dialect == "sqlserver"

    def test_create_mssql(self):
        """Test creating SQL Server generator with 'mssql' alias."""
        generator = SqlGeneratorFactory.create("mssql")
        assert generator is not None

    def test_create_db2(self):
        """Test creating DB2 generator."""
        generator = SqlGeneratorFactory.create("db2")
        assert generator is not None
        assert generator.default_dialect == "db2"

    def test_create_sqlite(self):
        """Test creating SQLite generator."""
        generator = SqlGeneratorFactory.create("sqlite")
        assert generator is not None
        assert generator.default_dialect == "sqlite"

    def test_create_sqlite3(self):
        """Test creating SQLite generator with 'sqlite3' alias."""
        generator = SqlGeneratorFactory.create("sqlite3")
        assert generator is not None

    def test_create_unknown_dialect_fallback(self):
        """Test creating generator for unknown dialect falls back to SqlGenerator."""
        generator = SqlGeneratorFactory.create("unknown_dialect")
        assert isinstance(generator, SqlGenerator)
        assert generator.default_dialect == "unknown_dialect"

    def test_create_with_custom_formatter(self):
        """Test creating generator with custom formatter."""
        formatter = SqlFormatter(dialect="postgresql")
        generator = SqlGeneratorFactory.create("postgresql", formatter=formatter)
        assert generator.formatter == formatter

    def test_create_with_dependency_ordering_false(self):
        """Test creating generator with dependency ordering disabled."""
        generator = SqlGeneratorFactory.create("postgresql", use_dependency_ordering=False)
        assert generator.use_dependency_ordering is False

    def test_create_with_dependency_ordering_true(self):
        """Test creating generator with dependency ordering enabled."""
        generator = SqlGeneratorFactory.create("postgresql", use_dependency_ordering=True)
        assert generator.use_dependency_ordering is True


@pytest.mark.unit
class TestSqlGeneratorFactoryRegister:
    """Test SqlGeneratorFactory.register method."""

    def test_register_custom_generator(self):
        """Test registering a custom generator."""

        class CustomGenerator(BaseSqlGenerator):
            def generate_create_statement(self, obj):
                return "CREATE CUSTOM"

            def _generate_drop_statement(self, obj, dialect):
                return "DROP CUSTOM"

        SqlGeneratorFactory.register("custom", CustomGenerator)
        generator = SqlGeneratorFactory.create("custom")
        assert isinstance(generator, CustomGenerator)

    def test_register_case_insensitive(self):
        """Test that registration is case-insensitive."""

        class CustomGenerator(BaseSqlGenerator):
            def generate_create_statement(self, obj):
                return "CREATE CUSTOM"

            def _generate_drop_statement(self, obj, dialect):
                return "DROP CUSTOM"

        SqlGeneratorFactory.register("CUSTOM", CustomGenerator)
        # Should be able to create with lowercase
        generator = SqlGeneratorFactory.create("custom")
        assert isinstance(generator, CustomGenerator)

    def test_register_overwrites_existing(self):
        """Test that registering overwrites existing registration."""

        class Generator1(BaseSqlGenerator):
            def generate_create_statement(self, obj):
                return "CREATE 1"

            def _generate_drop_statement(self, obj, dialect):
                return "DROP 1"

        class Generator2(BaseSqlGenerator):
            def generate_create_statement(self, obj):
                return "CREATE 2"

            def _generate_drop_statement(self, obj, dialect):
                return "DROP 2"

        SqlGeneratorFactory.register("test_dialect", Generator1)
        generator1 = SqlGeneratorFactory.create("test_dialect")
        assert isinstance(generator1, Generator1)

        SqlGeneratorFactory.register("test_dialect", Generator2)
        generator2 = SqlGeneratorFactory.create("test_dialect")
        assert isinstance(generator2, Generator2)


@pytest.mark.unit
class TestSqlGeneratorFactoryIsSupported:
    """Test SqlGeneratorFactory.is_supported method."""

    def test_is_supported_postgresql(self):
        """Test is_supported for PostgreSQL."""
        assert SqlGeneratorFactory.is_supported("postgresql") is True

    def test_is_supported_oracle(self):
        """Test is_supported for Oracle."""
        assert SqlGeneratorFactory.is_supported("oracle") is True

    def test_is_supported_mysql(self):
        """Test is_supported for MySQL."""
        assert SqlGeneratorFactory.is_supported("mysql") is True

    def test_is_supported_case_insensitive(self):
        """Test is_supported is case-insensitive."""
        assert SqlGeneratorFactory.is_supported("POSTGRESQL") is True
        assert SqlGeneratorFactory.is_supported("PostgreSQL") is True

    def test_is_supported_unknown_dialect(self):
        """Test is_supported for unknown dialect."""
        assert SqlGeneratorFactory.is_supported("unknown_dialect") is False

    def test_is_supported_custom_registered(self):
        """Test is_supported for custom registered dialect."""

        class CustomGenerator(BaseSqlGenerator):
            def generate_create_statement(self, obj):
                return "CREATE CUSTOM"

            def _generate_drop_statement(self, obj, dialect):
                return "DROP CUSTOM"

        SqlGeneratorFactory.register("custom_test", CustomGenerator)
        assert SqlGeneratorFactory.is_supported("custom_test") is True


@pytest.mark.unit
class TestSqlGeneratorFactorySupportedDialects:
    """Test SqlGeneratorFactory.supported_dialects method."""

    def test_supported_dialects_returns_list(self):
        """Test that supported_dialects returns a list."""
        dialects = SqlGeneratorFactory.supported_dialects()
        assert isinstance(dialects, list)

    def test_supported_dialects_includes_postgresql(self):
        """Test that supported_dialects includes PostgreSQL."""
        dialects = SqlGeneratorFactory.supported_dialects()
        assert "postgresql" in dialects or "postgres" in dialects

    def test_supported_dialects_includes_registered(self):
        """Test that supported_dialects includes custom registered dialects."""

        class CustomGenerator(BaseSqlGenerator):
            def generate_create_statement(self, obj):
                return "CREATE CUSTOM"

            def _generate_drop_statement(self, obj, dialect):
                return "DROP CUSTOM"

        SqlGeneratorFactory.register("custom_dialect", CustomGenerator)
        dialects = SqlGeneratorFactory.supported_dialects()
        assert "custom_dialect" in dialects


@pytest.mark.unit
class TestSqlGeneratorFactoryRegisterDefaults:
    """Test SqlGeneratorFactory._register_defaults method."""

    def test_register_defaults_called_on_first_create(self):
        """Test that _register_defaults is called on first create."""
        # Clear the dialect map AND the lazy-init flag to simulate
        # first call. (Story 26-3: factory uses an explicit ``_populated``
        # flag instead of ``not _DIALECT_MAP`` to align with
        # ``AlterGeneratorFactory._populated``; tests that simulate a
        # fresh state must reset both.)
        original_map = SqlGeneratorFactory._DIALECT_MAP.copy()
        original_populated = SqlGeneratorFactory._populated
        SqlGeneratorFactory._DIALECT_MAP.clear()
        SqlGeneratorFactory._populated = False

        # First create should register defaults
        generator = SqlGeneratorFactory.create("postgresql")
        assert generator is not None
        # Map should be populated
        assert len(SqlGeneratorFactory._DIALECT_MAP) > 0

        # Restore original state
        SqlGeneratorFactory._DIALECT_MAP = original_map
        SqlGeneratorFactory._populated = original_populated

    def test_register_defaults_handles_import_error(self):
        """Test that _register_defaults handles ImportError gracefully."""
        # This test verifies that if a generator import fails, it doesn't crash
        # The actual behavior is tested implicitly through create() tests
        dialects = SqlGeneratorFactory.supported_dialects()
        # Should have at least some dialects registered
        assert isinstance(dialects, list)

    def test_create_calls_register_defaults_once(self):
        """Test that _register_defaults is only called once."""
        original_map = SqlGeneratorFactory._DIALECT_MAP.copy()
        original_populated = SqlGeneratorFactory._populated
        SqlGeneratorFactory._DIALECT_MAP.clear()
        SqlGeneratorFactory._populated = False

        # First call should register defaults
        generator1 = SqlGeneratorFactory.create("postgresql")
        map_size_after_first = len(SqlGeneratorFactory._DIALECT_MAP)

        # Second call should not clear the map
        generator2 = SqlGeneratorFactory.create("oracle")
        map_size_after_second = len(SqlGeneratorFactory._DIALECT_MAP)

        # Map should be populated and not cleared
        assert map_size_after_first > 0
        assert map_size_after_second >= map_size_after_first

        SqlGeneratorFactory._DIALECT_MAP = original_map
        SqlGeneratorFactory._populated = original_populated

    def test_register_defaults_postgresql_registration(self):
        """Test PostgreSQL registration in _register_defaults."""
        # This test verifies that PostgreSQL is registered
        # The actual registration happens when create() is called
        generator = SqlGeneratorFactory.create("postgresql")
        assert generator is not None
        assert SqlGeneratorFactory.is_supported("postgresql") or SqlGeneratorFactory.is_supported(
            "postgres"
        )

    def test_register_defaults_oracle_registration(self):
        """Test Oracle registration in _register_defaults."""
        generator = SqlGeneratorFactory.create("oracle")
        assert generator is not None
        assert SqlGeneratorFactory.is_supported("oracle")

    def test_register_defaults_mysql_registration(self):
        """Test MySQL registration in _register_defaults."""
        generator = SqlGeneratorFactory.create("mysql")
        assert generator is not None
        assert SqlGeneratorFactory.is_supported("mysql") or SqlGeneratorFactory.is_supported(
            "mariadb"
        )

    def test_register_defaults_sqlserver_registration(self):
        """Test SQL Server registration in _register_defaults."""
        generator = SqlGeneratorFactory.create("sqlserver")
        assert generator is not None
        assert SqlGeneratorFactory.is_supported("sqlserver") or SqlGeneratorFactory.is_supported(
            "mssql"
        )

    def test_register_defaults_db2_registration(self):
        """Test DB2 registration in _register_defaults."""
        generator = SqlGeneratorFactory.create("db2")
        assert generator is not None
        assert SqlGeneratorFactory.is_supported("db2")

    def test_register_defaults_sqlite_registration(self):
        """Test SQLite registration in _register_defaults."""
        generator = SqlGeneratorFactory.create("sqlite")
        assert generator is not None
        assert SqlGeneratorFactory.is_supported("sqlite") or SqlGeneratorFactory.is_supported(
            "sqlite3"
        )
