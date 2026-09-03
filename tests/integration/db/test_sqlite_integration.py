"""
SQLite integration tests.

These tests verify the complete SQLite provider workflow including:
- Connection management
- Migration execution
- History tracking
- Schema introspection
- Locking mechanism

Unlike other database integrations, SQLite tests don't require Docker
since SQLite uses Python's built-in sqlite3 module with file-based storage.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from dblift.core.logger import Log


class DummyLogger(Log):
    """Dummy logger for testing that implements the Log interface."""

    def __init__(self):
        super().__init__(name="test_sqlite", enable_debug=True)

    def debug(self, msg: str, *args, **kwargs):
        pass

    def info(self, msg: str, *args, **kwargs):
        pass

    def warning(self, msg: str, *args, **kwargs):
        pass

    def error(self, msg: str, *args, **kwargs):
        pass

    def exception(self, msg: str, *args, **kwargs):
        pass


@pytest.fixture
def dummy_logger():
    """Provide a dummy logger for tests."""
    return DummyLogger()


@pytest.fixture
def sqlite_temp_db():
    """Create a temporary SQLite database file."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name

    yield db_path

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def sqlite_memory_db():
    """Create an in-memory SQLite database path."""
    return ":memory:"


@pytest.fixture
def migrations_dir(tmp_path):
    """Create a temporary migrations directory."""
    migrations = tmp_path / "migrations"
    migrations.mkdir(parents=True, exist_ok=True)
    return migrations


def create_migration_file(migrations_dir: Path, name: str, content: str):
    """Create a migration file in the migrations directory."""
    migration_file = migrations_dir / name
    migration_file.write_text(content)
    return migration_file


@pytest.mark.integration
class TestSQLiteProviderConnection:
    """Test SQLite provider connection management."""

    def test_connect_file_database(self, sqlite_temp_db, dummy_logger):
        """Test connecting to a file-based SQLite database."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            connection = provider.create_connection()
            assert connection is not None

            # Verify we can execute queries
            version = provider.get_database_version()
            assert "SQLite" in version
        finally:
            provider.close()

    def test_connect_memory_database(self, sqlite_memory_db, dummy_logger):
        """Test connecting to an in-memory SQLite database."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_memory_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            connection = provider.create_connection()
            assert connection is not None

            version = provider.get_database_version()
            assert "SQLite" in version
        finally:
            provider.close()

    def test_execute_statement(self, sqlite_temp_db, dummy_logger):
        """Test executing SQL statements."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            provider.create_connection()

            # Create a table
            provider.execute_statement(
                "CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)"
            )

            # Insert data
            rows = provider.execute_statement("INSERT INTO test_table (name) VALUES ('test')")
            assert rows == 1

            # Verify data
            results = provider.execute_query("SELECT name FROM test_table")
            assert len(results) == 1
            assert results[0]["name"] == "test"
        finally:
            provider.close()


@pytest.mark.integration
class TestSQLiteHistoryManagement:
    """Test SQLite migration history management."""

    def test_create_history_table(self, sqlite_temp_db, dummy_logger):
        """Test creating migration history table."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            provider.create_connection()

            # Create history table
            provider.create_migration_history_table_if_not_exists("main")

            # Verify table exists
            assert provider.table_exists("main", "dblift_schema_history")
        finally:
            provider.close()

    def test_record_migration(self, sqlite_temp_db, dummy_logger):
        """Test recording a migration in history."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            provider.create_connection()

            migration_info = {
                "version": "1.0.0",
                "description": "Initial migration",
                "type": "SQL",
                "script": "V1_0_0__initial.sql",
                "checksum": "abc123",
                "execution_time": 100,
                "success": True,
            }

            provider.record_migration("main", migration_info)

            # Verify migration was recorded
            migrations = provider.get_applied_migrations("main")
            assert len(migrations) == 1
            assert migrations[0]["version"] == "1.0.0"
            assert migrations[0]["description"] == "Initial migration"
        finally:
            provider.close()

    def test_get_applied_migrations_empty(self, sqlite_temp_db, dummy_logger):
        """Test getting migrations when none exist."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            provider.create_connection()

            # Should return empty list when no migrations exist
            migrations = provider.get_applied_migrations("main")
            assert migrations == []
        finally:
            provider.close()


