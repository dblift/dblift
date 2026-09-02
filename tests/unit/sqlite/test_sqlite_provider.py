"""Unit tests for SQLite provider."""

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]


class TestSQLiteConnectionManager:
    """Tests for SQLite connection manager."""

    def test_get_database_path_from_path(self):
        """Test getting database path from path config."""
        from dblift.db.plugins.sqlite.sqlite.connection_manager import SQLiteConnectionManager

        mock_config = MagicMock()
        mock_config.database.path = "/path/to/db.sqlite"
        mock_config.database.database = None
        mock_config.database.url = None

        manager = SQLiteConnectionManager(mock_config)
        assert manager.db_path == "/path/to/db.sqlite"

    def test_get_database_path_from_database(self):
        """Test getting database path from database config."""
        from dblift.db.plugins.sqlite.sqlite.connection_manager import SQLiteConnectionManager

        mock_config = MagicMock()
        mock_config.database.path = None
        mock_config.database.database = "/path/to/db.sqlite"
        mock_config.database.url = None

        manager = SQLiteConnectionManager(mock_config)
        assert manager.db_path == "/path/to/db.sqlite"

    def test_get_database_path_from_url(self):
        """Test getting database path from URL config.

        Three slashes is SQLAlchemy's convention for a path relative to cwd
        (``sqlite_path_from_url`` in ``db/plugins/sqlite/config.py`` is the
        single place this is parsed, and it agrees with
        ``sqlalchemy.engine.make_url``) — a fourth slash is required for an
        absolute path.
        """
        from dblift.db.plugins.sqlite.sqlite.connection_manager import SQLiteConnectionManager

        mock_config = MagicMock()
        mock_config.database.path = None
        mock_config.database.database = None
        mock_config.database.url = "sqlite:///path/to/db.sqlite"

        manager = SQLiteConnectionManager(mock_config)
        assert manager.db_path == "path/to/db.sqlite"

    def test_create_connection_memory(self):
        """Test creating in-memory database connection."""
        from dblift.db.plugins.sqlite.sqlite.connection_manager import SQLiteConnectionManager

        mock_config = MagicMock()
        mock_config.database.path = ":memory:"
        mock_config.database.database = None
        mock_config.database.url = None

        manager = SQLiteConnectionManager(mock_config)
        conn = manager.create_connection()

        assert conn is not None
        assert isinstance(conn, sqlite3.Connection)

        # Verify connection is working
        cursor = conn.execute("SELECT sqlite_version()")
        version = cursor.fetchone()[0]
        assert version is not None

        conn.close()

    def test_create_connection_file(self):
        """Test creating file-based database connection."""
        from dblift.db.plugins.sqlite.sqlite.connection_manager import SQLiteConnectionManager

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        try:
            mock_config = MagicMock()
            mock_config.database.path = db_path
            mock_config.database.database = None
            mock_config.database.url = None

            manager = SQLiteConnectionManager(mock_config)
            conn = manager.create_connection()

            assert conn is not None
            assert isinstance(conn, sqlite3.Connection)

            # Verify we can create a table
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
            conn.commit()

            conn.close()

            # Verify file was created
            assert os.path.exists(db_path)
        finally:
            os.unlink(db_path)


