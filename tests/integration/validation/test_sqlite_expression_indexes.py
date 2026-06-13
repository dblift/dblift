"""
SQLite expression indexes validation tests.

Tests introspection and SQL generation for expression indexes.
SQLite supports indexes on expressions like LOWER(name), LENGTH(email), etc.
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
    db_path = tmp_path / "test_expression_indexes.sqlite"

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
    log = ConsoleLog("sqlite_expression_index_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()
    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLiteExpressionIndexes:
    """SQLite expression indexes tests."""

    def test_lower_expression_index_introspection(self, sqlite_provider):
        """Test that LOWER() expression indexes are introspected correctly."""
        # Create table and index
        create_table_sql = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT
        )
        """
        create_index_sql = "CREATE INDEX idx_name_lower ON users(LOWER(name))"

        sqlite_provider.execute_statement(create_table_sql)
        sqlite_provider.execute_statement(create_index_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        indexes = introspector.get_indexes("main", "users")

        assert len(indexes) == 1
        index = indexes[0]
        assert index.name == "idx_name_lower"
        assert len(index.columns) == 1
        assert "LOWER" in index.columns[0] or "lower" in index.columns[0].lower()
        # Expression flag should be set
        assert index.expression_flags[0] is True

    def test_substr_expression_index_introspection(self, sqlite_provider):
        """Test that SUBSTR() expression indexes are introspected correctly."""
        # Create table and index
        create_table_sql = """
        CREATE TABLE emails (
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL
        )
        """
        create_index_sql = (
            'CREATE INDEX idx_email_domain ON emails(SUBSTR(email, INSTR(email, "@") + 1))'
        )

        sqlite_provider.execute_statement(create_table_sql)
        sqlite_provider.execute_statement(create_index_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        indexes = introspector.get_indexes("main", "emails")

        assert len(indexes) == 1
        index = indexes[0]
        assert index.name == "idx_email_domain"
        assert "SUBSTR" in index.columns[0] or "substr" in index.columns[0].lower()
        assert index.expression_flags[0] is True

    def test_arithmetic_expression_index_introspection(self, sqlite_provider):
        """Test that arithmetic expression indexes are introspected correctly."""
        # Create table and index
        create_table_sql = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            quantity INTEGER,
            unit_price REAL
        )
        """
        create_index_sql = "CREATE INDEX idx_total ON orders(quantity * unit_price)"

        sqlite_provider.execute_statement(create_table_sql)
        sqlite_provider.execute_statement(create_index_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        indexes = introspector.get_indexes("main", "orders")

        assert len(indexes) == 1
        index = indexes[0]
        assert index.name == "idx_total"
        assert "*" in index.columns[0]
        assert index.expression_flags[0] is True

    def test_expression_index_sql_generation(self, sqlite_provider):
        """Test that expression indexes are generated correctly in SQL."""
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        # Create table and expression index
        create_table_sql = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT,
            price REAL
        )
        """
        create_index_sql = "CREATE INDEX idx_name_lower ON products(LOWER(name))"

        sqlite_provider.execute_statement(create_table_sql)
        sqlite_provider.execute_statement(create_index_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        indexes = introspector.get_indexes("main", "products")

        # Generate SQL
        generator = SqlGeneratorFactory.create("sqlite")
        sql = generator.generate_create_statement(indexes[0])

        # Verify expression is in SQL (not quoted)
        assert "LOWER(name)" in sql
        assert '"LOWER(name)"' not in sql  # Should not be quoted

    def test_expression_index_round_trip(self, sqlite_provider):
        """Test round-trip preserves expression indexes."""
        # Create table and expression index
        create_table_sql = """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            email TEXT
        )
        """
        create_index_sql = (
            "CREATE INDEX idx_full_name ON customers(LOWER(first_name || ' ' || last_name))"
        )

        sqlite_provider.execute_statement(create_table_sql)
        sqlite_provider.execute_statement(create_index_sql)
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
            test_object_types=["tables", "indexes"],  # Need tables for indexes
        )

        results = tester.run_round_trip_test()

        # Verify success
        assert results["success"], f"Round-trip failed. Errors: {results.get('errors', [])}"
        # Expression indexes should be preserved
        assert results["indexes"]["original_count"] == 1
        assert results["indexes"].get("reintrospected_count", 0) == 1

    def test_mixed_column_and_expression_indexes(self, sqlite_provider):
        """Test tables with both regular and expression indexes."""
        # Create table with multiple indexes
        create_table_sql = """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            name TEXT,
            category TEXT,
            price REAL
        )
        """
        create_indexes = [
            "CREATE INDEX idx_category ON items(category)",  # Regular index
            "CREATE INDEX idx_name_lower ON items(LOWER(name))",  # Expression index
            "CREATE INDEX idx_price_high ON items(price) WHERE price > 100",  # Partial index
        ]

        sqlite_provider.execute_statement(create_table_sql)
        for idx_sql in create_indexes:
            sqlite_provider.execute_statement(idx_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        indexes = introspector.get_indexes("main", "items")

        assert len(indexes) == 3

        # Find expression index
        expr_index = next((idx for idx in indexes if "LOWER" in idx.columns[0]), None)
        assert expr_index is not None
        assert expr_index.expression_flags[0] is True

        # Find regular index
        regular_index = next((idx for idx in indexes if idx.name == "idx_category"), None)
        assert regular_index is not None
        assert regular_index.expression_flags[0] is False
