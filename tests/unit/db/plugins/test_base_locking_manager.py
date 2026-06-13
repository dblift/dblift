"""Tests for BaseLockingManager abstract interface."""

from unittest.mock import MagicMock

import pytest

from core.logger import NullLog
from db.plugins.base_locking_manager import BaseLockingManager
from db.plugins.db2.db2.locking_manager import Db2LockingManager
from db.plugins.mysql.mysql.locking_manager import MySqlLockingManager
from db.plugins.oracle.oracle.locking_manager import OracleLockingManager
from db.plugins.postgresql.postgresql.locking_manager import PostgreSqlLockingManager
from db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager
from db.plugins.sqlserver.sqlserver.locking_manager import SqlServerLockingManager


@pytest.mark.unit
class TestBaseLockingManagerInterface:
    """Verify the abstract interface contract."""

    def test_cannot_instantiate_directly(self):
        """BaseLockingManager cannot be instantiated directly (it has abstract methods)."""
        with pytest.raises(TypeError):
            BaseLockingManager(query_executor=MagicMock())

    def test_concrete_without_all_methods_raises_type_error(self):
        """A subclass missing abstract methods raises TypeError at instantiation."""

        class IncompleteLockingManager(BaseLockingManager):
            def acquire_migration_lock(self, connection, schema, wait_timeout_seconds=60):
                return True

            # Missing: create_migration_lock_table_if_not_exists, release_migration_lock

        with pytest.raises(TypeError):
            IncompleteLockingManager(query_executor=MagicMock())

    def test_concrete_missing_one_method_raises_type_error(self):
        """A subclass missing only one abstract method raises TypeError."""

        class AlmostCompleteLockingManager(BaseLockingManager):
            def create_migration_lock_table_if_not_exists(self, connection, schema):
                pass

            def acquire_migration_lock(self, connection, schema, wait_timeout_seconds=60):
                return True

            # Missing: release_migration_lock

        with pytest.raises(TypeError):
            AlmostCompleteLockingManager(query_executor=MagicMock())

    def test_concrete_with_all_methods_is_instantiable(self):
        """A complete subclass implementing all 3 abstract methods can be instantiated."""

        class CompleteLockingManager(BaseLockingManager):
            def create_migration_lock_table_if_not_exists(self, connection, schema):
                pass

            def acquire_migration_lock(self, connection, schema, wait_timeout_seconds=60):
                return True

            def release_migration_lock(self, connection, schema):
                return True

        qe = MagicMock()
        mgr = CompleteLockingManager(query_executor=qe)
        assert isinstance(mgr, BaseLockingManager)
        assert mgr.query_executor is qe
        assert isinstance(mgr.log, NullLog)

    def test_concrete_stores_query_executor_and_log(self):
        """BaseLockingManager.__init__ stores query_executor and log correctly."""

        class CompleteLockingManager(BaseLockingManager):
            def create_migration_lock_table_if_not_exists(self, connection, schema):
                pass

            def acquire_migration_lock(self, connection, schema, wait_timeout_seconds=60):
                return True

            def release_migration_lock(self, connection, schema):
                return True

        qe = MagicMock()
        log = MagicMock()
        mgr = CompleteLockingManager(query_executor=qe, log=log)
        assert mgr.query_executor is qe
        assert mgr.log is log

    @pytest.mark.parametrize(
        "manager_class,kwargs",
        [
            (OracleLockingManager, {"query_executor": MagicMock()}),
            (PostgreSqlLockingManager, {"query_executor": MagicMock()}),
            (MySqlLockingManager, {"query_executor": MagicMock()}),
            (SqlServerLockingManager, {"query_executor": MagicMock()}),
            (SQLiteLockingManager, {"query_executor": MagicMock()}),
            (Db2LockingManager, {"query_executor": MagicMock()}),
        ],
    )
    def test_jdbc_managers_are_instances_of_base(self, manager_class, kwargs):
        """All SQL locking managers are instances of BaseLockingManager."""
        mgr = manager_class(**kwargs)
        assert isinstance(
            mgr, BaseLockingManager
        ), f"{manager_class.__name__} should be an instance of BaseLockingManager"

    @pytest.mark.parametrize(
        "manager_class",
        [
            OracleLockingManager,
            PostgreSqlLockingManager,
            MySqlLockingManager,
            SqlServerLockingManager,
            SQLiteLockingManager,
            Db2LockingManager,
        ],
    )
    def test_jdbc_managers_are_subclasses_of_base(self, manager_class):
        """All SQL locking managers are subclasses of BaseLockingManager."""
        assert issubclass(
            manager_class, BaseLockingManager
        ), f"{manager_class.__name__} should be a subclass of BaseLockingManager"

    def test_cosmosdb_does_not_inherit_from_base(self):
        """CosmosDbLockingManager does NOT inherit from BaseLockingManager (different API)."""
        from db.plugins.cosmosdb.cosmosdb.locking_manager import CosmosDbLockingManager

        assert not issubclass(CosmosDbLockingManager, BaseLockingManager), (
            "CosmosDbLockingManager must NOT inherit from BaseLockingManager "
            "(non-relational, fundamentally different API)"
        )
