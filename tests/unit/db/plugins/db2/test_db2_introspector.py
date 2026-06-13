"""DB2 native introspector unit tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from db.plugins.db2.introspection.db2_introspector import DB2Introspector
from db.plugins.db2.introspection.db2_queries import DB2MetadataQueries


class _Provider:
    provider_transport = "native"

    def __init__(self):
        self.config = SimpleNamespace(database=SimpleNamespace(type="db2"))
        self.connection = MagicMock()
        self.query_executor = MagicMock()
        self._execute_map: dict = {}

    def create_connection(self):
        return self.connection

    def execute_query(self, sql, params=None):
        for key, rows in self._execute_map.items():
            if key in sql:
                return rows
        return []


def _make_introspector(execute_map=None):
    provider = _Provider()
    if execute_map:
        provider._execute_map = execute_map
    introspector = DB2Introspector(provider)
    vq = MagicMock()
    vq.get_tables_query.return_value = ("SELECT table_name", ["TEST_SCHEMA"])
    vq.get_view_names_query.return_value = ("SELECT view_name", ["TEST_SCHEMA"])
    vq.get_columns_query.return_value = ("SELECT column_name", ["TEST_SCHEMA", "USERS"])
    vq.get_primary_key_query.return_value = ("SELECT pk", ["TEST_SCHEMA", "USERS"])
    vq.get_foreign_keys_query.return_value = ("SELECT fk", ["TEST_SCHEMA", "USERS"])
    vq.get_unique_constraints_query.return_value = (None, [])
    introspector.vendor_queries = vq
    return introspector, provider


def test_native_get_tables_uses_vendor_queries(monkeypatch):
    execute_map = {
        "table_name": [{"TABLE_NAME": "USERS"}, {"TABLE_NAME": "DBLIFT_SCHEMA_HISTORY"}],
        "view_name": [],
        "column_name": [
            {
                "COLUMN_NAME": "ID",
                "DATA_TYPE": "INTEGER",
                "IS_NULLABLE": 0,
                "COLUMN_DEFAULT": None,
                "IS_PRIMARY_KEY": 1,
            }
        ],
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", MagicMock())
    monkeypatch.setattr(introspector, "enrich_table_with_partition_scheme", MagicMock())

    tables = introspector.get_tables("TEST_SCHEMA")

    assert [table.name for table in tables] == ["USERS"]
    assert tables[0].columns[0].name == "ID"
    assert tables[0].columns[0].is_primary_key is True
    introspector._apply_vendor_table_properties.assert_called_once_with(
        "TEST_SCHEMA", '"USERS"', tables[0]
    )


def test_native_get_tables_include_views(monkeypatch):
    execute_map = {
        "table_name": [{"TABLE_NAME": "USERS"}],
        "view_name": [{"VIEW_NAME": "ACTIVE_USERS"}],
        "column_name": [],
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", MagicMock())
    monkeypatch.setattr(introspector, "enrich_table_with_partition_scheme", MagicMock())

    tables = introspector.get_tables("TEST_SCHEMA", include_views=True)

    assert {table.name for table in tables} == {"USERS", "ACTIVE_USERS"}


def test_native_get_tables_matches_patterns_case_insensitively(monkeypatch):
    execute_map = {
        "table_name": [{"TABLE_NAME": "USERS"}, {"TABLE_NAME": "ACCOUNTS"}],
        "view_name": [],
        "column_name": [],
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", MagicMock())
    monkeypatch.setattr(introspector, "enrich_table_with_partition_scheme", MagicMock())

    tables = introspector.get_tables("TEST_SCHEMA", table_pattern="user%")

    assert [table.name for table in tables] == ["USERS"]


def test_native_get_tables_preserves_global_temporary_table(monkeypatch):
    execute_map = {
        "table_name": [
            {"TABLE_NAME": "SESSION_DATA", "IS_TEMPORARY": 1},
        ],
        "view_name": [],
        "column_name": [],
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", MagicMock())
    monkeypatch.setattr(introspector, "enrich_table_with_partition_scheme", MagicMock())

    tables = introspector.get_tables("TEST_SCHEMA")

    assert len(tables) == 1
    assert tables[0].name == "SESSION_DATA"
    assert tables[0].temporary is True


def test_native_get_tables_uses_exact_catalog_table_names_for_lookups(monkeypatch):
    execute_map = {
        "table_name": [{"TABLE_NAME": "MixedTable", "IS_TEMPORARY": 0}],
        "view_name": [],
        "column_name": [],
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "_ensure_metadata", lambda: None)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", MagicMock())
    monkeypatch.setattr(introspector, "enrich_table_with_partition_scheme", MagicMock())

    introspector.get_tables("TEST_SCHEMA")

    introspector.vendor_queries.get_columns_query.assert_called_once_with(
        "TEST_SCHEMA", '"MixedTable"'
    )


def test_native_constraints_include_check_constraints(monkeypatch):
    execute_map = {"pk": [], "fk": []}
    introspector, _ = _make_introspector(execute_map)
    check = MagicMock()
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[check]))

    constraints = introspector.get_constraints("TEST_SCHEMA", "USERS")

    assert constraints[-1] is check
    introspector.get_check_constraints.assert_called_once_with("TEST_SCHEMA", "USERS")


def test_native_constraints_use_case_insensitive_rows(monkeypatch):
    execute_map = {
        "pk": [{"CONSTRAINT_NAME": "PK_USERS", "COLUMN_NAME": "ID"}],
        "fk": [
            {
                "NAME": "FK_USERS_ACCOUNT",
                "COLUMN_NAME": "ACCOUNT_ID",
                "REF_SCHEMA": "TEST_SCHEMA",
                "REF_TABLE": "ACCOUNTS",
                "REF_COLUMN": "ID",
                "ON_DELETE": "CASCADE",
                "ON_UPDATE": "NO ACTION",
            }
        ],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))

    constraints = introspector.get_constraints("TEST_SCHEMA", "USERS")

    assert constraints[0].name == "PK_USERS"
    assert constraints[0].column_names == ["ID"]
    assert constraints[1].name == "FK_USERS_ACCOUNT"
    assert constraints[1].column_names == ["ACCOUNT_ID"]
    assert constraints[1].reference_schema == "TEST_SCHEMA"
    assert constraints[1].reference_table == "ACCOUNTS"
    assert constraints[1].reference_columns == ["ID"]
    assert constraints[1].on_delete == "CASCADE"
    assert constraints[1].on_update == "NO ACTION"


def test_columns_query_reads_tables_and_views():
    sql, params = DB2MetadataQueries().get_columns_query("TEST_SCHEMA", "ACTIVE_USERS")

    assert "syscat.columns" in sql
    assert "syscat.tables" not in sql
    assert params == ["TEST_SCHEMA", "ACTIVE_USERS"]


def test_catalog_queries_normalize_unquoted_identifiers_to_db2_catalog_case():
    queries = DB2MetadataQueries()

    _, table_params = queries.get_tables_query("app")
    _, column_params = queries.get_columns_query("app", "users")
    _, pk_params = queries.get_primary_key_query("app", "users")
    _, fk_params = queries.get_foreign_keys_query("app", "users")

    assert table_params == ["APP"]
    assert column_params == ["APP", "USERS"]
    assert pk_params == ["APP", "USERS"]
    assert fk_params == ["APP", "USERS"]


def test_catalog_queries_preserve_explicitly_quoted_identifiers():
    _, params = DB2MetadataQueries().get_columns_query('"MixedSchema"', '"MixedTable"')

    assert params == ["MixedSchema", "MixedTable"]


def test_foreign_key_query_maps_rule_codes_to_action_names():
    sql, params = DB2MetadataQueries().get_foreign_keys_query("TEST_SCHEMA", "ORDERS")

    assert "WHEN 'C' THEN 'CASCADE'" in sql
    assert "WHEN 'R' THEN 'RESTRICT'" in sql
    assert "WHEN 'A' THEN 'NO ACTION'" in sql
    assert "WHEN 'N' THEN 'SET NULL'" in sql
    assert "r.deleterule AS on_delete" not in sql
    assert "r.updaterule AS on_update" not in sql
    assert params == ["TEST_SCHEMA", "ORDERS"]


def test_columns_query_preserves_decfloat_precision():
    sql, params = DB2MetadataQueries().get_columns_query("TEST_SCHEMA", "AMOUNTS")

    assert "WHEN c.typename = 'DECFLOAT' AND c.length = 8 THEN '(16)'" in sql
    assert "WHEN c.typename = 'DECFLOAT' AND c.length = 16 THEN '(34)'" in sql
    assert "WHEN c.typename = 'DECIMAL'" in sql
    assert "WHEN c.typename IN ('DECIMAL', 'DECFLOAT')" not in sql
    assert params == ["TEST_SCHEMA", "AMOUNTS"]


def test_columns_query_preserves_for_bit_data_character_types():
    sql, params = DB2MetadataQueries().get_columns_query("TEST_SCHEMA", "PAYLOADS")

    assert "c.codepage = 0" in sql
    assert "FOR BIT DATA" in sql
    assert "WHEN c.typename IN ('CHARACTER', 'CHAR', 'VARCHAR')" in sql
    assert params == ["TEST_SCHEMA", "PAYLOADS"]


def test_columns_query_preserves_lob_lengths():
    sql, params = DB2MetadataQueries().get_columns_query("TEST_SCHEMA", "DOCUMENTS")

    assert "WHEN c.typename IN ('BLOB', 'CLOB', 'DBCLOB')" in sql
    assert "1073741824" in sql
    assert "1048576" in sql
    assert "1024" in sql
    assert params == ["TEST_SCHEMA", "DOCUMENTS"]


def test_tables_query_includes_global_temporary_tables():
    sql, params = DB2MetadataQueries().get_tables_query("TEST_SCHEMA")

    assert "CASE WHEN type = 'G' THEN 1 ELSE 0 END AS is_temporary" in sql
    assert "type IN ('T', 'G')" in sql
    assert params == ["TEST_SCHEMA"]
