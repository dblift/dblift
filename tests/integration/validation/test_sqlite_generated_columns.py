"""
SQLite generated columns validation tests.

Tests introspection and SQL generation for GENERATED ALWAYS AS columns.
SQLite 3.31+ supports both STORED and VIRTUAL generated columns.
"""

import tempfile
from pathlib import Path

import pytest

from config import DbliftConfig
from config.database_config import SQLiteConfig
from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester
from db.plugins.sqlite.provider import SQLiteProvider


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_generated.sqlite"

    yield {
        "type": "sqlite",
        "path": str(db_path),
        "schema": "main",
    }

    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def sqlite_provider(sqlite_test_db):
    """Create SQLite provider for testing."""
    db_config = SQLiteConfig(
        type="sqlite", path=sqlite_test_db["path"], schema=sqlite_test_db["schema"]
    )
    config = DbliftConfig(database=db_config)
    log = ConsoleLog("sqlite_generated_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()
    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLiteGeneratedColumns:
    """SQLite generated columns tests."""

    def test_generated_stored_column_introspection(self, sqlite_provider):
        """Test that STORED generated columns are introspected correctly."""
        # Create table with STORED generated column
        create_sql = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            name_upper TEXT GENERATED ALWAYS AS (UPPER(name)) STORED
        )
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        assert len(tables) == 1
        table = tables[0]
        assert table.name == "products"

        # Find generated column
        name_upper_col = next((c for c in table.columns if c.name == "name_upper"), None)
        assert name_upper_col is not None, "Generated column not found"
        assert name_upper_col.is_computed, "Column should be marked as computed"
        assert name_upper_col.computed_expression == "UPPER(name)"
        assert name_upper_col.computed_stored is True, "Should be STORED"

    def test_generated_virtual_column_introspection(self, sqlite_provider):
        """Test that VIRTUAL generated columns are introspected correctly."""
        # Create table with VIRTUAL generated column
        create_sql = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            full_name TEXT GENERATED ALWAYS AS (first_name || ' ' || last_name) VIRTUAL
        )
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        assert len(tables) == 1
        table = tables[0]

        # Find generated column
        full_name_col = next((c for c in table.columns if c.name == "full_name"), None)
        assert full_name_col is not None, "Generated column not found"
        assert full_name_col.is_computed, "Column should be marked as computed"
        assert "first_name" in full_name_col.computed_expression
        assert "last_name" in full_name_col.computed_expression
        assert full_name_col.computed_stored is False, "Should be VIRTUAL"

    def test_generated_columns_sql_generation(self, sqlite_provider):
        """Test that generated columns are generated correctly in SQL."""
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        # Create table with both STORED and VIRTUAL generated columns
        create_sql = """
        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY,
            quantity INTEGER,
            price REAL,
            total_value REAL GENERATED ALWAYS AS (quantity * price) STORED,
            total_value_virtual REAL GENERATED ALWAYS AS (quantity * price) VIRTUAL
        )
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        # Generate SQL
        generator = SqlGeneratorFactory.create("sqlite")
        sql = generator.generate_create_statement(tables[0])

        # Verify generated columns are in SQL
        assert "GENERATED ALWAYS AS" in sql
        assert "STORED" in sql
        assert "VIRTUAL" in sql
        assert "total_value" in sql
        assert "total_value_virtual" in sql

    def test_generated_columns_round_trip(self, sqlite_provider):
        """Test round-trip preserves generated columns."""
        # Create table with generated columns
        create_sql = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            item_count INTEGER,
            unit_price REAL,
            total_price REAL GENERATED ALWAYS AS (item_count * unit_price) STORED,
            discount REAL GENERATED ALWAYS AS (CASE WHEN total_price > 100 THEN total_price * 0.1 ELSE 0 END) VIRTUAL
        )
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Run round-trip test
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)

        tester = RoundTripTester(
            source_provider=sqlite_provider,
            test_provider=sqlite_provider,
            source_schema="main",
            test_schema="main_test",
            introspector=introspector,
            test_object_types=["tables"],
        )

        results = tester.run_round_trip_test()

        # Verify success
        assert results["success"], f"Round-trip failed. Errors: {results.get('errors', [])}"
        # Note: Generated columns should be preserved, but may have differences
        # in expression formatting (whitespace, etc.)

    def test_generated_columns_complex_expressions(self, sqlite_provider):
        """Test generated columns with complex expressions."""
        # Create table with complex generated column expressions
        create_sql = """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            full_name TEXT GENERATED ALWAYS AS (TRIM(first_name || ' ' || last_name)) STORED,
            email_domain TEXT GENERATED ALWAYS AS (SUBSTR(email, INSTR(email, '@') + 1)) VIRTUAL,
            name_length INTEGER GENERATED ALWAYS AS (LENGTH(first_name) + LENGTH(last_name)) STORED
        )
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        assert len(tables) == 1
        table = tables[0]

        # Verify all generated columns are found
        generated_cols = [c for c in table.columns if getattr(c, "is_computed", False)]
        assert len(generated_cols) == 3, f"Expected 3 generated columns, got {len(generated_cols)}"

        # Verify expressions
        full_name_col = next((c for c in generated_cols if c.name == "full_name"), None)
        assert full_name_col is not None
        assert "TRIM" in full_name_col.computed_expression
        assert full_name_col.computed_stored is True

        email_domain_col = next((c for c in generated_cols if c.name == "email_domain"), None)
        assert email_domain_col is not None
        assert "SUBSTR" in email_domain_col.computed_expression
        assert email_domain_col.computed_stored is False

        name_length_col = next((c for c in generated_cols if c.name == "name_length"), None)
        assert name_length_col is not None
        assert "LENGTH" in name_length_col.computed_expression
