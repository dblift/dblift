"""MySQL clean droppable-object enumeration."""

from unittest.mock import MagicMock

from dblift.db.plugins.mysql.provider import MySqlProvider
from dblift.db.provider_interfaces import DroppableObject


def _query_executor_with_rows(rows_by_keyword):
    query_executor = MagicMock()

    def _execute_query(_connection, query, params=None):
        for keyword, rows in rows_by_keyword.items():
            if keyword in query:
                return rows
        return []

    query_executor.execute_query.side_effect = _execute_query
    query_executor.get_schema_qualified_name.side_effect = lambda s, n: f"`{s}`.`{n}`"
    return query_executor


def test_mysql_list_droppable_objects_uses_clean_preview_order_without_dropping():
    provider = object.__new__(MySqlProvider)
    provider.query_executor = _query_executor_with_rows(
        {
            "TRIGGERS": [{"TRIGGER_NAME": "audit_orders"}],
            "VIEWS": [{"TABLE_NAME": "recent_orders"}],
            "TABLES": [{"TABLE_NAME": "orders"}, {"TABLE_NAME": "customers"}],
            "'FUNCTION'": [{"ROUTINE_NAME": "order_total"}],
            "'PROCEDURE'": [{"ROUTINE_NAME": "archive_orders"}],
            "EVENTS": [{"EVENT_NAME": "nightly_archive"}],
        }
    )
    provider.log = MagicMock()
    provider._ensure_connection = MagicMock(return_value=MagicMock())

    objects = provider.list_droppable_objects("testdb")

    assert objects == [
        DroppableObject(
            name="foreign_key_checks_off",
            object_type="clean_control",
            drop_sql="SET FOREIGN_KEY_CHECKS = 0",
            record_result=False,
        ),
        DroppableObject(
            name="audit_orders",
            object_type="trigger",
            drop_sql="DROP TRIGGER IF EXISTS `testdb`.`audit_orders`",
        ),
        DroppableObject(
            name="recent_orders",
            object_type="view",
            drop_sql="DROP VIEW IF EXISTS `testdb`.`recent_orders`",
        ),
        DroppableObject(
            name="orders",
            object_type="table",
            drop_sql="DROP TABLE IF EXISTS `testdb`.`orders`",
        ),
        DroppableObject(
            name="customers",
            object_type="table",
            drop_sql="DROP TABLE IF EXISTS `testdb`.`customers`",
        ),
        DroppableObject(
            name="order_total",
            object_type="function",
            drop_sql="DROP FUNCTION IF EXISTS `testdb`.`order_total`",
        ),
        DroppableObject(
            name="archive_orders",
            object_type="procedure",
            drop_sql="DROP PROCEDURE IF EXISTS `testdb`.`archive_orders`",
        ),
        DroppableObject(
            name="nightly_archive",
            object_type="event",
            drop_sql="DROP EVENT IF EXISTS `testdb`.`nightly_archive`",
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
