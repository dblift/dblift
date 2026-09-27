"""PostgreSQL droppable-object enumeration tests."""

from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.provider_interfaces import DroppableObject


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
        if "pg_proc" in sql:
            return [
                {"routine_name": "calc_total", "routine_kind": "f", "identity_arguments": ""},
                {
                    "routine_name": "calc_total",
                    "routine_kind": "f",
                    "identity_arguments": "order_id integer",
                },
                {
                    "routine_name": "refresh_totals",
                    "routine_kind": "p",
                    "identity_arguments": "INOUT n integer",
                },
                {
                    "routine_name": "sum_amounts",
                    "routine_kind": "a",
                    "identity_arguments": "numeric",
                },
            ]
        if "pg_type" in sql:
            return [
                {"type_name": "active_orders", "typtype": "c"},
                {"type_name": "order_status", "typtype": "e"},
                {"type_name": "positive_int", "typtype": "d"},
                {"type_name": "price_range", "typtype": "r"},
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
            name="calc_total()",
            object_type="function",
            drop_sql='DROP FUNCTION IF EXISTS "tenant_a"."calc_total"() CASCADE',
        ),
        DroppableObject(
            name="calc_total(order_id integer)",
            object_type="function",
            drop_sql='DROP FUNCTION IF EXISTS "tenant_a"."calc_total"(order_id integer) CASCADE',
        ),
        DroppableObject(
            name="refresh_totals(INOUT n integer)",
            object_type="procedure",
            drop_sql='DROP PROCEDURE IF EXISTS "tenant_a"."refresh_totals"(INOUT n integer) CASCADE',
        ),
        DroppableObject(
            name="sum_amounts(numeric)",
            object_type="aggregate",
            drop_sql='DROP AGGREGATE IF EXISTS "tenant_a"."sum_amounts"(numeric) CASCADE',
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
        DroppableObject(
            name="price_range",
            object_type="type",
            drop_sql='DROP TYPE IF EXISTS "tenant_a"."price_range" CASCADE',
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


def test_routine_discovery_reads_pg_proc_and_skips_owned_routines():
    """information_schema.routines omits aggregates, so clean left them behind."""
    provider = _Provider()

    provider.list_droppable_objects("tenant_a")

    routine_sql = next(sql for sql, _params in provider.queries if "pg_proc" in sql)
    assert "information_schema.routines" not in routine_sql
    assert "prokind IN ('f', 'p', 'a', 'w')" in routine_sql
    assert "pg_get_function_identity_arguments" in routine_sql
    # Extension members and a range type's constructors are dropped with their owner.
    assert "deptype IN ('e', 'i')" in routine_sql
    type_sql = next(sql for sql, _params in provider.queries if "pg_type" in sql)
    assert "'r'" in type_sql
    assert "'m'" not in type_sql


def test_zero_argument_aggregate_is_dropped_with_star():
    class _AggProvider(_Provider):
        def execute_query(self, sql, params=None):
            if "pg_proc" in sql:
                return [{"routine_name": "tally", "routine_kind": "a", "identity_arguments": ""}]
            return []

    objects = _AggProvider().list_droppable_objects("tenant_a")

    assert [o.drop_sql for o in objects] == [
        'DROP AGGREGATE IF EXISTS "tenant_a"."tally"(*) CASCADE'
    ]