@pytest.mark.integration
class TestSQLiteSchemaOperations:
    """Test SQLite schema operations."""

    def test_clean_schema(self, sqlite_temp_db, dummy_logger):
        """Test cleaning database objects."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            provider.create_connection()

            # Create some objects
            provider.execute_statement("CREATE TABLE table1 (id INTEGER PRIMARY KEY)")
            provider.execute_statement("CREATE TABLE table2 (id INTEGER PRIMARY KEY)")
            provider.execute_statement("CREATE VIEW view1 AS SELECT * FROM table1")
            provider.execute_statement("CREATE INDEX idx1 ON table1(id)")

            # Verify objects exist
            assert provider.table_exists("main", "table1")
            assert provider.table_exists("main", "table2")

            # Clean schema
            summary = provider.clean_schema("main")
            assert len(summary.statements) > 0

            # Verify objects are gone
            assert not provider.table_exists("main", "table1")
            assert not provider.table_exists("main", "table2")
        finally:
            provider.close()

    def test_get_database_version(self, sqlite_temp_db, dummy_logger):
        """Test getting database version."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            provider.create_connection()

            version = provider.get_database_version()
            assert "SQLite" in version
            # SQLite version format: SQLite X.Y.Z
            assert any(char.isdigit() for char in version)
        finally:
            provider.close()


@pytest.mark.integration
class TestSQLiteLocking:
    """Test SQLite migration locking."""

    def test_acquire_and_release_lock(self, sqlite_temp_db, dummy_logger):
        """Test acquiring and releasing migration lock."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            provider.create_connection()

            # Acquire lock
            acquired = provider.acquire_migration_lock("main", wait_timeout_seconds=5)
            assert acquired is True

            # Release lock
            released = provider.release_migration_lock("main")
            assert released is True
        finally:
            provider.close()

    def test_lock_prevents_concurrent_acquisition(self, sqlite_temp_db, dummy_logger):
        """Test that lock prevents concurrent acquisition."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider1 = SQLiteProvider(config, dummy_logger)
        provider2 = SQLiteProvider(config, dummy_logger)

        try:
            provider1.create_connection()
            provider2.create_connection()

            # First provider acquires lock
            acquired1 = provider1.acquire_migration_lock("main", wait_timeout_seconds=2)
            assert acquired1 is True

            # Second provider should fail to acquire lock (with short timeout)
            acquired2 = provider2.acquire_migration_lock("main", wait_timeout_seconds=1)
            assert acquired2 is False

            # Release first lock
            provider1.release_migration_lock("main")

            # Now second provider should be able to acquire
            acquired2 = provider2.acquire_migration_lock("main", wait_timeout_seconds=2)
            assert acquired2 is True

            provider2.release_migration_lock("main")
        finally:
            provider1.close()
            provider2.close()


@pytest.mark.integration
class TestSQLiteTransactions:
    """Test SQLite transaction management."""

    def test_transaction_commit(self, sqlite_temp_db, dummy_logger):
        """Test transaction commit."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            provider.create_connection()

            # Create table
            provider.execute_statement("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")

            # Begin transaction
            provider.begin_transaction()

            # Insert data
            provider.execute_statement("INSERT INTO test (val) VALUES ('test1')")
            provider.execute_statement("INSERT INTO test (val) VALUES ('test2')")

            # Commit
            provider.commit_transaction()

            # Verify data persisted
            results = provider.execute_query("SELECT COUNT(*) as cnt FROM test")
            assert results[0]["cnt"] == 2
        finally:
            provider.close()

    def test_transaction_rollback(self, sqlite_temp_db, dummy_logger):
        """Test transaction rollback."""
        from dblift.config import DbliftConfig
        from dblift.db.plugins.sqlite.provider import SQLiteProvider

        config_dict = {
            "database": {
                "type": "sqlite",
                "path": sqlite_temp_db,
            },
            "migrations": {
                "directory": "/tmp",
                "table": "dblift_schema_history",
            },
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = SQLiteProvider(config, dummy_logger)

        try:
            provider.create_connection()

            # Create table and insert initial data
            provider.execute_statement("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
            provider.execute_statement("INSERT INTO test (val) VALUES ('initial')")

            # Begin transaction
            provider.begin_transaction()

            # Insert more data
            provider.execute_statement("INSERT INTO test (val) VALUES ('rollback_me')")

            # Rollback
            provider.rollback_transaction()

            # Verify only initial data exists
            results = provider.execute_query("SELECT val FROM test")
            assert len(results) == 1
            assert results[0]["val"] == "initial"
        finally:
            provider.close()
