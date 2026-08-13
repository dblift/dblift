"""``MongoDbSchemaOperations`` — collections through the driver, no DDL."""

from unittest.mock import MagicMock

from db.plugins.mongodb.mongodb import MongoDbSchemaOperations


def _operations(collection_names=None):
    query_executor = MagicMock()
    database = MagicMock()
    database.list_collection_names.return_value = list(collection_names or [])
    query_executor.connection_manager.database = database
    query_executor.connection_manager.create_connection.return_value = database
    return MongoDbSchemaOperations(query_executor), database


def test_lists_every_collection():
    operations, _ = _operations(["users", "orders"])
    assert sorted(operations.list_collections()) == ["orders", "users"]


def test_dblift_collections_are_listed_too():
    """Unfiltered by design — clean drops dblift's own storage as well, the
    same way the Cosmos DB plugin does."""
    operations, _ = _operations(["users", "dblift_schema_history", "dblift_migration_lock"])
    assert sorted(operations.list_collections()) == [
        "dblift_migration_lock",
        "dblift_schema_history",
        "users",
    ]


def test_collection_exists_checks_the_real_list():
    operations, _ = _operations(["users"])
    assert operations.collection_exists("users") is True
    assert operations.collection_exists("absent") is False


def test_collection_exists_sees_dblift_collections():
    """History-table probing depends on a truthful answer here."""
    operations, _ = _operations(["dblift_schema_history"])
    assert operations.collection_exists("dblift_schema_history") is True


def test_create_is_idempotent():
    operations, database = _operations(["users"])
    operations.create_collection_if_not_exists("users")
    database.create_collection.assert_not_called()


def test_create_makes_a_missing_collection():
    operations, database = _operations([])
    operations.create_collection_if_not_exists("users")
    database.create_collection.assert_called_once_with("users")


def test_drop_reports_whether_it_removed_anything():
    operations, database = _operations(["users"])
    assert operations.drop_collection("users") is True
    database.drop_collection.assert_called_once_with("users")

    operations, database = _operations([])
    assert operations.drop_collection("absent") is False
    database.drop_collection.assert_not_called()


def test_clean_drops_every_collection():
    """Clean returns the database to empty — dblift's own storage included."""
    operations, database = _operations(["users", "orders", "dblift_schema_history"])
    summary = operations.clean_schema(None, "ignored")

    dropped = sorted(call.args[0] for call in database.drop_collection.call_args_list)
    assert dropped == ["dblift_schema_history", "orders", "users"]
    assert len(summary.objects) == 3


def test_clean_records_the_driver_call_it_made():
    """``statements`` is an audit line, not executable SQL — nothing routes it
    back through a statement executor."""
    operations, _ = _operations(["users"])
    summary = operations.clean_schema(None, "ignored")
    assert summary.statements == ["database.drop_collection('users')"]


def test_clean_preview_drops_nothing():
    operations, database = _operations(["users"])
    summary = operations.get_clean_preview("ignored")
    database.drop_collection.assert_not_called()
    assert len(summary.objects) == 1


def test_clean_continues_past_a_failing_drop():
    """One undroppable collection must not abandon the rest."""
    operations, database = _operations(["a", "b"])
    database.drop_collection.side_effect = [Exception("locked"), None]
    summary = operations.clean_schema(None, "ignored")
    assert len(summary.objects) == 1
    assert len(summary.errors) == 1


def test_list_droppable_collections_excludes_system_namespace():
    """``system.views`` is server bookkeeping, not user schema — and dropping
    it first destroys every view definition before clean reaches them, which
    is the actual mechanism behind the "drop a view, get a spurious failure"
    bug. Excluding anything starting with the reserved ``system.`` prefix
    removes the cause."""
    operations, _ = _operations(["users", "system.views", "system.js"])
    assert operations.list_droppable_collections() == ["users"]


def test_list_droppable_collections_keeps_names_that_merely_contain_system_dot():
    """``system.`` is a reserved *prefix*, not a banned substring — MongoDB
    itself accepts a collection named ``orders_system.log`` (it only refuses
    creation under the leading ``system.`` prefix). A substring match would
    silently spare real user data from a full-reset ``clean``, which is a
    worse failure than the one this filter exists to fix, because it is
    silent."""
    operations, _ = _operations(["orders_system.log", "system.views"])
    assert operations.list_droppable_collections() == ["orders_system.log"]


def test_list_droppable_collections_keeps_dblift_collections():
    """dblift's own storage is user-visible state dblift created, not server
    bookkeeping — clean's contract is a full reset, so it must still go."""
    operations, _ = _operations(["dblift_schema_history", "dblift_migration_lock", "users"])
    assert sorted(operations.list_droppable_collections()) == [
        "dblift_migration_lock",
        "dblift_schema_history",
        "users",
    ]


def test_clean_schema_skips_system_namespace_collections():
    operations, database = _operations(["users", "system.views"])
    summary = operations.clean_schema(None, "ignored")

    dropped = [call.args[0] for call in database.drop_collection.call_args_list]
    assert dropped == ["users"]
    assert len(summary.objects) == 1


def test_clean_preview_skips_system_namespace_collections():
    operations, _ = _operations(["users", "system.views"])
    summary = operations.get_clean_preview("ignored")
    names = [obj.name for obj in summary.objects]
    assert names == ["users"]


def test_database_version_reads_build_info():
    operations, database = _operations([])
    database.command.return_value = {"version": "7.0.5"}
    assert operations.get_database_version(None) == "7.0.5"
    database.command.assert_called_once_with("buildInfo")


def test_database_version_falls_back_when_unavailable():
    operations, database = _operations([])
    database.command.side_effect = Exception("not authorized")
    assert operations.get_database_version(None) == "unknown"


def test_create_schema_is_noop():
    """MongoDB has no schema layer; create_schema_if_not_exists is a no-op."""
    operations, database = _operations([])
    operations.create_schema_if_not_exists(None, "test_schema")
    assert database.method_calls == []


def test_set_current_schema_is_noop():
    """MongoDB has no schema layer; set_current_schema is a no-op."""
    operations, database = _operations([])
    operations.set_current_schema(None, "test_schema")
    assert database.method_calls == []


def test_get_tables_returns_collections():
    """get_tables should return the list of collections."""
    operations, _ = _operations(["users", "orders"])
    tables = operations.get_tables(None, "ignored")
    assert sorted(tables) == ["orders", "users"]


def test_get_schemas_returns_empty_list():
    """get_schemas returns empty list since MongoDB has no schemas."""
    operations, _ = _operations([])
    schemas = operations.get_schemas(None)
    assert schemas == []


def test_get_columns_query_returns_find_command():
    """get_columns_query returns a MongoDB find query."""
    operations, _ = _operations([])
    query = operations.get_columns_query("ignored_schema", "users")
    assert query == "db.users.findOne()"


def test_get_add_column_sql_returns_comment():
    """get_add_column_sql returns a comment since MongoDB is schema-less."""
    operations, _ = _operations([])
    sql = operations.get_add_column_sql("ignored_schema", "users", "email", "string")
    assert "schema-less" in sql
    assert "users.email" in sql


def test_get_parameter_placeholders():
    """get_parameter_placeholders returns comma-separated question marks."""
    operations, _ = _operations([])
    assert operations.get_parameter_placeholders(1) == "?"
    assert operations.get_parameter_placeholders(3) == "?, ?, ?"
    assert operations.get_parameter_placeholders(0) == ""
