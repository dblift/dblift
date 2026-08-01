from unittest.mock import MagicMock

import pytest

from db.plugins.sqlserver.provider import SqlServerProvider
from db.plugins.sqlserver.sqlserver.schema_operations import SqlServerSchemaOperations


def _make_query_executor():
    query_executor = MagicMock()
    query_executor.get_schema_qualified_name.side_effect = (
        lambda schema, name: f"[{schema}].[{name}]"
    )

    def execute_query(_connection, query, params=None):
        if "sys.foreign_keys" in query:
            return [{"constraint_name": "fk_orders_customer", "table_name": "orders"}]
        if "INFORMATION_SCHEMA.VIEWS" in query:
            return [{"view_name": "sales_view"}]
        if "INFORMATION_SCHEMA.TABLES" in query:
            return [{"table_name": "orders"}]
        if "temporal_type" in query:
            return []
        if "INFORMATION_SCHEMA.ROUTINES" in query:
            return [
                {"routine_name": "rebuild_stats", "routine_type": "PROCEDURE"},
                {"routine_name": "calc_total", "routine_type": "FUNCTION"},
            ]
        if "sys.sequences" in query:
            return [{"sequence_name": "order_seq"}]
        if "sys.types" in query:
            return [{"type_name": "EmailAddress"}]
        if "sys.synonyms" in query:
            return [{"synonym_name": "remote_orders"}]
        if "sys.fulltext_catalogs" in query:
            return [{"catalog_name": "ft_catalog"}]
        raise AssertionError(f"Unexpected query: {query}")

    query_executor.execute_query.side_effect = execute_query
    return query_executor


@pytest.mark.unit
def test_sqlserver_clean_preview_matches_explicit_clean_objects():
    connection = object()
    operations = SqlServerSchemaOperations(_make_query_executor(), MagicMock())

    preview = operations.get_clean_preview(connection, "dbo")
    executed = operations.clean_schema(connection, "dbo")

    preview_objects = [(obj.object_type, obj.name, obj.schema) for obj in preview.objects]
    executed_objects = [(obj.object_type, obj.name, obj.schema) for obj in executed.objects]

    assert executed_objects == preview_objects
    assert preview_objects == [
        ("foreign_key", "fk_orders_customer", "dbo"),
        ("view", "sales_view", "dbo"),
        ("table", "orders", "dbo"),
        ("procedure", "rebuild_stats", "dbo"),
        ("function", "calc_total", "dbo"),
        ("sequence", "order_seq", "dbo"),
        ("type", "EmailAddress", "dbo"),
        ("synonym", "remote_orders", "dbo"),
        ("fulltext_catalog", "ft_catalog", "dbo"),
    ]
    assert "trigger" not in {obj.object_type for obj in preview.objects}
    assert executed.statements == preview.statements
    assert all("TRIGGER" not in statement.upper() for statement in preview.statements)

    # The catalog drop must come after the table drop: a fulltext index on
    # "orders" implicitly disappears when the table is dropped, but the
    # catalog it lived in is a separate object that DROP TABLE never touches.
    table_drop_index = preview.statements.index("DROP TABLE [dbo].[orders]")
    catalog_drop_index = preview.statements.index("DROP FULLTEXT CATALOG [ft_catalog]")
    assert table_drop_index < catalog_drop_index


@pytest.mark.unit
def test_sqlserver_provider_exposes_native_clean_preview():
    """SqlServerProvider.get_clean_preview delegates to execute_query."""
    from config.dblift_config import DbliftConfig

    cfg = DbliftConfig.from_dict(
        {
            "database": {
                "type": "sqlserver",
                "host": "localhost",
                "port": 1433,
                "database": "testdb",
                "username": "sa",
                "password": "Password1!",
            }
        }
    )
    provider = SqlServerProvider(cfg)
    # Patch execute_query so no live connection is needed.
    preview_rows: dict = {}

    def _fake_query(sql, params=None):
        if "sys.foreign_keys" in sql:
            return []
        if "INFORMATION_SCHEMA.VIEWS" in sql:
            return []
        if "sys.tables" in sql:
            return []
        if "INFORMATION_SCHEMA.ROUTINES" in sql:
            return []
        if "sys.sequences" in sql:
            return []
        if "sys.types" in sql:
            return []
        if "sys.synonyms" in sql:
            return []
        return []

    provider.execute_query = _fake_query  # type: ignore[method-assign]
    summary = provider.get_clean_preview("dbo")
    assert hasattr(summary, "statements")
    assert summary.statements == []
