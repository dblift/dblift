"""``MongoDbProvider`` — component wiring and the document contract."""

from unittest.mock import MagicMock

import pytest

from config import DbliftConfig
from core.exceptions import NoSqlQueryLanguageUnsupportedError
from db.plugins.mongodb.config import MongoDbConfig
from db.plugins.mongodb.provider import MongoDbProvider
from db.plugins.nosql_base import DocumentStoreProvider


def _provider():
    config = MagicMock(spec=DbliftConfig)
    config.database = MongoDbConfig(
        type="mongodb", url="mongodb://localhost:27017", database="appdb"
    )
    return MongoDbProvider(config)


def test_canonical_dialect_key():
    assert MongoDbProvider.canonical_dialect_key == "mongodb"


def test_components_are_wired():
    provider = _provider()
    for attribute in (
        "connection_manager",
        "query_executor",
        "schema_operations",
        "history_manager",
        "locking_manager",
        "snapshot_manager",
    ):
        assert getattr(provider, attribute) is not None


def test_satisfies_the_document_store_contract():
    """A caller that needs document-level storage selects on this
    capability, not on a dialect name."""
    assert isinstance(_provider(), DocumentStoreProvider)


def test_connection_manager_exposes_the_migration_context_handles():
    """MigrationContext.db / .raw_client read these attribute names."""
    provider = _provider()
    assert hasattr(provider.connection_manager, "database")
    assert hasattr(provider.connection_manager, "client")


def test_statements_are_rejected():
    provider = _provider()
    with pytest.raises(NoSqlQueryLanguageUnsupportedError):
        provider.execute_statement("DELETE FROM dblift_schema_history")
    with pytest.raises(NoSqlQueryLanguageUnsupportedError):
        provider.execute_query("SELECT 1")


def test_transactions_are_not_claimed():
    provider = _provider()
    assert provider.supports_transactions() is False
    assert provider.supports_transactional_ddl() is False


def test_transaction_calls_are_no_ops():
    """The framework calls these unconditionally; they must not raise."""
    provider = _provider()
    provider.begin_transaction()
    provider.commit_transaction()
    provider.rollback_transaction()


def test_display_url_is_masked():
    config = MagicMock(spec=DbliftConfig)
    config.database = MongoDbConfig(
        type="mongodb", url="mongodb://app:s3cret@localhost:27017", database="appdb"
    )
    assert "s3cret" not in MongoDbProvider(config).get_display_url()


def test_clean_delegates_to_schema_operations():
    provider = _provider()
    provider.schema_operations = MagicMock()
    provider.clean_schema("ignored")
    provider.schema_operations.clean_schema.assert_called_once()


def test_upsert_native_item_writes_a_document():
    provider = _provider()
    provider.query_executor = MagicMock()
    document = {"_id": "s1", "checksum": "abc"}
    provider.upsert_native_item("dblift_schema_snapshots", document)
    provider.query_executor.upsert_document.assert_called_once_with(
        "dblift_schema_snapshots", document
    )


def test_delete_native_item_ignores_the_partition_key():
    """MongoDB has no partitioning; the parameter exists for contract parity."""
    provider = _provider()
    provider.query_executor = MagicMock()
    provider.delete_native_item("dblift_schema_snapshots", "s1", partition_key="s1")
    provider.query_executor.delete_document.assert_called_once_with("dblift_schema_snapshots", "s1")


def test_list_native_items_reads_the_collection():
    provider = _provider()
    provider.query_executor = MagicMock()
    provider.query_executor.list_documents.return_value = [{"_id": "s1"}]
    assert provider.list_native_items("dblift_schema_snapshots") == [{"_id": "s1"}]


def test_provider_is_concrete_not_abstract():
    """Every ABC-declared abstract method must be implemented, or this class
    cannot be constructed at all — the failure mode this test exists to
    catch is a TypeError at import/instantiation time, not a runtime bug."""
    assert MongoDbProvider.__abstractmethods__ == frozenset()


def test_record_migration_delegates_to_history_manager():
    provider = _provider()
    provider.history_manager = MagicMock()
    provider.record_migration("public", {"installed_rank": 1}, "dblift_schema_history")
    provider.history_manager.record_migration.assert_called_once_with(
        None, "public", {"installed_rank": 1}, "dblift_schema_history"
    )


def test_get_applied_migrations_delegates_to_history_manager():
    provider = _provider()
    provider.history_manager = MagicMock()
    provider.history_manager.get_applied_migrations.return_value = [{"installed_rank": 1}]
    result = provider.get_applied_migrations("public", "dblift_schema_history")
    assert result == [{"installed_rank": 1}]
    provider.history_manager.get_applied_migrations.assert_called_once_with(
        None, "public", "dblift_schema_history"
    )


def test_create_migration_history_table_delegates():
    provider = _provider()
    provider.history_manager = MagicMock()
    provider.create_migration_history_table_if_not_exists("public")
    provider.history_manager.create_migration_history_table_if_not_exists.assert_called_once_with(
        None, "public", False, "dblift_schema_history"
    )


def test_acquire_and_release_lock_delegate_to_locking_manager():
    provider = _provider()
    provider.locking_manager = MagicMock()
    provider.locking_manager.acquire_migration_lock.return_value = True
    provider.locking_manager.release_migration_lock.return_value = True

    assert provider.acquire_migration_lock("public", wait_timeout_seconds=5) is True
    provider.locking_manager.acquire_migration_lock.assert_called_once_with("public", 5)

    assert provider.release_migration_lock("public") is True
    provider.locking_manager.release_migration_lock.assert_called_once_with("public")


def test_create_migration_lock_table_delegates():
    provider = _provider()
    provider.locking_manager = MagicMock()
    provider.create_migration_lock_table_if_not_exists("public")
    provider.locking_manager.create_migration_lock_container_if_not_exists.assert_called_once_with(
        "public"
    )


def test_get_schema_qualified_name_returns_the_bare_name():
    provider = _provider()
    assert provider.get_schema_qualified_name("public", "users") == "users"


def test_delete_failed_migration_entry_is_inherited_not_reimplemented():
    """BaseProvider's default already delegates to self.history_manager by
    attribute-name convention — this class must not shadow it with a
    redundant override."""
    from db.base_provider import BaseProvider

    assert (
        MongoDbProvider.delete_failed_migration_entry is BaseProvider.delete_failed_migration_entry
    )
