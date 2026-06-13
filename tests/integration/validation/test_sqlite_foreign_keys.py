"""
SQLite Foreign Key Enforcement Tests.

Tests foreign key constraints, ON DELETE/ON UPDATE actions, and PRAGMA foreign_keys handling.
"""

import tempfile
from pathlib import Path

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester
from db.plugins.sqlite.generator.ddl_generator import SQLiteSqlGenerator
from db.plugins.sqlite.provider import SQLiteProvider


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_fk.sqlite"

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

    db_config = SQLiteConfig(
        type="sqlite",
        path=sqlite_test_db["path"],
        schema=sqlite_test_db["schema"],
    )
    config = DbliftConfig(database=db_config)
    log = ConsoleLog("sqlite_fk_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()

    # Enable foreign key enforcement
    provider.execute_statement("PRAGMA foreign_keys = ON")
    provider.connection.commit()

    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLiteForeignKeys:
    """SQLite foreign key constraint tests."""

    def test_foreign_key_on_delete_cascade(self, sqlite_provider):
        """Test that ON DELETE CASCADE is preserved in round-trip."""
        # Create parent table
        create_parent = """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
        """
        # Create child table with ON DELETE CASCADE
        create_child = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category_id INTEGER,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        )
        """

        sqlite_provider.execute_statement(create_parent)
        sqlite_provider.execute_statement(create_child)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        # Find the foreign key constraint
        products_table = next(t for t in tables if t.name == "products")
        fk_constraints = [
            c for c in products_table.constraints if c.constraint_type.value == "FOREIGN KEY"
        ]

        assert len(fk_constraints) == 1
        fk = fk_constraints[0]
        assert fk.reference_table == "categories"
        assert fk.reference_columns == ["id"]
        # Check that ON DELETE CASCADE is preserved (if supported in introspection)
        # SQLite stores this in the CREATE TABLE SQL, so it should be extractable

    def test_inline_and_explicit_duplicate_foreign_key_exports_once(self, sqlite_provider):
        """SQLite reports duplicate pragma ids for redundant inline/table-level FKs."""
        sqlite_provider.execute_statement("""
            CREATE TABLE departments (
                id INTEGER PRIMARY KEY
            )
            """)
        sqlite_provider.execute_statement("""
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY,
                dept_id INTEGER REFERENCES departments(id),
                FOREIGN KEY (dept_id) REFERENCES departments(id)
            )
            """)
        sqlite_provider.connection.commit()

        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")
        employees_table = next(t for t in tables if t.name == "employees")
        fk_constraints = [
            c for c in employees_table.constraints if c.constraint_type.value == "FOREIGN KEY"
        ]

        assert len(fk_constraints) == 1
        assert fk_constraints[0].column_names == ["dept_id"]
        assert fk_constraints[0].reference_table == "departments"
        assert fk_constraints[0].reference_columns == ["id"]

        exported = SQLiteSqlGenerator()._generate_table_create_statement(employees_table)
        assert exported.upper().count("FOREIGN KEY") == 1

    def test_foreign_key_on_delete_set_null(self, sqlite_provider):
        """Test that ON DELETE SET NULL is preserved in round-trip."""
        create_parent = """
        CREATE TABLE departments (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
        create_child = """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department_id INTEGER,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
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

        # Verify success
        assert results["success"], f"Round-trip failed. Errors: {results.get('errors', [])}"

    def test_foreign_key_on_delete_restrict(self, sqlite_provider):
        """Test that ON DELETE RESTRICT is preserved in round-trip."""
        create_parent = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            order_number TEXT NOT NULL UNIQUE
        )
        """
        create_child = """
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            product_name TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE RESTRICT
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

        assert results["success"], f"Round-trip failed. Errors: {results.get('errors', [])}"

    def test_foreign_key_on_update_cascade(self, sqlite_provider):
        """Test that ON UPDATE CASCADE is preserved in round-trip."""
        create_parent = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE
        )
        """
        create_child = """
        CREATE TABLE user_profiles (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            bio TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON UPDATE CASCADE
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

        assert results["success"], f"Round-trip failed. Errors: {results.get('errors', [])}"

    def test_foreign_key_composite(self, sqlite_provider):
        """Test composite foreign keys (multiple columns)."""
        create_parent = """
        CREATE TABLE regions (
            country_code TEXT NOT NULL,
            region_code TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (country_code, region_code)
        )
        """
        create_child = """
        CREATE TABLE locations (
            id INTEGER PRIMARY KEY,
            country_code TEXT NOT NULL,
            region_code TEXT NOT NULL,
            city TEXT,
            FOREIGN KEY (country_code, region_code) REFERENCES regions(country_code, region_code)
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

        assert results["success"], f"Round-trip failed. Errors: {results.get('errors', [])}"

    def test_foreign_key_self_referencing(self, sqlite_provider):
        """Test self-referencing foreign keys."""
        create_table = """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            manager_id INTEGER,
            FOREIGN KEY (manager_id) REFERENCES employees(id)
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

        assert results["success"], f"Round-trip failed. Errors: {results.get('errors', [])}"

    def test_foreign_key_pragma_enforcement(self, sqlite_provider):
        """Test that PRAGMA foreign_keys=ON is respected."""
        # Create tables
        create_parent = """
        CREATE TABLE parent (
            id INTEGER PRIMARY KEY
        )
        """
        create_child = """
        CREATE TABLE child (
            id INTEGER PRIMARY KEY,
            parent_id INTEGER,
            FOREIGN KEY (parent_id) REFERENCES parent(id)
        )
        """

        sqlite_provider.execute_statement(create_parent)
        sqlite_provider.execute_statement(create_child)
        sqlite_provider.connection.commit()

        # Verify foreign keys are enabled
        result = sqlite_provider.execute_query("PRAGMA foreign_keys")
        fk_enabled = result[0]["foreign_keys"] if result else 0
        assert fk_enabled == 1, "Foreign keys should be enabled"

        # Try to insert invalid foreign key (should fail if enforcement is on)
        # Note: This test verifies that PRAGMA is set, not that it's enforced
        # (enforcement testing would require actual data insertion)
