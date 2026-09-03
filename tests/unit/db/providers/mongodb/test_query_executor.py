"""``MongoDbQueryExecutor`` — no string statements, documents only."""

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import NoSqlQueryLanguageUnsupportedError
from dblift.db.plugins.mongodb.mongodb import MongoDbQueryExecutor


def _executor():
    connection_manager = MagicMock()
    return MongoDbQueryExecutor(connection_manager), connection_manager


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM users",
        "INSERT INTO users VALUES (1)",
        "CREATE TABLE users (id INT)",
        "db.users.find({})",
        "",
    ],
)
def test_every_statement_is_rejected(statement):
    """Reads too, not just writes — MongoDB has no string query language,
    so there is nothing a string could correctly mean."""
    executor, _ = _executor()
    with pytest.raises(NoSqlQueryLanguageUnsupportedError):
        executor.execute_statement(statement)
    with pytest.raises(NoSqlQueryLanguageUnsupportedError):
        executor.execute_query(statement)


def test_rejection_names_the_code_and_the_remedy():
    executor, _ = _executor()
    with pytest.raises(NoSqlQueryLanguageUnsupportedError) as excinfo:
        executor.execute_query("SELECT 1")
    message = str(excinfo.value)
    assert "DBLIFT-NOSQL-002" in message
    assert "context.db" in message


def test_upsert_replaces_by_id():
    executor, connection_manager = _executor()
    collection = MagicMock()
    connection_manager.get_collection.return_value = collection
    document = {"_id": "abc", "value": 1}

    assert executor.upsert_document("things", document) == document

    connection_manager.get_collection.assert_called_once_with("things")
    collection.replace_one.assert_called_once_with({"_id": "abc"}, document, upsert=True)


def test_delete_returns_the_deleted_count():
    executor, connection_manager = _executor()
    collection = MagicMock()
    collection.delete_one.return_value = MagicMock(deleted_count=1)
    connection_manager.get_collection.return_value = collection

    assert executor.delete_document("things", "abc") == 1
    collection.delete_one.assert_called_once_with({"_id": "abc"})


def test_list_documents_returns_a_list():
    executor, connection_manager = _executor()
    collection = MagicMock()
    collection.find.return_value = iter([{"_id": "a"}, {"_id": "b"}])
    connection_manager.get_collection.return_value = collection

    assert executor.list_documents("things") == [{"_id": "a"}, {"_id": "b"}]
    collection.find.assert_called_once_with({})


def test_list_documents_passes_a_filter():
    executor, connection_manager = _executor()
    collection = MagicMock()
    collection.find.return_value = iter([])
    connection_manager.get_collection.return_value = collection

    executor.list_documents("things", {"success": False})
    collection.find.assert_called_once_with({"success": False})


def test_qualified_name_is_the_bare_collection_name():
    """No schema layer — prefixing would produce a collection that does not
    exist."""
    executor, _ = _executor()
    assert executor.get_schema_qualified_name("public", "users") == "users"
