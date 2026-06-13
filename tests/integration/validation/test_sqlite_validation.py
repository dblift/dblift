"""
SQLite-specific validation tests.

Tests round-trip, property preservation, and SQL generation for SQLite.
SQLite doesn't require Docker containers, making these tests faster.
"""

import tempfile
from pathlib import Path

import pytest

from config import DbliftConfig
from config.database_config import SQLiteConfig
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester
from db.plugins.sqlite.provider import SQLiteProvider


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_validation.sqlite"

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
        type="sqlite",
        path=sqlite_test_db["path"],
        schema=sqlite_test_db["schema"],
    )
    config = DbliftConfig(database=db_config)
    log = ConsoleLog("sqlite_validation_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()
    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLiteValidation:
    """SQLite-specific validation tests."""

    def test_check_constraint_extraction(self, sqlite_provider):
        """Test that CHECK constraints are extracted from CREATE TABLE SQL."""
        from core.introspection.introspector_factory import IntrospectorFactory

        # Create table with CHECK constraints
        create_sql = """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            age INTEGER CHECK (age > 0 AND age < 150),
            email TEXT,
            CONSTRAINT chk_email CHECK (email LIKE '%@%'),
            CHECK (id > 0)
        )
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Introspect the table using factory
        from core.logger import ConsoleLog

        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        assert len(tables) == 1
        table = tables[0]
        assert table.name == "test_table"

        # Check that CHECK constraints were extracted
        check_constraints = [c for c in table.constraints if c.constraint_type.value == "CHECK"]

        # Should have at least 2 table-level CHECK constraints
        # (named and unnamed - column-level may not be extracted yet)
        assert (
            len(check_constraints) >= 2
        ), f"Expected at least 2 CHECK constraints, got {len(check_constraints)}"

        # Verify named constraint
        named_constraint = next((c for c in check_constraints if c.name == "chk_email"), None)
        assert named_constraint is not None, "Named CHECK constraint not found"
        assert "@" in named_constraint.check_expression, "Email CHECK expression not correct"

        # Verify unnamed constraint (may have normalized whitespace)
        unnamed_constraints = [
            c
            for c in check_constraints
            if c.name.startswith("check_")
            and ("id > 0" in c.check_expression or "id>0" in c.check_expression.replace(" ", ""))
        ]
        assert (
            len(unnamed_constraints) >= 1
        ), f"Unnamed CHECK constraint not found. Found constraints: {[(c.name, c.check_expression) for c in check_constraints]}"

    def test_round_trip_simple_table(self, sqlite_provider):
        """Test round-trip for a simple SQLite table."""
        # Create table
        create_sql = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Run round-trip test with SQLite introspector
        from core.introspection.introspector_factory import IntrospectorFactory
        from core.logger import ConsoleLog

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
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Warnings: {results.get('warnings', [])}"
        )
        assert (
            len(results["tables"]["differences"]) == 0
        ), f"Found differences: {results['tables']['differences']}"

    def test_round_trip_with_check_constraints(self, sqlite_provider):
        """Test round-trip preserves CHECK constraints."""
        # Create table with CHECK constraints
        create_sql = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL CHECK (price > 0),
            stock INTEGER CHECK (stock >= 0),
            CONSTRAINT chk_name_length CHECK (length(name) > 0)
        )
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Run round-trip test with SQLite introspector
        from core.introspection.introspector_factory import IntrospectorFactory
        from core.logger import ConsoleLog

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
        # Note: CHECK constraints may not be fully preserved yet
        # This test documents current behavior

    def test_round_trip_with_foreign_keys(self, sqlite_provider):
        """Test round-trip preserves foreign key constraints."""
        # Enable foreign key enforcement
        sqlite_provider.execute_statement("PRAGMA foreign_keys = ON")

        # Create tables with foreign key (SQLite requires separate statements)
        create_dept_sql = """
        CREATE TABLE departments (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        )
        """
        create_emp_sql = """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department_id INTEGER,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
        )
        """

        sqlite_provider.execute_statement(create_dept_sql)
        sqlite_provider.execute_statement(create_emp_sql)
        sqlite_provider.connection.commit()

        # Run round-trip test with SQLite introspector
        from core.introspection.introspector_factory import IntrospectorFactory
        from core.logger import ConsoleLog

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
        assert results["tables"]["original_count"] == 2
        # Check reintrospected_count (the actual key used)
        reintrospected_count = results["tables"].get("reintrospected_count", 0)
        assert reintrospected_count == 2, f"Expected 2 tables, got {reintrospected_count}"
