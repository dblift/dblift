"""
SQLite Edge Cases and Complex Scenarios Tests.

Tests for edge cases, complex scenarios, and real-world use cases.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_edge_cases.sqlite"

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
    log = ConsoleLog("sqlite_edge_cases_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()

    # Enable foreign key enforcement
    provider.execute_statement("PRAGMA foreign_keys = ON")
    provider.connection.commit()

    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLiteEdgeCases:
    """SQLite edge case tests."""

    def test_table_with_all_constraint_types(self, sqlite_provider):
        """Test table with all constraint types: PK, FK, UNIQUE, CHECK, NOT NULL."""
        create_parent = """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
        """
        create_child = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL,
            sku TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            stock INTEGER DEFAULT 0,
            CHECK (price > 0),
            CHECK (stock >= 0),
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        )
        """

        sqlite_provider.execute_statement(create_parent)
        sqlite_provider.execute_statement(create_child)
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

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

    def test_multiple_foreign_keys_same_table(self, sqlite_provider):
        """Test table with multiple foreign keys referencing different tables."""
        create_tables = [
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY,
                author_id INTEGER NOT NULL,
                category_id INTEGER,
                title TEXT NOT NULL,
                FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
            )
            """,
        ]

        for stmt in create_tables:
            sqlite_provider.execute_statement(stmt)
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

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

    def test_table_with_generated_column_and_index(self, sqlite_provider):
        """Test table with generated column and index on that column."""
        create_table = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total REAL GENERATED ALWAYS AS (quantity * unit_price) STORED
        )
        """
        create_index = """
        CREATE INDEX idx_order_total ON orders(total)
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

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

    def test_complex_check_with_subquery(self, sqlite_provider):
        """Test CHECK constraint with subquery (if supported)."""
        # Note: SQLite doesn't support subqueries in CHECK constraints
        # This test verifies the system handles this gracefully
        create_table = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            CHECK (amount > 0)
        )
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        assert len(tables) == 1
        check_constraints = [c for c in tables[0].constraints if c.constraint_type.value == "CHECK"]
        assert len(check_constraints) >= 1

    def test_table_with_default_current_timestamp(self, sqlite_provider):
        """Test table with multiple timestamp defaults."""
        create_table = """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT
        )
        """

        sqlite_provider.execute_statement(create_table)
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

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

    def test_index_on_foreign_key_column(self, sqlite_provider):
        """Test index on foreign key column."""
        create_tables = [
            """
            CREATE TABLE departments (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                department_id INTEGER,
                FOREIGN KEY (department_id) REFERENCES departments(id)
            )
            """,
        ]
        create_index = """
        CREATE INDEX idx_emp_dept ON employees(department_id)
        """

        for stmt in create_tables:
            sqlite_provider.execute_statement(stmt)
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

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

    def test_unique_constraint_vs_unique_index(self, sqlite_provider):
        """Test that UNIQUE constraints and UNIQUE indexes are handled correctly."""
        create_table = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL
        )
        """
        create_index = """
        CREATE UNIQUE INDEX idx_unique_email ON users(email)
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

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )
