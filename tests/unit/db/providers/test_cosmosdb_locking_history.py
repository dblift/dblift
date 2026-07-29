"""Unit tests for CosmosDB locking and history managers.

Covers CosmosDbLockingManager and CosmosDbHistoryManager internals
using mocked azure-cosmos container clients.
"""

import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connection_manager(database=None):
    """Build a minimal CosmosDbConnectionManager mock."""
    cm = MagicMock()
    cm.database = database
    return cm


def _make_query_executor(connection_manager=None):
    """Build a minimal CosmosDbQueryExecutor mock."""
    qe = MagicMock()
    qe.connection_manager = connection_manager or _make_connection_manager()
    return qe


def _make_locking_manager(connection_manager=None, log=None):
    """Build a CosmosDbLockingManager with mock dependencies."""
    from db.plugins.cosmosdb.cosmosdb.locking_manager import CosmosDbLockingManager

    cm = connection_manager or _make_connection_manager()
    qe = _make_query_executor(connection_manager=cm)
    _log = log or MagicMock()
    mgr = CosmosDbLockingManager(query_executor=qe, log=_log)
    return mgr, cm, _log


def _make_history_manager(connection_manager=None, log=None):
    """Build a CosmosDbHistoryManager with mock dependencies."""
    from db.plugins.cosmosdb.cosmosdb.history_manager import CosmosDbHistoryManager

    cm = connection_manager or _make_connection_manager()
    qe = _make_query_executor(connection_manager=cm)
    schema_ops = MagicMock()
    config = MagicMock()
    _log = log or MagicMock()
    mgr = CosmosDbHistoryManager(
        query_executor=qe,
        schema_operations=schema_ops,
        config=config,
        log=_log,
    )
    return mgr, cm, _log


# ===========================================================================
# LockingManager tests
# ===========================================================================


class TestCosmosDbLockingManagerInit(unittest.TestCase):
    """Test CosmosDbLockingManager initialisation."""

    def test_init_sets_query_executor(self):
        mgr, cm, _ = _make_locking_manager()
        self.assertIsNotNone(mgr.query_executor)

    def test_init_sets_connection_manager(self):
        mgr, cm, _ = _make_locking_manager()
        self.assertIs(mgr.connection_manager, cm)

    def test_init_with_none_log_uses_nulllog(self):
        from core.logger import NullLog
        from db.plugins.cosmosdb.cosmosdb.locking_manager import CosmosDbLockingManager

        cm = _make_connection_manager()
        qe = _make_query_executor(connection_manager=cm)
        mgr = CosmosDbLockingManager(query_executor=qe, log=None)
        self.assertIsInstance(mgr.log, NullLog)

    def test_lock_container_is_none_initially(self):
        mgr, _, _ = _make_locking_manager()
        self.assertIsNone(mgr.lock_container)


class TestCreateMigrationLockContainer(unittest.TestCase):
    """Test create_migration_lock_container_if_not_exists."""

    def test_creates_container_and_sets_lock_container(self):
        mock_db = MagicMock()
        mock_container = MagicMock()
        mock_db.create_container_if_not_exists.return_value = mock_container
        mock_db.get_container_client.return_value = mock_container

        cm = _make_connection_manager(database=mock_db)
        mgr, _, _ = _make_locking_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                mgr.create_migration_lock_container_if_not_exists("public")

        mock_db.create_container_if_not_exists.assert_called_once()
        self.assertIs(mgr.lock_container, mock_container)

    def test_creates_connection_when_database_is_none(self):
        mock_db = MagicMock()
        mock_db.create_container_if_not_exists.return_value = MagicMock()
        mock_db.get_container_client.return_value = MagicMock()

        cm = _make_connection_manager(database=None)
        # After create_connection(), database becomes available
        cm.create_connection.side_effect = lambda: setattr(cm, "database", mock_db)

        mgr, _, _ = _make_locking_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                mgr.create_migration_lock_container_if_not_exists("public")

        cm.create_connection.assert_called_once()

    def test_raises_when_database_remains_none_after_create(self):
        cm = _make_connection_manager(database=None)
        # create_connection doesn't set database
        mgr, _, _ = _make_locking_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                with self.assertRaises(RuntimeError):
                    mgr.create_migration_lock_container_if_not_exists("public")

    def test_error_during_create_propagates(self):
        mock_db = MagicMock()
        mock_db.create_container_if_not_exists.side_effect = Exception("network error")

        cm = _make_connection_manager(database=mock_db)
        mgr, _, log = _make_locking_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                with self.assertRaises(Exception):
                    mgr.create_migration_lock_container_if_not_exists("public")

        log.error.assert_called()


class TestCreateLockDocument(unittest.TestCase):
    """Test _create_lock_document private method."""

    def test_returns_true_on_success(self):
        mock_container = MagicMock()
        created_doc = {"id": "migration_lock"}
        mock_container.create_item.return_value = created_doc

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        result = mgr._create_lock_document()

        self.assertTrue(result)
        mock_container.create_item.assert_called_once()

    def test_returns_false_when_document_already_exists_conflict(self):
        mock_container = MagicMock()
        mock_container.create_item.side_effect = Exception("409 conflict already exists")

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        result = mgr._create_lock_document()

        self.assertFalse(result)

    def test_returns_false_when_document_already_exists_by_message(self):
        mock_container = MagicMock()
        mock_container.create_item.side_effect = Exception("document already exists")

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        result = mgr._create_lock_document()

        self.assertFalse(result)

    def test_raises_on_unexpected_error(self):
        mock_container = MagicMock()
        mock_container.create_item.side_effect = RuntimeError("network failure")

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        with self.assertRaises(RuntimeError):
            mgr._create_lock_document()

    def test_returns_false_and_logs_when_lock_container_is_none(self):
        # Uninitialised lock container is an infra bug. Return False
        # (matches ``-> bool`` contract) and log at error level. The
        # earlier ``raise RuntimeError`` broke callers that consume
        # the bool. (PR #241 Bugbot.)
        mgr, _, log = _make_locking_manager()
        mgr.lock_container = None

        result = mgr._create_lock_document()
        self.assertFalse(result)
        log.error.assert_called()

    def test_returns_false_when_created_doc_has_wrong_id(self):
        mock_container = MagicMock()
        mock_container.create_item.return_value = {"id": "wrong_id"}

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        result = mgr._create_lock_document()

        self.assertFalse(result)


class TestReleaseMigrationLock(unittest.TestCase):
    """Test release_migration_lock."""

    def test_returns_true_on_successful_delete(self):
        mock_container = MagicMock()
        mock_container.delete_item.return_value = None

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        result = mgr.release_migration_lock("public")

        self.assertTrue(result)
        mock_container.delete_item.assert_called_once_with(
            item="migration_lock",
            partition_key="migration_lock",
        )

    def test_returns_true_when_document_not_found(self):
        mock_container = MagicMock()
        mock_container.delete_item.side_effect = Exception("NotFound")

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        result = mgr.release_migration_lock("public")

        self.assertTrue(result)

    def test_returns_true_when_not_found_lowercase(self):
        mock_container = MagicMock()
        mock_container.delete_item.side_effect = Exception("not found")

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        result = mgr.release_migration_lock("public")

        self.assertTrue(result)

    def test_returns_false_on_unexpected_error(self):
        mock_container = MagicMock()
        mock_container.delete_item.side_effect = Exception("network error")

        mgr, _, log = _make_locking_manager()
        mgr.lock_container = mock_container

        result = mgr.release_migration_lock("public")

        self.assertFalse(result)
        log.error.assert_called()

    def test_gets_container_client_when_lock_container_is_none(self):
        mock_container = MagicMock()
        mock_container.delete_item.return_value = None

        cm = _make_connection_manager()
        cm.get_container_client.return_value = mock_container

        mgr, _, _ = _make_locking_manager(connection_manager=cm)
        mgr.lock_container = None

        result = mgr.release_migration_lock("public")

        cm.get_container_client.assert_called_once_with("dblift_migration_lock")
        self.assertTrue(result)

    def test_returns_false_when_container_remains_none(self):
        """When get_container_client returns None, RuntimeError is caught → False."""
        cm = _make_connection_manager()
        cm.get_container_client.return_value = None

        mgr, _, _ = _make_locking_manager(connection_manager=cm)
        mgr.lock_container = None

        result = mgr.release_migration_lock("public")
        self.assertFalse(result)


