"""
SQLite Advanced Features Tests.

Tests for SQLite-specific features like STRICT mode, WITHOUT ROWID, temporary tables, etc.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_advanced.sqlite"

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
    log = ConsoleLog("sqlite_advanced_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()
    provider.connection.commit()

    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLiteAdvancedFeatures:
    """SQLite advanced feature tests."""

    def test_strict_mode_table(self, sqlite_provider):
        """Test STRICT mode tables (SQLite 3.37+)."""
        create_sql = """
        CREATE TABLE strict_table (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER,
            salary REAL
        ) STRICT
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        assert len(tables) == 1
        table = tables[0]
        assert table.name == "strict_table"
        # Note: STRICT mode may not be introspectable, but table should exist

    def test_without_rowid_table(self, sqlite_provider):
        """Test WITHOUT ROWID tables."""
        create_sql = """
        CREATE TABLE key_value_store (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        assert len(tables) == 1
        table = tables[0]
        assert table.name == "key_value_store"
        # Note: WITHOUT ROWID may not be introspectable, but table should exist

    def test_temporary_table(self, sqlite_provider):
        """Test temporary tables."""
        create_sql = """
        CREATE TEMP TABLE temp_data (
            id INTEGER PRIMARY KEY,
            data TEXT
        )
        """

        sqlite_provider.execute_statement(create_sql)
        sqlite_provider.connection.commit()

        # Introspect
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)
        tables = introspector.get_tables("main")

        # Temporary tables may not appear in main schema introspection
        # This test verifies the table can be created

    def test_composite_primary_key_without_rowid(self, sqlite_provider):
        """Test composite PRIMARY KEY with WITHOUT ROWID."""
        create_sql = """
        CREATE TABLE composite_pk (
            part1 TEXT NOT NULL,
            part2 TEXT NOT NULL,
            data TEXT,
            PRIMARY KEY (part1, part2)
        ) WITHOUT ROWID
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

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

    def test_unique_constraint_multiple_columns(self, sqlite_provider):
        """Test UNIQUE constraint on multiple columns."""
        create_sql = """
        CREATE TABLE user_sessions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            session_token TEXT NOT NULL,
            created_at TEXT,
            UNIQUE (user_id, session_token)
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

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

    def test_default_values_with_functions(self, sqlite_provider):
        """Test DEFAULT values with SQLite functions."""
        create_sql = """
        CREATE TABLE timestamps (
            id INTEGER PRIMARY KEY,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            random_id INTEGER DEFAULT (abs(random()))
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

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )
