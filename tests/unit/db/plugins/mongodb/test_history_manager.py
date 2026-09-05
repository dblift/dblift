"""``MongoDbHistoryManager`` — migration history as documents.

The critical method is delete_failed_migration_entry: repair calls it to
clear a failed row so migrate can retry. Inheriting the relational default
would emit a SQL DELETE, which on MongoDB raises — and the migration would
be permanently unretryable.
"""

import datetime
from unittest.mock import MagicMock

from dblift.db.plugins.mongodb.mongodb import MongoDbHistoryManager


def _manager(documents=None):
    query_executor = MagicMock()
    query_executor.list_documents.return_value = list(documents or [])
    query_executor.delete_document.return_value = 1
    schema_operations = MagicMock()
    manager = MongoDbHistoryManager(query_executor, schema_operations, config=MagicMock())
    return manager, query_executor, schema_operations


def test_history_collection_name():
    manager, _, _ = _manager()
    assert manager.HISTORY_CONTAINER_NAME == "dblift_schema_history"


def test_create_provisions_the_collection():
    manager, _, schema_operations = _manager()
    manager.create_migration_history_table_if_not_exists(None, "ignored")
    schema_operations.create_collection_if_not_exists.assert_called_once_with(
        "dblift_schema_history"
    )


def _framework_migration_info(**overrides):
    """Match the exact key set ``MigrationHistoryManager.record_migration``
    sends — no ``installed_rank``. See
    ``core/migration/history/migration_history_manager.py``."""
    info = {
        "script": "V1_0_0__create_users.py",
        "version": "1.0.0",
        "description": "create users",
        "type": "PYTHON",
        "checksum": 123456,
        "success": True,
        "execution_time": 42,
        "installed_by": "app",
    }
    info.update(overrides)
    return info


def test_record_migration_stamps_installed_on_when_the_caller_omits_it():
    """The framework leaves ``installed_on`` out so relational history tables
    fall back to their column default. A collection has no default, so the
    manager must stamp the apply time itself or ``info`` shows an empty
    Installed On column for every MongoDB migration."""
    manager, query_executor, _ = _manager()
    before = datetime.datetime.now(datetime.timezone.utc)
    manager.record_migration(None, "ignored", _framework_migration_info())
    _, document = query_executor.upsert_document.call_args.args
    installed_on = document["installed_on"]
    assert isinstance(installed_on, datetime.datetime)
    assert installed_on.tzinfo is not None
    assert before <= installed_on <= datetime.datetime.now(datetime.timezone.utc)


def test_record_migration_keeps_a_caller_supplied_installed_on():
    """import-flyway carries the original apply date and must not have it
    replaced by the import time."""
    manager, query_executor, _ = _manager()
    manager.record_migration(
        None, "ignored", _framework_migration_info(installed_on="2026-01-01T00:00:00")
    )
    _, document = query_executor.upsert_document.call_args.args
    assert document["installed_on"] == "2026-01-01T00:00:00"


def test_record_writes_a_document_keyed_by_installed_rank():
    """``installed_rank`` is assigned by the manager itself, the MongoDB-native
    equivalent of an auto-increment column — the real framework caller never
    supplies it (see ``_framework_migration_info``)."""
    manager, query_executor, _ = _manager()
    manager.record_migration(None, "ignored", _framework_migration_info())
    collection, document = query_executor.upsert_document.call_args.args
    assert collection == "dblift_schema_history"
    assert document["_id"] == "1"
    assert document["installed_rank"] == 1
    assert document["script"] == "V1_0_0__create_users.py"
    assert document["success"] is True


def test_record_migration_assigns_sequential_ranks_without_a_caller_supplied_rank():
    """Regression test for a crash where ``record_migration`` read
    ``migration_info["installed_rank"]`` — a key the real framework caller
    never provides — and raised ``KeyError`` on the first migration."""
    manager, query_executor, _ = _manager()

    written = []

    def _record_upsert(collection, document):
        written.append(dict(document))
        return document

    query_executor.upsert_document.side_effect = _record_upsert

    def _list_documents(collection):
        return list(written)

    query_executor.list_documents.side_effect = _list_documents

    manager.record_migration(None, "ignored", _framework_migration_info(script="V1.py"))
    manager.record_migration(None, "ignored", _framework_migration_info(script="V2.py"))

    ranks = [doc["installed_rank"] for doc in written]
    assert ranks == [1, 2]
    assert [doc["_id"] for doc in written] == ["1", "2"]


def test_record_migration_ignores_a_caller_supplied_installed_rank():
    """Nothing in the contract promises a caller-supplied rank is honored —
    the manager always computes its own from the stored maximum."""
    manager, query_executor, _ = _manager(
        [{"_id": "5", "installed_rank": 5, "script": "V5.py", "success": True}]
    )
    manager.record_migration(
        None, "ignored", _framework_migration_info(installed_rank=999, script="V6.py")
    )
    _collection, document = query_executor.upsert_document.call_args.args
    assert document["installed_rank"] == 6
    assert document["_id"] == "6"


def test_record_undo_computes_its_own_rank_too():
    """``record_undo`` is inherited from ``BaseHistoryManager`` and calls
    ``self.record_migration(...)`` — the same overridden method, so the same
    fix that stops ``record_migration`` from crashing on a missing
    ``installed_rank`` also fixes undo history, which previously failed
    silently (the base implementation swallows the KeyError and returns
    False)."""
    manager, query_executor, _ = _manager()
    result = manager.record_undo(None, "ignored", "1.0.0")
    assert result is True
    _collection, document = query_executor.upsert_document.call_args.args
    assert document["installed_rank"] == 1
    assert document["_id"] == "1"


def test_applied_migrations_are_ordered_by_installed_rank():
    manager, _, _ = _manager(
        [
            {"_id": "2", "installed_rank": 2, "script": "V2.py", "success": True},
            {"_id": "1", "installed_rank": 1, "script": "V1.py", "success": True},
        ]
    )
    ranks = [row["installed_rank"] for row in manager.get_applied_migrations(None, "ignored")]
    assert ranks == [1, 2]


def test_applied_migrations_drop_the_document_id():
    """``_id`` is storage bookkeeping; the framework's row shape has no such
    column and would carry it into comparisons."""
    manager, _, _ = _manager([{"_id": "1", "installed_rank": 1, "script": "V1.py"}])
    assert "_id" not in manager.get_applied_migrations(None, "ignored")[0]


def test_delete_failed_removes_only_the_failed_document():
    manager, query_executor, _ = _manager(
        [
            {"_id": "1", "script": "V1.py", "success": False},
            {"_id": "2", "script": "V1.py", "success": True},
            {"_id": "3", "script": "V2.py", "success": False},
        ]
    )
    removed = manager.delete_failed_migration_entry(None, "ignored", "V1.py")

    assert removed == 1
    query_executor.delete_document.assert_called_once_with("dblift_schema_history", "1")


def test_delete_failed_returns_zero_when_nothing_matches():
    manager, query_executor, _ = _manager([{"_id": "2", "script": "V1.py", "success": True}])
    assert manager.delete_failed_migration_entry(None, "ignored", "V1.py") == 0
    query_executor.delete_document.assert_not_called()


def test_delete_failed_is_not_the_inherited_sql_version():
    """Regression guard: if this ever resolves to BaseHistoryManager's
    implementation, repair on MongoDB breaks and a failed migration can
    never be retried."""
    from dblift.db.plugins.base_history_manager import BaseHistoryManager

    assert (
        MongoDbHistoryManager.delete_failed_migration_entry
        is not BaseHistoryManager.delete_failed_migration_entry
    )


def test_repair_updates_the_checksum_in_place():
    manager, query_executor, _ = _manager(
        [{"_id": "1", "script": "V1.py", "checksum": 111, "success": True}]
    )
    result = manager.repair_migration_history(None, "ignored", "V1.py", 222)
    assert result is True
    _collection, document = query_executor.upsert_document.call_args.args
    assert document["checksum"] == 222
    assert document["_id"] == "1"


def test_create_history_table_returns_a_description_not_ddl():
    manager, _, _ = _manager()
    rendered = manager.create_history_table("ignored", "dblift_schema_history")
    assert "CREATE TABLE" not in rendered.upper()