class TestTryNativeLockAcquire(unittest.TestCase):
    """Test _try_native_lock_acquire: 404 → creates document."""

    def test_acquires_lock_when_no_existing_document(self):
        """When read_item raises 404, creates lock document → True."""
        mock_container = MagicMock()
        mock_container.read_item.side_effect = Exception("not found 404")

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        # _create_lock_document succeeds on first call
        with patch.object(mgr, "_create_lock_document", return_value=True):
            with patch("time.sleep"):
                result = mgr._try_native_lock_acquire("public", wait_timeout_seconds=1)

        self.assertTrue(result)

    def test_falls_back_when_read_raises_unexpected_error(self):
        """Non-404 read error → return False (fall back to document locking)."""
        mock_container = MagicMock()
        mock_container.read_item.side_effect = Exception("internal server error")

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        with patch("time.sleep"):
            result = mgr._try_native_lock_acquire("public", wait_timeout_seconds=1)

        self.assertFalse(result)

    def test_returns_false_when_lock_container_is_none(self):
        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = None

        with patch("time.sleep"):
            result = mgr._try_native_lock_acquire("public", wait_timeout_seconds=1)

        self.assertFalse(result)

    def test_waits_when_lock_not_expired(self):
        """Existing unexpired lock → waits, then times out → False."""
        future = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        ).isoformat()
        existing_lock = {"id": "migration_lock", "expires_at": future, "_etag": "tag1"}

        mock_container = MagicMock()
        mock_container.read_item.return_value = existing_lock

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        with patch("time.sleep"):
            with patch("time.time", side_effect=[0, 0.1, 0.2, 2]):
                result = mgr._try_native_lock_acquire("public", wait_timeout_seconds=1)

        self.assertFalse(result)

    def test_deletes_expired_lock_and_continues(self):
        """Expired lock: deletes it, then creates new document → True."""
        past = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        ).isoformat()
        existing_lock = {"id": "migration_lock", "expires_at": past, "_etag": "etag1"}

        mock_container = MagicMock()
        # First call: returns expired lock; second call: raises 404 so we create
        mock_container.read_item.side_effect = [existing_lock, Exception("not found 404")]

        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = mock_container

        with patch.object(mgr, "_create_lock_document", return_value=True):
            with patch("time.sleep"):
                result = mgr._try_native_lock_acquire("public", wait_timeout_seconds=5)

        self.assertTrue(result)


class TestAcquireDocumentBasedLock(unittest.TestCase):
    """Test _acquire_document_based_lock fallback."""

    def test_acquires_lock_when_create_succeeds(self):
        mgr, _, _ = _make_locking_manager()
        mgr.lock_container = MagicMock()

        with patch.object(mgr, "_create_lock_document", return_value=True):
            with patch("time.sleep"):
                result = mgr._acquire_document_based_lock("public", wait_timeout_seconds=5)

        self.assertTrue(result)

    def test_returns_false_after_timeout(self):
        mgr, _, _ = _make_locking_manager()
        mock_container = MagicMock()
        # read_item raises 404 every time (no existing lock to check expiry)
        mock_container.read_item.side_effect = Exception("not found 404")
        mgr.lock_container = mock_container

        # Use a real clock-based approach: set wait_timeout_seconds=0 so it expires immediately
        with patch.object(mgr, "_create_lock_document", return_value=False):
            with patch("time.sleep"):
                result = mgr._acquire_document_based_lock("public", wait_timeout_seconds=0)

        self.assertFalse(result)

    def test_deletes_expired_lock_and_retries(self):
        past = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
        ).isoformat()
        existing = {"expires_at": past}

        mock_container = MagicMock()
        mock_container.read_item.return_value = existing
        # create_lock_document: fails first (lock exists), succeeds after delete
        call_count = {"n": 0}

        def _create():
            call_count["n"] += 1
            return call_count["n"] > 1

        mgr, _, log = _make_locking_manager()
        mgr.lock_container = mock_container

        with patch.object(mgr, "_create_lock_document", side_effect=_create):
            with patch("time.sleep"):
                result = mgr._acquire_document_based_lock("public", wait_timeout_seconds=5)

        self.assertTrue(result)
        mock_container.delete_item.assert_called()


# ===========================================================================
# HistoryManager tests
# ===========================================================================


class TestCosmosDbHistoryManagerInit(unittest.TestCase):
    """Test CosmosDbHistoryManager initialisation."""

    def test_inherits_base_history_manager(self):
        from db.plugins.base_history_manager import BaseHistoryManager
        from db.plugins.cosmosdb.cosmosdb.history_manager import CosmosDbHistoryManager

        self.assertTrue(issubclass(CosmosDbHistoryManager, BaseHistoryManager))

    def test_history_container_is_none_initially(self):
        mgr, _, _ = _make_history_manager()
        self.assertEqual(mgr._history_containers, {})

    def test_connection_manager_set_from_query_executor(self):
        cm = _make_connection_manager()
        mgr, _, _ = _make_history_manager(connection_manager=cm)
        self.assertIs(mgr.connection_manager, cm)


class TestCreateHistoryTable(unittest.TestCase):
    """create_history_table describes the SDK call; it is not runnable DDL."""

    def test_describes_the_sdk_call_and_names_the_container(self):
        mgr, _, _ = _make_history_manager()
        described = mgr.create_history_table("public", "my_history")
        self.assertTrue(described.lstrip().startswith("--"))
        self.assertIn("create_container_if_not_exists", described)
        self.assertIn("my_history", described)

    def test_names_the_partition_key_path(self):
        mgr, _, _ = _make_history_manager()
        described = mgr.create_history_table("public", "dblift_schema_history")
        self.assertIn("/version", described)

    def test_emits_no_pseudo_ddl(self):
        """The old CREATE CONTAINER string looked runnable but never was."""
        mgr, _, _ = _make_history_manager()
        described = mgr.create_history_table("public", "dblift_schema_history").upper()
        self.assertNotIn("CREATE CONTAINER ", described)
        self.assertNotIn("CREATE TABLE", described)


