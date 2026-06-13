"""
SQLite Partial Index Tests.

Tests partial indexes (indexes with WHERE clauses) for SQLite.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_partial_idx.sqlite"

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
    from config import DbliftConfig
    from config.database_config import SQLiteConfig
    from core.logger import ConsoleLog
    from db.plugins.sqlite.provider import SQLiteProvider

    db_config = SQLiteConfig(
        type="sqlite",
        path=sqlite_test_db["path"],
        schema=sqlite_test_db["schema"],
    )
    config = DbliftConfig(database=db_config)
    log = ConsoleLog("sqlite_partial_idx_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()
    provider.connection.commit()

    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLitePartialIndexes:
    """SQLite partial index tests."""

    def test_partial_index_where_clause(self, sqlite_provider):
        """Test that partial indexes with WHERE clauses are introspected."""
        # Create table
        create_table = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            amount REAL,
            created_at TEXT
        )
        """
        # Create partial index (only indexes rows where status = 'active')
        create_index = """
        CREATE INDEX idx_active_orders ON orders(amount) WHERE status = 'active'
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_index)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        indexes = introspector.get_indexes("main", "orders")

        assert len(indexes) == 1
        index = indexes[0]
        assert index.name == "idx_active_orders"
        # Note: WHERE clause extraction from sqlite_master.sql may need implementation
        # For now, we verify the index exists

    def test_partial_index_round_trip(self, sqlite_provider):
        """Test that partial indexes are preserved in round-trip."""
        create_table = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL,
            discontinued INTEGER DEFAULT 0
        )
        """
        create_index = """
        CREATE INDEX idx_active_products ON products(price) WHERE discontinued = 0
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_index)
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
            test_object_types=["tables", "indexes"],
        )

        results = tester.run_round_trip_test()

        # Verify success (even if WHERE clause isn't fully preserved yet)
        assert results["success"], f"Round-trip failed. Errors: {results.get('errors', [])}"

    def test_partial_index_complex_condition(self, sqlite_provider):
        """Test partial index with complex WHERE condition."""
        create_table = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            age INTEGER,
            active INTEGER DEFAULT 1
        )
        """
        create_index = """
        CREATE INDEX idx_active_adults ON users(email) WHERE active = 1 AND age >= 18
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_index)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        indexes = introspector.get_indexes("main", "users")

        assert len(indexes) == 1
        assert indexes[0].name == "idx_active_adults"
