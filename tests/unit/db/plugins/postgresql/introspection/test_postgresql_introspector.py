"""Unit tests for :class:`db.plugins.postgresql.introspection.postgresql_introspector.PostgreSQLIntrospector`."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.introspection.base_introspector import BaseIntrospector
from core.sql_model.base import ConstraintType
from db.plugins.postgresql.introspection.postgresql_introspector import PostgreSQLIntrospector


class _Provider:
    provider_transport = "native"

    def __init__(self):
        self.config = SimpleNamespace(database=SimpleNamespace(type="postgresql"))
        self.connection = MagicMock()
        self._execute_map: dict = {}

    def execute_query(self, sql, params=None):
        for key, rows in self._execute_map.items():
            if key in sql:
                return rows
        return []


def _make_introspector(execute_map=None):
    provider = _Provider()
    if execute_map:
        provider._execute_map = execute_map
    introspector = PostgreSQLIntrospector(provider, use_vendor_queries=False)
    introspector.vendor_queries = MagicMock()
    return introspector, provider


class TestMatchesPattern:
    def test_percent_wildcard_matches(self):
        assert PostgreSQLIntrospector._matches_pattern("orders", "%") is True

    def test_underscore_wildcard_matches_single_char(self):
        assert PostgreSQLIntrospector._matches_pattern("ord1", "ord_") is True

    def test_pattern_does_not_match(self):
        assert PostgreSQLIntrospector._matches_pattern("orders", "items%") is False


class TestIsInternalTable:
    def test_default_history_table_is_internal(self):
        introspector, _ = _make_introspector()
        assert introspector._is_internal_table("dblift_schema_history") is True

    def test_default_snapshot_table_is_internal(self):
        introspector, _ = _make_introspector()
        from core.constants import DBLIFT_SCHEMA_SNAPSHOTS_TABLE

        assert introspector._is_internal_table(DBLIFT_SCHEMA_SNAPSHOTS_TABLE) is True

    def test_migration_lock_table_is_internal(self):
        introspector, _ = _make_introspector()
        assert introspector._is_internal_table("dblift_migration_lock") is True

    def test_legacy_flyway_history_table_is_internal(self):
        introspector, _ = _make_introspector()
        assert introspector._is_internal_table("schema_version") is True

    def test_normal_table_is_not_internal(self):
        introspector, _ = _make_introspector()
        assert introspector._is_internal_table("orders") is False

    def test_custom_history_table_from_config(self):
        introspector, provider = _make_introspector()
        provider.config.database.history_table = "custom_history"
        assert introspector._is_internal_table("custom_history") is True
        assert introspector._is_internal_table("dblift_schema_history") is False

    def test_custom_snapshot_table_from_config(self):
        introspector, provider = _make_introspector()
        provider.config.database.snapshot_table = "custom_snapshot"
        assert introspector._is_internal_table("custom_snapshot") is True


class TestVendorColumns:
    def test_no_vendor_queries_returns_empty(self):
        introspector, _ = _make_introspector()
        introspector.vendor_queries = None
        assert introspector._vendor_columns("public", "orders") == []

    def test_columns_query_returns_none(self):
        introspector, _ = _make_introspector()
        introspector.vendor_queries.get_columns_query.return_value = None
        assert introspector._vendor_columns("public", "orders") == []

    def test_returns_sql_columns_from_rows(self):
        introspector, provider = _make_introspector()
        introspector.vendor_queries.get_columns_query.return_value = (
            "SELECT cols",
            ["public", "orders"],
        )
        provider._execute_map = {
            "SELECT cols": [
                {
                    "column_name": "id",
                    "data_type": "integer",
                    "is_nullable": False,
                    "column_default": None,
                    "is_primary_key": True,
                },
                {
                    "column_name": "name",
                    "data_type": "text",
                },
            ]
        }

        columns = introspector._vendor_columns("public", "orders")

        assert [c.name for c in columns] == ["id", "name"]
        assert columns[0].is_primary_key is True
        assert columns[1].nullable is True


class TestGetTables:
    def test_non_native_transport_delegates_to_base(self):
        introspector, provider = _make_introspector()
        provider.provider_transport = "jdbc"
        with patch.object(
            BaseIntrospector, "get_tables", return_value=["sentinel"]
        ) as base_get_tables:
            result = introspector.get_tables("public")

        assert result == ["sentinel"]
        base_get_tables.assert_called_once()

    def test_no_vendor_queries_returns_empty(self):
        introspector, _ = _make_introspector()
        introspector.vendor_queries = None
        assert introspector.get_tables("public") == []

    def test_filters_internal_tables_and_pattern(self):
        introspector, provider = _make_introspector()
        introspector.vendor_queries.get_tables_query.return_value = (
            "SELECT table_name",
            ["public"],
        )
        provider._execute_map = {
            "SELECT table_name": [
                {"table_name": "orders"},
                {"table_name": "dblift_schema_history"},
                {"table_name": "logs"},
            ]
        }
        introspector.enrich_columns_with_computed = MagicMock()
        introspector.enrich_columns_with_identity = MagicMock()
        introspector.get_constraints = MagicMock(return_value=[])
        introspector._vendor_columns = MagicMock(return_value=[])

        tables = introspector.get_tables("public", include_views=False, table_pattern="ord%")

        assert [t.name for t in tables] == ["orders"]
        introspector.enrich_columns_with_computed.assert_called_once()
        introspector.enrich_columns_with_identity.assert_called_once()

    def test_includes_views_when_requested(self):
        introspector, provider = _make_introspector()
        introspector.vendor_queries.get_tables_query.return_value = (
            "SELECT table_name",
            ["public"],
        )
        introspector.vendor_queries.get_view_names_query.return_value = (
            "SELECT view_name",
            ["public"],
        )
        provider._execute_map = {
            "SELECT table_name": [{"table_name": "orders"}],
            "SELECT view_name": [{"view_name": "orders_view"}],
        }
        introspector.enrich_columns_with_computed = MagicMock()
        introspector.enrich_columns_with_identity = MagicMock()
        introspector.get_constraints = MagicMock(return_value=[])
        introspector._vendor_columns = MagicMock(return_value=[])

        tables = introspector.get_tables("public", include_views=True)

        assert {t.name for t in tables} == {"orders", "orders_view"}

    def test_no_tables_query_result(self):
        introspector, provider = _make_introspector()
        introspector.vendor_queries.get_tables_query.return_value = None
        introspector.vendor_queries.get_view_names_query.return_value = None

        tables = introspector.get_tables("public")

        assert tables == []


class TestGetConstraints:
    def test_non_native_transport_delegates(self):
        introspector, provider = _make_introspector()
        provider.provider_transport = "jdbc"
        introspector._get_constraints = MagicMock(return_value=["sentinel"])

        result = introspector.get_constraints("public", "orders")

        assert result == ["sentinel"]
        introspector._get_constraints.assert_called_once_with("public", "orders")

    def test_no_vendor_queries_returns_empty(self):
        introspector, _ = _make_introspector()
        introspector.vendor_queries = None
        assert introspector.get_constraints("public", "orders") == []

    def test_no_results_returns_check_constraints_only(self):
        introspector, provider = _make_introspector()
        introspector.vendor_queries.get_primary_key_query.return_value = None
        introspector.vendor_queries.get_foreign_keys_query.return_value = None
        introspector.vendor_queries.get_unique_constraints_query.return_value = (None, [])
        introspector.get_check_constraints = MagicMock(return_value=[])

        result = introspector.get_constraints("public", "orders")

        assert result == []
        introspector.get_check_constraints.assert_called_once_with("public", "orders")

    def test_full_constraint_aggregation(self):
        introspector, provider = _make_introspector()
        introspector.vendor_queries.get_primary_key_query.return_value = (
            "SELECT pk",
            ["public", "orders"],
        )
        introspector.vendor_queries.get_foreign_keys_query.return_value = (
            "SELECT fk",
            ["public", "orders"],
        )
        introspector.vendor_queries.get_unique_constraints_query.return_value = (
            "SELECT uc",
            ["public", "orders"],
        )
        check_constraint = SimpleNamespace(name="chk1", constraint_type=ConstraintType.CHECK)
        introspector.get_check_constraints = MagicMock(return_value=[check_constraint])

        provider._execute_map = {
            "SELECT pk": [{"constraint_name": "orders_pkey", "column_name": "id"}],
            "SELECT fk": [
                {
                    "name": "fk_customer",
                    "column_name": "customer_id",
                    "ref_schema": "public",
                    "ref_table": "customers",
                    "ref_column": "id",
                    "on_delete": "CASCADE",
                    "on_update": "NO ACTION",
                },
                {
                    "name": "fk_customer",
                    "column_name": "customer_id2",
                    "ref_schema": "public",
                    "ref_table": "customers",
                    "ref_column": "id2",
                    "on_delete": "CASCADE",
                    "on_update": "NO ACTION",
                },
            ],
            "SELECT uc": [
                {"name": "uq_orders_code", "column_name": "code"},
                {"name": "uq_orders_code", "column_name": "code2"},
            ],
        }

        constraints = introspector.get_constraints("public", "orders")

        types = [c.constraint_type for c in constraints]
        assert ConstraintType.PRIMARY_KEY in types
        assert ConstraintType.FOREIGN_KEY in types
        assert ConstraintType.UNIQUE in types

        fk = next(c for c in constraints if c.constraint_type == ConstraintType.FOREIGN_KEY)
        assert fk.column_names == ["customer_id", "customer_id2"]
        assert fk.reference_columns == ["id", "id2"]
        assert fk.reference_schema == "public"

        uc = next(c for c in constraints if c.constraint_type == ConstraintType.UNIQUE)
        assert uc.column_names == ["code", "code2"]

        assert check_constraint in constraints

    def test_pk_with_missing_constraint_name(self):
        introspector, provider = _make_introspector()
        introspector.vendor_queries.get_primary_key_query.return_value = (
            "SELECT pk",
            ["public", "orders"],
        )
        introspector.vendor_queries.get_foreign_keys_query.return_value = None
        introspector.vendor_queries.get_unique_constraints_query.return_value = (None, [])
        introspector.get_check_constraints = MagicMock(return_value=[])
        provider._execute_map = {
            "SELECT pk": [{"column_name": "id"}],
        }

        constraints = introspector.get_constraints("public", "orders")

        pk = next(c for c in constraints if c.constraint_type == ConstraintType.PRIMARY_KEY)
        assert pk.name == "orders_pkey"

    def test_pk_query_returns_no_rows(self):
        introspector, provider = _make_introspector()
        introspector.vendor_queries.get_primary_key_query.return_value = (
            "SELECT pk",
            ["public", "orders"],
        )
        introspector.vendor_queries.get_foreign_keys_query.return_value = None
        introspector.vendor_queries.get_unique_constraints_query.return_value = (None, [])
        introspector.get_check_constraints = MagicMock(return_value=[])
        provider._execute_map = {"SELECT pk": []}

        constraints = introspector.get_constraints("public", "orders")

        assert not any(c.constraint_type == ConstraintType.PRIMARY_KEY for c in constraints)


class TestGetIndexes:
    def test_delegates_to_base_get_indexes(self):
        introspector, _ = _make_introspector()
        with patch.object(
            BaseIntrospector, "get_indexes", return_value=["idx"]
        ) as base_get_indexes:
            result = introspector.get_indexes("public", "orders")

        assert result == ["idx"]
        base_get_indexes.assert_called_once_with("public", "orders")
