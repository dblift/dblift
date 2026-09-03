"""MariaDB clean droppable-object enumeration tests."""

from unittest.mock import MagicMock

from dblift.db.plugins.mariadb.provider import MariadbProvider
from dblift.db.provider_interfaces import DroppableObject


def _query_executor_with_rows(rows_by_keyword):
    query_executor = MagicMock()

    def _execute_query(connection, query, params=None):
        for keyword, rows in rows_by_keyword.items():
            if keyword in query:
                return rows
        return []

    query_executor.execute_query.side_effect = _execute_query
    query_executor.get_schema_qualified_name.side_effect = lambda schema, name: (
        f"`{schema}`.`{name}`"
    )
    return query_executor


def test_list_droppable_objects_returns_clean_preview_order_without_dropping() -> None:
    """MariaDB returns droppable objects in the same order as clean preview."""
    provider = object.__new__(MariadbProvider)
    provider.query_executor = _query_executor_with_rows(
        {
            "TRIGGERS": [{"TRIGGER_NAME": "audit_trg"}],
            "VIEWS": [{"TABLE_NAME": "active_users_v"}],
            "TABLES": [{"TABLE_NAME": "users"}],
            "'FUNCTION'": [{"ROUTINE_NAME": "calc_total"}],
            "'PROCEDURE'": [{"ROUTINE_NAME": "do_thing"}],
            "EVENTS": [{"EVENT_NAME": "nightly_purge"}],
        }
    )
    provider.log = MagicMock()
    provider._ensure_connection = MagicMock(return_value=MagicMock())

    objects = provider.list_droppable_objects("app")

    assert objects == [
        DroppableObject(
            name="foreign_key_checks_off",
            object_type="clean_control",
            drop_sql="SET FOREIGN_KEY_CHECKS = 0",
            record_result=False,
        ),
        DroppableObject(
            name="audit_trg",
            object_type="trigger",
            drop_sql="DROP TRIGGER IF EXISTS `app`.`audit_trg`",
        ),
        DroppableObject(
            name="active_users_v",
            object_type="view",
            drop_sql="DROP VIEW IF EXISTS `app`.`active_users_v`",
        ),
        DroppableObject(
            name="users",
            object_type="table",
            drop_sql="DROP TABLE IF EXISTS `app`.`users`",
        ),
        DroppableObject(
            name="calc_total",
            object_type="function",
            drop_sql="DROP FUNCTION IF EXISTS `app`.`calc_total`",
        ),
        DroppableObject(
            name="do_thing",
            object_type="procedure",
            drop_sql="DROP PROCEDURE IF EXISTS `app`.`do_thing`",
        ),
        DroppableObject(
            name="nightly_purge",
            object_type="event",
            drop_sql="DROP EVENT IF EXISTS `app`.`nightly_purge`",
        ),
        DroppableObject(
            name="foreign_key_checks_on",
            object_type="clean_control",
            drop_sql="SET FOREIGN_KEY_CHECKS = 1",
            record_result=False,
        ),
    ]
    provider.query_executor.execute_statement.assert_not_called()
    provider._ensure_connection.assert_called_once_with()