class TestSQLiteQueryExecutor:
    """Tests for SQLite query executor."""

    def setup_method(self):
        """Set up test fixtures."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

        # Create test table
        self.conn.execute("""
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value INTEGER
            )
        """)
        self.conn.execute("INSERT INTO test_table (name, value) VALUES ('test1', 100)")
        self.conn.execute("INSERT INTO test_table (name, value) VALUES ('test2', 200)")
        self.conn.commit()

    def teardown_method(self):
        """Clean up test fixtures."""
        self.conn.close()

    def test_execute_query(self):
        """Test executing a SELECT query."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)

        results = executor.execute_query(
            self.conn, "SELECT name, value FROM test_table ORDER BY id"
        )

        assert len(results) == 2
        assert results[0]["name"] == "test1"
        assert results[0]["value"] == 100
        assert results[1]["name"] == "test2"
        assert results[1]["value"] == 200

    def test_execute_query_with_params(self):
        """Test executing a parameterized query."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)

        results = executor.execute_query(
            self.conn, "SELECT * FROM test_table WHERE value > ?", [100]
        )

        assert len(results) == 1
        assert results[0]["name"] == "test2"

    def test_execute_statement(self):
        """Test executing an INSERT statement."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)

        rows_affected = executor.execute_statement(
            self.conn,
            "INSERT INTO test_table (name, value) VALUES (?, ?)",
            ["test3", 300],
        )

        assert rows_affected == 1

        # Verify insertion
        results = executor.execute_query(self.conn, "SELECT * FROM test_table WHERE name = 'test3'")
        assert len(results) == 1
        assert results[0]["value"] == 300

    def test_table_exists_true(self):
        """Test table_exists returns True for existing table."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)

        assert executor.table_exists(self.conn, "main", "test_table") is True

    def test_table_exists_false(self):
        """Test table_exists returns False for non-existing table."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)

        assert executor.table_exists(self.conn, "main", "nonexistent") is False

    def test_get_schema_qualified_name(self):
        """Test schema-qualified name generation."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)

        # SQLite doesn't use schemas, so just returns quoted name
        name = executor.get_schema_qualified_name("main", "my_table")
        assert name == '"my_table"'


class TestSQLiteSchemaOperations:
    """Tests for SQLite schema operations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def teardown_method(self):
        """Clean up test fixtures."""
        self.conn.close()

    def test_create_schema_is_noop(self):
        """Test that create_schema is a no-op for SQLite."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor
        from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)
        schema_ops = SQLiteSchemaOperations(executor)

        # Should not raise an exception
        schema_ops.create_schema_if_not_exists(self.conn, "test_schema")

    def test_get_database_version(self):
        """Test getting database version."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor
        from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)
        schema_ops = SQLiteSchemaOperations(executor)

        version = schema_ops.get_database_version(self.conn)
        assert "SQLite" in version

    def test_get_tables(self):
        """Test getting list of tables."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor
        from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        # Create some tables
        self.conn.execute("CREATE TABLE table1 (id INTEGER PRIMARY KEY)")
        self.conn.execute("CREATE TABLE table2 (id INTEGER PRIMARY KEY)")
        self.conn.commit()

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)
        schema_ops = SQLiteSchemaOperations(executor)

        tables = schema_ops.get_tables(self.conn, "main")
        assert "table1" in tables
        assert "table2" in tables

    def test_get_schemas(self):
        """Test getting list of schemas (should return ['main'])."""
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor
        from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        mock_connection_manager = MagicMock()
        executor = SQLiteQueryExecutor(mock_connection_manager)
        schema_ops = SQLiteSchemaOperations(executor)

        schemas = schema_ops.get_schemas(self.conn)
        assert schemas == ["main"]


class TestSQLiteHistoryManager:
    """Tests for SQLite history manager."""

    def setup_method(self):
        """Set up test fixtures."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def teardown_method(self):
        """Clean up test fixtures."""
        self.conn.close()

    def test_create_history_table(self):
        """Test creating migration history table."""
        from dblift.db.plugins.sqlite.sqlite.history_manager import SQLiteHistoryManager
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor
        from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        mock_connection_manager = MagicMock()
        mock_config = MagicMock()

        executor = SQLiteQueryExecutor(mock_connection_manager)
        schema_ops = SQLiteSchemaOperations(executor)
        history_mgr = SQLiteHistoryManager(executor, schema_ops, mock_config)

        history_mgr.create_migration_history_table_if_not_exists(
            self.conn, "main", create_schema=False
        )

        # Verify table was created
        assert executor.table_exists(self.conn, "main", "dblift_schema_history")

    def test_record_migration(self):
        """Test recording a migration."""
        from dblift.db.plugins.sqlite.sqlite.history_manager import SQLiteHistoryManager
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor
        from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        mock_connection_manager = MagicMock()
        mock_config = MagicMock()

        executor = SQLiteQueryExecutor(mock_connection_manager)
        schema_ops = SQLiteSchemaOperations(executor)
        history_mgr = SQLiteHistoryManager(executor, schema_ops, mock_config)

        migration_info = {
            "version": "1.0.0",
            "description": "Initial migration",
            "type": "SQL",
            "script": "V1_0_0__Initial.sql",
            "checksum": "abc123",
            "execution_time": 100,
            "success": True,
        }

        history_mgr.record_migration(self.conn, "main", migration_info)

        # Verify migration was recorded
        results = history_mgr.get_applied_migrations(self.conn, "main")
        assert len(results) == 1
        assert results[0]["version"] == "1.0.0"
        assert results[0]["description"] == "Initial migration"
        assert results[0]["success"] is True

    def test_get_applied_migrations_empty(self):
        """Test getting migrations when none exist."""
        from dblift.db.plugins.sqlite.sqlite.history_manager import SQLiteHistoryManager
        from dblift.db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor
        from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        mock_connection_manager = MagicMock()
        mock_config = MagicMock()

        executor = SQLiteQueryExecutor(mock_connection_manager)
        schema_ops = SQLiteSchemaOperations(executor)
        history_mgr = SQLiteHistoryManager(executor, schema_ops, mock_config)

        results = history_mgr.get_applied_migrations(self.conn, "main")
        assert results == []
