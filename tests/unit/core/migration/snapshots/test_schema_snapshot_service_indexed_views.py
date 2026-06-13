from types import SimpleNamespace

import pytest

from core.logger import NullLog
from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService


@pytest.mark.unit
def test_build_payload_keeps_indexes_on_materialized_views(monkeypatch):
    table = SimpleNamespace(name="orders", schema="dbo", constraints=[])
    indexed_view = SimpleNamespace(name="order_summary", schema="dbo")
    table_index = SimpleNamespace(name="idx_orders_user_id", schema="dbo", table_name="orders")
    view_index = SimpleNamespace(
        name="idx_order_summary",
        schema="dbo",
        table_name="order_summary",
    )

    class FakeIntrospector:
        def get_tables(self, schema):
            return [table]

        def get_views(self, schema):
            return []

        def get_materialized_views(self, schema):
            return [indexed_view]

        def get_all_indexes(self, schema):
            return [table_index, view_index]

        def get_sequences(self, schema):
            return []

        def get_triggers(self, schema):
            return []

    monkeypatch.setattr(
        "core.migration.snapshots.schema_snapshot_service.IntrospectorFactory.create",
        lambda provider, log: FakeIntrospector(),
    )

    service = SchemaSnapshotService.__new__(SchemaSnapshotService)
    service.config = SimpleNamespace(
        database=SimpleNamespace(schema="dbo", type="sqlserver"),
        snapshot_table="schema_snapshot",
    )
    service.provider = SimpleNamespace()
    service.history_manager = SimpleNamespace(history_table="schema_version")
    service.log = NullLog()
    service._collect_migration_metadata = lambda: {}
    service._validate_snapshot_accuracy = lambda *args, **kwargs: None

    payload = service._build_payload()

    assert {index.name for index in payload.indexes} == {
        "idx_orders_user_id",
        "idx_order_summary",
    }
