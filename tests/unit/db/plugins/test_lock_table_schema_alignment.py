"""Tests for lock table schema alignment across MySQL and DB2 plugins.

Verifies that CREATE TABLE SQL uses the standard column names
(lock_name, acquired_at, acquired_by) as defined in the BaseLockingManager
schema contract.
"""

from unittest.mock import MagicMock

import pytest

from db.plugins.db2.db2.locking_manager import Db2LockingManager
from db.plugins.mysql.mysql.locking_manager import MySqlLockingManager


def _capture_create_table_sql(manager_class):
    """Helper: instantiate a locking manager, call create_migration_lock_table_if_not_exists,
    and return the SQL string passed to execute_statement."""
    mock_qe = MagicMock()
    mock_qe.table_exists.return_value = False
    mock_qe.get_schema_qualified_name.return_value = "myschema.dblift_migration_lock"

    manager = manager_class(query_executor=mock_qe)

    mock_conn = MagicMock()
    manager.create_migration_lock_table_if_not_exists(mock_conn, "myschema")

    sql_called = mock_qe.execute_statement.call_args[0][1]
    return sql_called


# ── MySQL tests ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestMySqlLockTableSchema:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.sql = _capture_create_table_sql(MySqlLockingManager)

    def test_mysql_create_table_contains_lock_name(self):
        assert "lock_name" in self.sql.lower()

    def test_mysql_create_table_contains_acquired_at(self):
        assert "acquired_at" in self.sql.lower()

    def test_mysql_create_table_contains_acquired_by(self):
        assert "acquired_by" in self.sql.lower()

    def test_mysql_create_table_does_not_contain_lock_id(self):
        assert "lock_id" not in self.sql.lower()


# ── MySQL DML tests ───────────────────────────────────────────────────────


def _capture_mysql_dml_sql(mock_execute_query_result):
    """Helper: run _try_table_based_locking_acquire and return all execute_statement SQL."""
    mock_qe = MagicMock()
    mock_qe.table_exists.return_value = True  # table exists, skip CREATE TABLE
    mock_qe.get_schema_qualified_name.return_value = "myschema.dblift_migration_lock"
    mock_qe.execute_query.return_value = mock_execute_query_result
    mock_qe.execute_statement.return_value = 0

    manager = MySqlLockingManager(query_executor=mock_qe)
    mock_conn = MagicMock()
    manager._try_table_based_locking_acquire(mock_conn, "myschema", 1)

    return " ".join(str(c) for c in mock_qe.execute_statement.call_args_list)


@pytest.mark.unit
class TestMySqlDmlSchema:
    """Verify DML queries (INSERT/UPDATE/DELETE) use aligned column names."""

    def test_mysql_insert_sql_uses_lock_name(self):
        # No existing lock row → INSERT path
        combined = _capture_mysql_dml_sql([])
        assert "lock_name" in combined.lower()
        assert "lock_id" not in combined.lower()

    def test_mysql_insert_sql_uses_acquired_at(self):
        combined = _capture_mysql_dml_sql([])
        assert "acquired_at" in combined.lower()
        assert "locked_at" not in combined.lower()

    def test_mysql_insert_sql_uses_acquired_by(self):
        combined = _capture_mysql_dml_sql([])
        assert "acquired_by" in combined.lower()
        assert "locked_by" not in combined.lower()

    def test_mysql_update_sql_uses_acquired_columns(self):
        # Existing lock row → UPDATE path
        existing_row = [{"lock_name": "migration", "acquired_at": "now", "acquired_by": "x"}]
        combined = _capture_mysql_dml_sql(existing_row)
        assert "acquired_at" in combined.lower()
        assert "acquired_by" in combined.lower()
        assert "locked_at" not in combined.lower()
        assert "locked_by" not in combined.lower()


# ── DB2 tests ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDb2LockTableSchema:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.sql = _capture_create_table_sql(Db2LockingManager)

    def test_db2_create_table_contains_lock_name(self):
        assert "lock_name" in self.sql.lower()

    def test_db2_create_table_contains_acquired_at(self):
        assert "acquired_at" in self.sql.lower()

    def test_db2_create_table_contains_acquired_by(self):
        assert "acquired_by" in self.sql.lower()

    def test_db2_create_table_does_not_contain_lock_id(self):
        assert "lock_id" not in self.sql.lower()


# ── DB2 DML tests ────────────────────────────────────────────────────────


def _capture_db2_dml_sql():
    """Helper: run DB2 _try_table_based_locking_acquire and return all execute_statement SQL."""
    mock_qe = MagicMock()
    mock_qe.table_exists.return_value = True  # table exists everywhere
    mock_qe.get_schema_qualified_name.return_value = "myschema.DBLIFT_MIGRATION_LOCK"
    mock_qe.execute_statement.return_value = 0

    manager = Db2LockingManager(query_executor=mock_qe)
    mock_conn = MagicMock()
    mock_conn.getAutoCommit.return_value = False

    manager._try_table_based_locking_acquire(mock_conn, "myschema", 1)

    return " ".join(str(c) for c in mock_qe.execute_statement.call_args_list)


@pytest.mark.unit
class TestDb2DmlSchema:
    """Verify DML queries (MERGE, cleanup DELETE) use aligned column names."""

    def test_db2_merge_sql_uses_lock_name(self):
        combined = _capture_db2_dml_sql()
        assert "lock_name" in combined.lower()
        assert "lock_id" not in combined.lower()

    def test_db2_merge_sql_uses_acquired_at(self):
        combined = _capture_db2_dml_sql()
        assert "acquired_at" in combined.lower()
        assert "locked_at" not in combined.lower()

    def test_db2_merge_sql_uses_acquired_by(self):
        combined = _capture_db2_dml_sql()
        assert "acquired_by" in combined.lower()
        assert "locked_by" not in combined.lower()
