from unittest.mock import MagicMock

import pytest

from db.plugins.sqlserver.provider import SqlServerProvider
from db.provider_interfaces import DroppableObject


def _provider_with_catalog_rows():
    provider = object.__new__(SqlServerProvider)
    connection = object()
    provider._ensure_connection = MagicMock(return_value=connection)
    provider.execute_statement = MagicMock()
    provider.log = MagicMock()
    provider.query_executor = MagicMock()
    provider.query_executor.get_schema_qualified_name.side_effect = (
        lambda schema, name: f"[{schema}].[{name}]"
    )

    def execute_query(query_connection, sql, params=None):
        assert query_connection is connection
        # Full-text catalogs are not schema-owned, so that query alone is
        # unparameterized — every other query here is scoped to "dbo".
        if "sys.fulltext_catalogs" in sql:
            assert params is None
        else:
            assert params == ["dbo"]
        if "sys.foreign_keys" in sql:
            return [{"constraint_name": "fk_orders_customer", "table_name": "orders"}]
        if "INFORMATION_SCHEMA.VIEWS" in sql:
            return [{"view_name": "sales_view"}]
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return [{"table_name": "orders"}]
        if "temporal_type" in sql:
            return []
        if "INFORMATION_SCHEMA.ROUTINES" in sql:
            return [
                {"routine_name": "rebuild_stats", "routine_type": "PROCEDURE"},
                {"routine_name": "calc_total", "routine_type": "FUNCTION"},
            ]
        if "sys.sequences" in sql:
            return [{"sequence_name": "order_seq"}]
        if "sys.types" in sql:
            return [{"type_name": "EmailAddress"}]
        if "sys.synonyms" in sql:
            return [{"synonym_name": "remote_orders"}]
        if "sys.fulltext_catalogs" in sql:
            return [{"catalog_name": "ft_catalog"}]
        raise AssertionError(f"Unexpected query: {sql}")

    provider.query_executor.execute_query.side_effect = execute_query
    return provider


@pytest.mark.unit
def test_sqlserver_provider_lists_droppable_objects_in_clean_order():
    provider = _provider_with_catalog_rows()

    objects = provider.list_droppable_objects("dbo")

    assert objects == [
        DroppableObject(
            name="fk_orders_customer",
            object_type="foreign_key",
            drop_sql="ALTER TABLE [dbo].[orders] DROP CONSTRAINT [fk_orders_customer]",
        ),
        DroppableObject(
            name="sales_view",
            object_type="view",
            drop_sql="DROP VIEW [dbo].[sales_view]",
        ),
        DroppableObject(
            name="orders",
            object_type="table",
            drop_sql="DROP TABLE [dbo].[orders]",
        ),
        DroppableObject(
            name="rebuild_stats",
            object_type="procedure",
            drop_sql="DROP PROCEDURE [dbo].[rebuild_stats]",
        ),
        DroppableObject(
            name="calc_total",
            object_type="function",
            drop_sql="DROP FUNCTION [dbo].[calc_total]",
        ),
        DroppableObject(
            name="order_seq",
            object_type="sequence",
            drop_sql="DROP SEQUENCE [dbo].[order_seq]",
        ),
        DroppableObject(
            name="EmailAddress",
            object_type="type",
            drop_sql="DROP TYPE [dbo].[EmailAddress]",
        ),
        DroppableObject(
            name="remote_orders",
            object_type="synonym",
            drop_sql="DROP SYNONYM [dbo].[remote_orders]",
        ),
        DroppableObject(
            name="ft_catalog",
            object_type="fulltext_catalog",
            drop_sql="DROP FULLTEXT CATALOG [ft_catalog]",
        ),
    ]
    provider.execute_statement.assert_not_called()
    provider.query_executor.execute_statement.assert_not_called()