class TestCreateHistoryContainerIfNotExists(unittest.TestCase):
    """Test create_history_container_if_not_exists."""

    def test_uses_existing_container_when_read_succeeds(self):
        mock_existing = MagicMock()
        mock_existing.read.return_value = None  # no exception = container exists
        mock_db = MagicMock()
        mock_db.get_container_client.return_value = mock_existing

        cm = _make_connection_manager(database=mock_db)
        mgr, _, _ = _make_history_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                mgr.create_history_container_if_not_exists("public")

        self.assertIs(mgr._history_containers["dblift_schema_history"], mock_existing)
        mock_db.create_container_if_not_exists.assert_not_called()

    def test_creates_container_when_not_found(self):
        mock_new_container = MagicMock()
        mock_db = MagicMock()
        # read raises 404
        existing_client = MagicMock()
        existing_client.read.side_effect = Exception("not found 404")
        mock_db.get_container_client.return_value = existing_client
        mock_db.create_container_if_not_exists.return_value = mock_new_container

        cm = _make_connection_manager(database=mock_db)
        mgr, _, _ = _make_history_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                mgr.create_history_container_if_not_exists("public")

        mock_db.create_container_if_not_exists.assert_called_once()

    def test_retries_transient_service_unavailable_when_creating_container(self):
        mock_new_container = MagicMock()
        mock_db = MagicMock()
        existing_client = MagicMock()
        existing_client.read.side_effect = Exception("not found 404")
        mock_db.get_container_client.return_value = existing_client
        mock_db.create_container_if_not_exists.side_effect = [
            Exception("ServiceUnavailable"),
            mock_new_container,
        ]

        cm = _make_connection_manager(database=mock_db)
        mgr, _, _ = _make_history_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                mgr.create_history_container_if_not_exists("public")

        self.assertIs(mgr._history_containers["dblift_schema_history"], mock_new_container)
        self.assertEqual(mock_db.create_container_if_not_exists.call_count, 2)

    def test_handles_conflict_error_during_create(self):
        """create_container_if_not_exists raising 'conflict' → get existing client."""
        mock_client = MagicMock()
        mock_db = MagicMock()
        existing_client = MagicMock()
        existing_client.read.side_effect = Exception("not found 404")
        mock_db.get_container_client.return_value = mock_client
        mock_db.create_container_if_not_exists.side_effect = Exception("conflict already exists")

        cm = _make_connection_manager(database=mock_db)
        mgr, _, _ = _make_history_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                mgr.create_history_container_if_not_exists("public")

        self.assertIs(mgr._history_containers["dblift_schema_history"], mock_client)

    def test_creates_connection_when_database_is_none(self):
        mock_db = MagicMock()
        mock_existing = MagicMock()
        mock_existing.read.return_value = None
        mock_db.get_container_client.return_value = mock_existing

        cm = _make_connection_manager(database=None)
        cm.create_connection.side_effect = lambda: setattr(cm, "database", mock_db)

        mgr, _, _ = _make_history_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                mgr.create_history_container_if_not_exists("public")

        cm.create_connection.assert_called_once()

    def test_reraises_on_unexpected_create_error(self):
        mock_db = MagicMock()
        existing_client = MagicMock()
        existing_client.read.side_effect = Exception("not found 404")
        mock_db.get_container_client.return_value = existing_client
        mock_db.create_container_if_not_exists.side_effect = Exception("unexpected storage error")
        mock_db.list_containers.return_value = []

        cm = _make_connection_manager(database=mock_db)
        mgr, _, _ = _make_history_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                with self.assertRaises(Exception):
                    mgr.create_history_container_if_not_exists("public")

    def test_conflict_error_after_genuine_not_found_uses_fallback_client(self):
        """The existence check reports not-found, so creation is attempted;
        creation then reports a conflict, so the container client must be
        fetched via the fallback ``get_container_client`` call and cached."""
        not_found_container = MagicMock()
        not_found_container.read.side_effect = Exception("not found 404")
        conflict_fallback_client = MagicMock()

        mock_db = MagicMock()
        mock_db.get_container_client.side_effect = [
            not_found_container,
            conflict_fallback_client,
        ]
        mock_db.create_container_if_not_exists.side_effect = Exception(
            "Conflict: resource already exists"
        )

        cm = _make_connection_manager(database=mock_db)
        mgr, _, _ = _make_history_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                mgr.create_history_container_if_not_exists("public")

        self.assertIs(mgr._history_containers["dblift_schema_history"], conflict_fallback_client)

    def test_unexpected_create_error_found_via_container_listing(self):
        """When creation fails with an error that isn't a recognised conflict,
        the container is looked up by listing; if found there, the client is
        cached instead of re-raising."""
        not_found_container = MagicMock()
        not_found_container.read.side_effect = Exception("not found 404")
        found_via_listing_client = MagicMock()

        mock_db = MagicMock()
        mock_db.get_container_client.side_effect = [
            not_found_container,
            found_via_listing_client,
        ]
        mock_db.create_container_if_not_exists.side_effect = Exception("unexpected storage hiccup")
        mock_db.list_containers.return_value = [{"id": "dblift_schema_history"}]

        cm = _make_connection_manager(database=mock_db)
        mgr, _, _ = _make_history_manager(connection_manager=cm)

        with patch("azure.cosmos.PartitionKey", MagicMock()):
            with patch("time.sleep"):
                mgr.create_history_container_if_not_exists("public")

        self.assertIs(mgr._history_containers["dblift_schema_history"], found_via_listing_client)


