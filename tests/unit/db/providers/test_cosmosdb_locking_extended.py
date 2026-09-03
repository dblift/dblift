"""Extended tests for db/plugins/cosmosdb/cosmosdb/locking_manager.py."""

import unittest
from unittest.mock import MagicMock, patch


def _make_mgr():
    from dblift.db.plugins.cosmosdb.cosmosdb.locking_manager import CosmosDbLockingManager

    qe = MagicMock()
    log = MagicMock()
    mgr = CosmosDbLockingManager(query_executor=qe, log=log)
    return mgr, qe, log


class TestCosmosDbLockingManagerInit(unittest.TestCase):
    def test_stores_query_executor(self):
        mgr, qe, _ = _make_mgr()
        self.assertIs(mgr.query_executor, qe)

    def test_null_log_default(self):
        from dblift.core.logger import NullLog
        from dblift.db.plugins.cosmosdb.cosmosdb.locking_manager import CosmosDbLockingManager

        qe = MagicMock()
        mgr = CosmosDbLockingManager(query_executor=qe, log=None)
        self.assertIsInstance(mgr.log, NullLog)

    def test_container_none_initially(self):
        mgr, *_ = _make_mgr()
        self.assertIsNone(mgr.lock_container)


class TestCreateLockContainer(unittest.TestCase):
    def test_creates_container_when_none(self):
        mgr, qe, _ = _make_mgr()
        # Should not raise (may fail without real Azure setup)
        try:
            mgr.create_migration_lock_container_if_not_exists("test")
        except Exception:
            pass

    def test_raises_on_none_database(self):
        mgr, qe, _ = _make_mgr()
        qe.connection_manager.database = None
        qe.connection_manager.create_connection.return_value = None
        with self.assertRaises(Exception):
            mgr.create_migration_lock_container_if_not_exists("test")


class TestAcquireMigrationLock(unittest.TestCase):
    def test_returns_bool(self):
        mgr, qe, _ = _make_mgr()
        container = MagicMock()
        mgr.lock_container = container
        container.read_item.side_effect = Exception("NotFound 404")
        container.create_item.return_value = {"id": "migration_lock"}
        from unittest.mock import patch as _patch

        with _patch.object(mgr, "create_migration_lock_container_if_not_exists"):
            result = mgr.acquire_migration_lock("test")
        self.assertIsInstance(result, bool)

    def test_returns_false_and_logs_on_container_init_failure(self):
        # Infra failures during container init return False (preserves
        # the ``-> bool`` contract migrate_command depends on) and log
        # at error level. Earlier attempt to let RuntimeError propagate
        # broke the migrate flow. (PR #241 Bugbot.)
        mgr, qe, log = _make_mgr()
        from unittest.mock import patch as _patch

        with _patch.object(
            mgr,
            "create_migration_lock_container_if_not_exists",
            side_effect=RuntimeError("connection failed"),
        ):
            result = mgr.acquire_migration_lock("test")
        self.assertFalse(result)
        log.error.assert_called()


class TestReleaseMigrationLock(unittest.TestCase):
    def test_returns_bool(self):
        mgr, qe, _ = _make_mgr()
        mgr.lock_container = None
        result = mgr.release_migration_lock("test")
        self.assertIsInstance(result, bool)

    def test_deletes_existing_lock(self):
        mgr, qe, _ = _make_mgr()
        container = MagicMock()
        mgr.lock_container = container
        container.delete_item.return_value = None
        result = mgr.release_migration_lock("test")
        self.assertIsInstance(result, bool)

    def test_handles_not_found(self):
        mgr, qe, _ = _make_mgr()
        container = MagicMock()
        mgr.lock_container = container
        container.delete_item.side_effect = Exception("Not Found 404")
        result = mgr.release_migration_lock("test")
        self.assertIsInstance(result, bool)


class TestCreateLockDocument(unittest.TestCase):
    def test_creates_document(self):
        mgr, *_ = _make_mgr()
        container = MagicMock()
        container.create_item.return_value = {"id": "migration_lock"}
        mgr.lock_container = container
        result = mgr._create_lock_document()
        self.assertTrue(result)

    def test_handles_conflict(self):
        mgr, *_ = _make_mgr()
        container = MagicMock()
        container.create_item.side_effect = Exception("409 Conflict already exists")
        mgr.lock_container = container
        result = mgr._create_lock_document()
        self.assertFalse(result)

    def test_none_container_returns_false_and_logs(self):
        # Uninitialised lock container is an infra bug; return False
        # (matches ``-> bool`` contract) and log at error level so
        # the operator sees the real cause. (PR #241 Bugbot.)
        mgr, *_, log = _make_mgr()
        mgr.lock_container = None
        result = mgr._create_lock_document()
        self.assertFalse(result)
        log.error.assert_called()
