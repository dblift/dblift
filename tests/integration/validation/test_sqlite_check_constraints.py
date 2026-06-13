"""
SQLite CHECK Constraint Tests.

Comprehensive tests for CHECK constraints including complex expressions, named constraints, and round-trip validation.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_check.sqlite"

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
    log = ConsoleLog("sqlite_check_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()
    provider.connection.commit()

    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLiteCheckConstraints:
    """SQLite CHECK constraint tests."""

    def test_named_check_constraint(self, sqlite_provider):
        """Test that named CHECK constraints are extracted correctly."""
        create_sql = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL,
            CONSTRAINT chk_positive_price CHECK (price > 0),
            CONSTRAINT chk_name_length CHECK (length(name) > 0 AND length(name) <= 100)
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
        check_constraints = [c for c in table.constraints if c.constraint_type.value == "CHECK"]

        assert len(check_constraints) >= 2
        # Verify named constraints
        named_constraints = [c for c in check_constraints if c.name]
        assert len(named_constraints) >= 2

    def test_complex_check_expression(self, sqlite_provider):
        """Test CHECK constraints with complex expressions."""
        create_sql = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            quantity INTEGER,
            unit_price REAL,
            discount REAL,
            total REAL,
            CHECK (quantity > 0),
            CHECK (unit_price >= 0),
            CHECK (discount >= 0 AND discount <= 1),
            CHECK (total = quantity * unit_price * (1 - discount))
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
        check_constraints = [c for c in table.constraints if c.constraint_type.value == "CHECK"]

        # Should have at least 4 CHECK constraints
        assert len(check_constraints) >= 4

    def test_check_with_functions(self, sqlite_provider):
        """Test CHECK constraints using SQLite functions."""
        create_sql = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email TEXT,
            age INTEGER,
            created_at TEXT,
            CHECK (email LIKE '%@%'),
            CHECK (length(email) > 5),
            CHECK (age >= 0 AND age < 150),
            CHECK (datetime(created_at) IS NOT NULL OR created_at IS NULL)
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
        check_constraints = [c for c in table.constraints if c.constraint_type.value == "CHECK"]

        # Should have multiple CHECK constraints
        assert len(check_constraints) >= 3

    def test_check_constraint_round_trip(self, sqlite_provider):
        """Test that CHECK constraints are preserved in round-trip."""
        create_sql = """
        CREATE TABLE inventory (
            id INTEGER PRIMARY KEY,
            item_name TEXT NOT NULL,
            quantity INTEGER,
            price REAL,
            status TEXT,
            CHECK (quantity >= 0),
            CHECK (price > 0),
            CHECK (status IN ('in_stock', 'out_of_stock', 'discontinued'))
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

        # Verify success (CHECK constraints should be preserved)
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

    def test_multi_column_check_constraint(self, sqlite_provider):
        """Test CHECK constraints involving multiple columns."""
        create_sql = """
        CREATE TABLE reservations (
            id INTEGER PRIMARY KEY,
            check_in TEXT NOT NULL,
            check_out TEXT NOT NULL,
            guests INTEGER,
            CHECK (datetime(check_in) < datetime(check_out)),
            CHECK (guests > 0 AND guests <= 10)
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
        check_constraints = [c for c in table.constraints if c.constraint_type.value == "CHECK"]

        # Should have CHECK constraints
        assert len(check_constraints) >= 2
