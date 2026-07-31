"""PostgreSQL droppable-object enumeration tests."""

from db.plugins.postgresql.provider import PostgreSqlProvider
from db.provider_interfaces import DroppableObject


class _Provider(PostgreSqlProvider):
    def __init__(self):
        self.queries = []
        self.statements = []

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        if "pg_extension" in sql:
            return [{"extension_name": "pg_trgm"}]
        if "pg_views" in sql:
            return [{"view_name": "active_orders"}]
        if "pg_matviews" in sql:
            return [{"matview_name": "daily_totals"}]
        if "pg_tables" in sql:
            return [{"table_name": "orders"}]
        if "information_schema.sequences" in sql:
            return [{"sequence_name": "orders_id_seq"}]
        if "information_schema.routines" in sql:
            return [
                {"routine_name": "calc_total", "routine_type": "FUNCTION"},
                {"routine_name": "refresh_totals", "routine_type": "PROCEDURE"},
            ]
        if "pg_type" in sql:
            return [
                {"type_name": "active_orders", "typtype": "c"},
                {"type_name": "order_status", "typtype": "e"},
                {"type_name": "positive_int", "typtype": "d"},
            ]
        return []

    def execute_statement(self, sql, schema=None, params=None):
        self.statements.append((sql, schema, params))
        return 1


def test_list_droppable_objects_returns_preview_order_without_executing_drops():
    provider = _Provider()

    objects = provider.list_droppable_objects("tenant_a")

    assert objects == [
        DroppableObject(
            name="pg_trgm",
            object_type="extension",
            drop_sql='DROP EXTENSION IF EXISTS "pg_trgm" CASCADE',
        ),
        DroppableObject(
            name="active_orders",
            object_type="view",
            drop_sql='DROP VIEW IF EXISTS "tenant_a"."active_orders" CASCADE',
        ),
        DroppableObject(
            name="daily_totals",
            object_type="materialized_view",
            drop_sql='DROP MATERIALIZED VIEW IF EXISTS "tenant_a"."daily_totals" CASCADE',
        ),
        DroppableObject(
            name="orders",
            object_type="table",
            drop_sql='DROP TABLE IF EXISTS "tenant_a"."orders" CASCADE',
        ),
        DroppableObject(
            name="orders_id_seq",
            object_type="sequence",
            drop_sql='DROP SEQUENCE IF EXISTS "tenant_a"."orders_id_seq" CASCADE',
        ),
        DroppableObject(
            name="calc_total",
            object_type="function",
            drop_sql='DROP FUNCTION IF EXISTS "tenant_a"."calc_total" CASCADE',
        ),
        DroppableObject(
            name="refresh_totals",
            object_type="procedure",
            drop_sql='DROP PROCEDURE IF EXISTS "tenant_a"."refresh_totals" CASCADE',
        ),
        DroppableObject(
            name="order_status",
            object_type="type",
            drop_sql='DROP TYPE IF EXISTS "tenant_a"."order_status" CASCADE',
        ),
        DroppableObject(
            name="positive_int",
            object_type="domain",
            drop_sql='DROP DOMAIN IF EXISTS "tenant_a"."positive_int" CASCADE',
        ),
    ]
    assert not provider.statements
    # Queries carrying a placeholder are schema-scoped and must bind the schema.
    # The continuous-aggregate catalog probe asks a global question and so
    # correctly takes no parameters; it must still never interpolate a name.
    schema_scoped = [(sql, params) for sql, params in provider.queries if "?" in sql]
    assert schema_scoped
    assert all(params == ["tenant_a"] for _sql, params in schema_scoped)
    assert all("tenant_a" not in sql for sql, _params in provider.queries)
