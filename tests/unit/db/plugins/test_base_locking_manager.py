"""Tests for BaseLockingManager abstract interface."""

from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.db.plugins.base_locking_manager import BaseLockingManager
from dblift.db.plugins.sqlite.sqlite.locking_manager import SQLiteLockingManager


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

    def test_component_locking_manager_is_an_instance_of_base(self):
        """SQLite is the one dialect that still attaches a locking component.

        The other relational dialects implement ``acquire_migration_lock`` /
        ``release_migration_lock`` on the provider itself, so they have no
        locking manager to type-check against this interface.
        """
        mgr = SQLiteLockingManager(query_executor=MagicMock())
        assert isinstance(mgr, BaseLockingManager)

    def test_component_locking_manager_is_a_subclass_of_base(self):
        assert issubclass(SQLiteLockingManager, BaseLockingManager)

    def test_cosmosdb_does_not_inherit_from_base(self):
        """CosmosDbLockingManager does NOT inherit from BaseLockingManager (different API)."""
        from dblift.db.plugins.cosmosdb.cosmosdb.locking_manager import CosmosDbLockingManager

        assert not issubclass(CosmosDbLockingManager, BaseLockingManager), (
            "CosmosDbLockingManager must NOT inherit from BaseLockingManager "
            "(non-relational, fundamentally different API)"
        )
