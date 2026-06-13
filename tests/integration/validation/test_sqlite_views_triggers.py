"""
SQLite Views and Triggers Tests.

Comprehensive tests for views (including complex queries) and triggers.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_views_triggers.sqlite"

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
    log = ConsoleLog("sqlite_views_triggers_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()
    provider.connection.commit()

    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLiteViews:
    """SQLite view tests."""

    def test_simple_view(self, sqlite_provider):
        """Test simple view creation and introspection."""
        create_table = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT
        )
        """
        create_view = """
        CREATE VIEW active_users AS
        SELECT id, name, email
        FROM users
        WHERE email IS NOT NULL
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_view)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        views = introspector.get_views("main")

        assert len(views) == 1
        assert views[0].name == "active_users"
        assert "SELECT" in views[0].query.upper()

    def test_view_with_join(self, sqlite_provider):
        """Test view with JOIN."""
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
        create_view = """
        CREATE VIEW employee_departments AS
        SELECT e.id, e.name, d.name AS department_name
        FROM employees e
        LEFT JOIN departments d ON e.department_id = d.id
        """

        for stmt in create_tables:
            sqlite_provider.execute_statement(stmt)
        sqlite_provider.execute_statement(create_view)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        views = introspector.get_views("main")

        assert len(views) == 1
        assert views[0].name == "employee_departments"

    def test_view_with_aggregation(self, sqlite_provider):
        """Test view with aggregation functions."""
        create_table = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            amount REAL,
            order_date TEXT
        )
        """
        create_view = """
        CREATE VIEW customer_totals AS
        SELECT 
            customer_id,
            COUNT(*) AS order_count,
            SUM(amount) AS total_amount,
            AVG(amount) AS avg_amount
        FROM orders
        GROUP BY customer_id
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_view)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        views = introspector.get_views("main")

        assert len(views) == 1
        assert views[0].name == "customer_totals"

    def test_view_round_trip(self, sqlite_provider):
        """Test that views are preserved in round-trip."""
        create_table = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL,
            category TEXT
        )
        """
        create_view = """
        CREATE VIEW expensive_products AS
        SELECT id, name, price
        FROM products
        WHERE price > 100
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_view)
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
            test_object_types=["tables", "views"],
        )

        results = tester.run_round_trip_test()

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('views', {}).get('differences', [])}"
        )
        assert results["views"]["original_count"] == 1


@pytest.mark.integration
class TestSQLiteTriggers:
    """SQLite trigger tests."""

    def test_after_insert_trigger(self, sqlite_provider):
        """Test AFTER INSERT trigger."""
        create_table = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT
        )
        """
        create_trigger = """
        CREATE TRIGGER set_created_at
        AFTER INSERT ON users
        BEGIN
            UPDATE users SET created_at = datetime('now') WHERE id = NEW.id;
        END
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_trigger)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        triggers = introspector.get_triggers("main", "users")

        assert len(triggers) == 1
        assert triggers[0].name == "set_created_at"
        assert triggers[0].timing == "AFTER"
        assert "INSERT" in triggers[0].events

    def test_before_update_trigger(self, sqlite_provider):
        """Test BEFORE UPDATE trigger."""
        create_table = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL,
            last_modified TEXT
        )
        """
        create_trigger = """
        CREATE TRIGGER update_timestamp
        BEFORE UPDATE ON products
        BEGIN
            UPDATE products SET last_modified = datetime('now') WHERE id = NEW.id;
        END
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_trigger)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        triggers = introspector.get_triggers("main", "products")

        assert len(triggers) == 1
        assert triggers[0].name == "update_timestamp"
        assert triggers[0].timing == "BEFORE"
        assert "UPDATE" in triggers[0].events

    def test_trigger_with_when_clause(self, sqlite_provider):
        """Test trigger with WHEN clause."""
        create_table = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            status TEXT,
            amount REAL
        )
        """
        create_trigger = """
        CREATE TRIGGER log_high_value_orders
        AFTER INSERT ON orders
        WHEN NEW.amount > 1000
        BEGIN
            INSERT INTO order_log (order_id, message) VALUES (NEW.id, 'High value order');
        END
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_trigger)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        triggers = introspector.get_triggers("main", "orders")

        assert len(triggers) == 1
        assert triggers[0].name == "log_high_value_orders"

    def test_trigger_round_trip(self, sqlite_provider):
        """Test that triggers are preserved in round-trip."""
        create_table = """
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY,
            table_name TEXT,
            action TEXT,
            timestamp TEXT
        )
        """
        create_trigger = """
        CREATE TRIGGER audit_users_insert
        AFTER INSERT ON users
        BEGIN
            INSERT INTO audit_log (table_name, action, timestamp)
            VALUES ('users', 'INSERT', datetime('now'));
        END
        """
        # Need users table for the trigger
        create_users = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
        """

        sqlite_provider.execute_statement(create_table)
        sqlite_provider.execute_statement(create_users)
        sqlite_provider.execute_statement(create_trigger)
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
            test_object_types=["tables", "triggers"],
        )

        results = tester.run_round_trip_test()

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('triggers', {}).get('differences', [])}"
        )
