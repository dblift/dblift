"""``clean`` must delete Cosmos containers through the SDK, never via SQL.

Clean enumerates droppable objects and drops them one by one. For
relational providers that means executing ``obj.drop_sql``; Cosmos has no
executable DROP, so its provider overrides :meth:`drop_object`. Without
that override the deletion would reach the query executor and raise
``NoSqlWriteNotSupportedError``, leaving the account untouched while clean
reported only warnings.
"""

from unittest.mock import MagicMock

import pytest

from dblift.db.plugins.cosmosdb.provider import CosmosDbProvider
from dblift.db.provider_interfaces import DroppableObject


def _provider() -> CosmosDbProvider:
    provider = CosmosDbProvider.__new__(CosmosDbProvider)
    provider.schema_operations = MagicMock()
    provider.query_executor = MagicMock()
    return provider


def test_droppable_objects_do_not_advertise_executable_sql():
    provider = _provider()
    provider.schema_operations.list_containers.return_value = ["users", "orders"]

    objects = provider.list_droppable_objects("default")

    assert [o.name for o in objects] == ["users", "orders"]
    for obj in objects:
        assert "DROP CONTAINER" not in obj.drop_sql
        assert "delete_container" in obj.drop_sql


def test_drop_object_calls_the_sdk_and_never_the_query_executor():
    provider = _provider()
    provider.schema_operations.delete_container.return_value = True

    provider.drop_object(DroppableObject(name="users", object_type="CONTAINER", drop_sql="x"))

    provider.schema_operations.delete_container.assert_called_once_with("users")
    provider.query_executor.execute_statement.assert_not_called()


def test_drop_object_raises_when_the_sdk_reports_failure():
    provider = _provider()
    provider.schema_operations.delete_container.return_value = False

    with pytest.raises(RuntimeError, match="users"):
        provider.drop_object(DroppableObject(name="users", object_type="CONTAINER", drop_sql="x"))


def test_clean_command_drops_through_the_provider_hook():
    """The command must call ``drop_object``, not ``execute_statement``."""
    import inspect

    from dblift.core.migration.commands.clean_command import CleanCommand

    source = inspect.getsource(CleanCommand)
    assert "self.provider.drop_object(obj)" in source
    assert "self.provider.execute_statement(obj.drop_sql)" not in source