class TestGetAppliedMigrations(unittest.TestCase):
    """Test get_applied_migrations."""

    def test_returns_list_of_migration_records(self):
        items = [
            {
                "script": "V1__init.sql",
                "installed_rank": 1,
                "version": "1",
                "description": "Init",
                "type": "SQL",
                "checksum": "abc",
                "installed_by": "user@host",
                "installed_on": "2024-01-01",
                "execution_time": 100,
                "success": True,
            }
        ]
        mock_container = MagicMock()
        mock_container.query_items.return_value = items

        mgr, cm, _ = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        result = mgr.get_applied_migrations(connection=None, schema="public")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["script"], "V1__init.sql")
        self.assertEqual(result[0]["version"], "1")

    def test_returns_empty_list_when_container_not_found(self):
        mock_container = MagicMock()
        mock_container.query_items.side_effect = Exception("not found 404")

        mgr, _, _ = _make_history_manager()
        mgr.history_container = mock_container

        result = mgr.get_applied_migrations(connection=None, schema="public")

        self.assertEqual(result, [])

    def test_returns_empty_list_on_other_exception(self):
        mock_container = MagicMock()
        mock_container.query_items.side_effect = Exception("network failure")

        mgr, _, log = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        result = mgr.get_applied_migrations(connection=None, schema="public")

        self.assertEqual(result, [])
        log.error.assert_called()

    def test_gets_container_client_when_history_container_is_none(self):
        items = []
        mock_container = MagicMock()
        mock_container.query_items.return_value = items

        cm = _make_connection_manager()
        cm.get_container_client.return_value = mock_container

        mgr, _, _ = _make_history_manager(connection_manager=cm)
        mgr.history_container = None

        result = mgr.get_applied_migrations(connection=None, schema="public")

        cm.get_container_client.assert_called_once()
        self.assertEqual(result, [])

    def test_uses_custom_table_name(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = []

        cm = _make_connection_manager()
        cm.get_container_client.return_value = mock_container

        mgr, _, _ = _make_history_manager(connection_manager=cm)
        mgr.history_container = None

        mgr.get_applied_migrations(connection=None, schema="public", table_name="custom_history")

        cm.get_container_client.assert_called_once_with("custom_history")

    def test_execution_time_defaults_to_zero_when_missing(self):
        items = [{"script": "V1__init.sql", "installed_rank": 1}]
        mock_container = MagicMock()
        mock_container.query_items.return_value = items

        mgr, _, _ = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        result = mgr.get_applied_migrations(connection=None, schema="public")

        self.assertEqual(result[0]["execution_time"], 0)

    def test_success_defaults_to_true_when_missing(self):
        items = [{"script": "V1__init.sql", "installed_rank": 1}]
        mock_container = MagicMock()
        mock_container.query_items.return_value = items

        mgr, _, _ = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        result = mgr.get_applied_migrations(connection=None, schema="public")

        self.assertTrue(result[0]["success"])


class TestRecordMigration(unittest.TestCase):
    """Test record_migration."""

    def _make_mgr_with_container(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = [None]  # SELECT VALUE MAX returns [None]
        mock_container.upsert_item.return_value = None

        mgr, cm, log = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        with patch.object(mgr, "create_history_container_if_not_exists"):
            return mgr, mock_container, log

    def test_upserts_migration_document(self):
        mgr, container, _ = self._make_mgr_with_container()
        migration_info = {
            "script": "V1__init.sql",
            "version": "1",
            "description": "Init",
            "type": "SQL",
            "checksum": "abc",
            "success": True,
            "execution_time": 100,
        }

        with patch.object(mgr, "create_history_container_if_not_exists"):
            mgr.record_migration(connection=None, schema="public", migration_info=migration_info)

        container.upsert_item.assert_called_once()
        doc = container.upsert_item.call_args[1]["body"]
        self.assertEqual(doc["script"], "V1__init.sql")
        self.assertEqual(doc["version"], "1")

    def test_installed_rank_is_1_when_no_existing_migrations(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = [None]  # max rank = None
        mock_container.upsert_item.return_value = None

        mgr, _, _ = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        migration_info = {"script": "V1__init.sql", "version": "1", "type": "SQL"}

        with patch.object(mgr, "create_history_container_if_not_exists"):
            mgr.record_migration(connection=None, schema="public", migration_info=migration_info)

        doc = mock_container.upsert_item.call_args[1]["body"]
        self.assertEqual(doc["installed_rank"], 1)

    def test_installed_rank_increments_from_existing(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = [5]  # max existing rank = 5
        mock_container.upsert_item.return_value = None

        mgr, _, _ = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        migration_info = {"script": "V6__add.sql", "version": "6", "type": "SQL"}

        with patch.object(mgr, "create_history_container_if_not_exists"):
            mgr.record_migration(connection=None, schema="public", migration_info=migration_info)

        doc = mock_container.upsert_item.call_args[1]["body"]
        self.assertEqual(doc["installed_rank"], 6)

    def test_installed_on_uses_provided_datetime(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = [None]
        mock_container.upsert_item.return_value = None

        mgr, _, _ = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        dt = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        migration_info = {
            "script": "V1.sql",
            "version": "1",
            "type": "SQL",
            "installed_on": dt,
        }

        with patch.object(mgr, "create_history_container_if_not_exists"):
            mgr.record_migration(connection=None, schema="public", migration_info=migration_info)

        doc = mock_container.upsert_item.call_args[1]["body"]
        self.assertIn("2024-01-01", doc["installed_on"])

    def test_raises_on_upsert_error(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = [None]
        mock_container.upsert_item.side_effect = Exception("write failed")

        mgr, _, log = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        migration_info = {"script": "V1.sql", "version": "1", "type": "SQL"}

        with patch.object(mgr, "create_history_container_if_not_exists"):
            with self.assertRaises(Exception):
                mgr.record_migration(
                    connection=None, schema="public", migration_info=migration_info
                )

        log.error.assert_called()

    def test_installed_rank_dict_result_handled(self):
        """SELECT VALUE MAX returning a dict (unusual) is handled gracefully."""
        mock_container = MagicMock()
        mock_container.query_items.return_value = [{"installed_rank": 3}]
        mock_container.upsert_item.return_value = None

        mgr, _, _ = _make_history_manager()
        mgr._history_containers["dblift_schema_history"] = mock_container

        migration_info = {"script": "V4.sql", "version": "4", "type": "SQL"}

        with patch.object(mgr, "create_history_container_if_not_exists"):
            mgr.record_migration(connection=None, schema="public", migration_info=migration_info)

        doc = mock_container.upsert_item.call_args[1]["body"]
        self.assertEqual(doc["installed_rank"], 4)

    def test_gets_container_client_when_not_cached(self):
        """If create_history_container_if_not_exists doesn't populate the
        cache (e.g. it's stubbed out), record_migration must fall back to
        fetching the container client directly."""
        mock_container = MagicMock()
        mock_container.query_items.return_value = [None]
        mock_container.upsert_item.return_value = None

        cm = _make_connection_manager()
        cm.get_container_client.return_value = mock_container

        mgr, _, _ = _make_history_manager(connection_manager=cm)
        migration_info = {"script": "V1__init.sql", "version": "1", "type": "SQL"}

        with patch.object(mgr, "create_history_container_if_not_exists"):
            mgr.record_migration(connection=None, schema="public", migration_info=migration_info)

        cm.get_container_client.assert_called_once_with("dblift_schema_history")
        self.assertIs(mgr._history_containers["dblift_schema_history"], mock_container)
        mock_container.upsert_item.assert_called_once()


class TestRepairMigrationHistoryContainerCaching(unittest.TestCase):
    """repair_migration_history must fall back to get_container_client
    when the container for this table_name isn't cached yet."""

    def test_gets_container_client_when_not_cached(self):
        mock_container = MagicMock()
        mock_container.read_item.return_value = {
            "id": "V1__x.sql",
            "checksum": 0,
            "success": True,
        }

        cm = _make_connection_manager()
        cm.get_container_client.return_value = mock_container

        mgr, _, _ = _make_history_manager(connection_manager=cm)

        result = mgr.repair_migration_history(
            connection=None, schema="public", script_name="V1__x.sql", checksum=42
        )

        self.assertTrue(result)
        cm.get_container_client.assert_called_once_with("dblift_schema_history")
        self.assertIs(mgr._history_containers["dblift_schema_history"], mock_container)


class TestDeleteFailedMigrationEntryContainerCaching(unittest.TestCase):
    """delete_failed_migration_entry must fall back to get_container_client
    when the container for this table_name isn't cached yet."""

    def test_gets_container_client_when_not_cached(self):
        mock_container = MagicMock()
        mock_container.query_items.return_value = []

        cm = _make_connection_manager()
        cm.get_container_client.return_value = mock_container

        mgr, _, _ = _make_history_manager(connection_manager=cm)

        removed = mgr.delete_failed_migration_entry(None, "public", "V1__x.sql")

        self.assertEqual(removed, 0)
        cm.get_container_client.assert_called_once_with("dblift_schema_history")
        self.assertIs(mgr._history_containers["dblift_schema_history"], mock_container)


class TestCreateMigrationHistoryTableIfNotExists(unittest.TestCase):
    """Test create_migration_history_table_if_not_exists delegates correctly."""

    def test_delegates_to_create_history_container_if_not_exists(self):
        mgr, _, _ = _make_history_manager()

        with patch.object(mgr, "create_history_container_if_not_exists") as mock_create:
            mgr.create_migration_history_table_if_not_exists(
                connection=None, schema="public", table_name="my_history"
            )

        mock_create.assert_called_once_with("public", "my_history")


if __name__ == "__main__":
    unittest.main()
