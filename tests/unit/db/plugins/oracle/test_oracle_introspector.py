"""Oracle native introspector unit tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from db.plugins.oracle.introspection.oracle_introspector import OracleIntrospector
from db.plugins.oracle.introspection.oracle_queries import OracleMetadataQueries


class _Provider:
    provider_transport = "native"

    def __init__(self):
        self.config = SimpleNamespace(database=SimpleNamespace(type="oracle"))
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
    introspector = OracleIntrospector(provider)
    vq = MagicMock()
    vq.get_tables_query.return_value = ("SELECT table_name", ["APP"])
    vq.get_view_names_query.return_value = ("SELECT view_name", ["APP"])
    vq.get_columns_query.return_value = ("SELECT column_name", ["APP", "USERS"])
    vq.get_primary_key_query.return_value = ("SELECT pk", ["APP", "USERS"])
    vq.get_foreign_keys_query.return_value = ("SELECT fk", ["APP", "USERS"])
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
                "DATA_TYPE": "NUMBER(10,0)",
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

    tables = introspector.get_tables("APP")

    assert [table.name for table in tables] == ["USERS"]
    assert tables[0].columns[0].name == "ID"
    assert tables[0].columns[0].is_primary_key is True
    introspector._apply_vendor_table_properties.assert_called_once_with("APP", '"USERS"', tables[0])


def test_native_get_tables_does_not_request_metadata(monkeypatch):
    execute_map = {
        "table_name": [{"TABLE_NAME": "USERS"}],
        "view_name": [],
        "column_name": [],
        "pk": [],
        "fk": [],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(
        introspector,
        "_ensure_metadata",
        MagicMock(side_effect=AssertionError("native Oracle must not request metadata")),
    )
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))
    monkeypatch.setattr(introspector, "_apply_vendor_table_properties", MagicMock())
    monkeypatch.setattr(introspector, "enrich_table_with_partition_scheme", MagicMock())

    tables = introspector.get_tables("APP")

    assert [table.name for table in tables] == ["USERS"]


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

    tables = introspector.get_tables("APP", include_views=True)

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

    tables = introspector.get_tables("APP", table_pattern="user%")

    assert [table.name for table in tables] == ["USERS"]


def test_native_get_tables_preserves_global_temporary_table(monkeypatch):
    execute_map = {
        "table_name": [
            {
                "TABLE_NAME": "TMP_USERS",
                "IS_TEMPORARY": 1,
                "TEMPORARY_DURATION": "SYS$SESSION",
            }
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

    tables = introspector.get_tables("APP")

    assert len(tables) == 1
    assert tables[0].name == "TMP_USERS"
    assert tables[0].temporary is True


def test_native_get_tables_uses_exact_catalog_table_names_for_lookups(monkeypatch):
    execute_map = {
        "table_name": [
            {"TABLE_NAME": "Users", "IS_TEMPORARY": 0},
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

    introspector.get_tables("APP")

    introspector.vendor_queries.get_columns_query.assert_called_once_with("APP", '"Users"')


def test_native_constraints_include_check_constraints(monkeypatch):
    execute_map = {"pk": [], "fk": []}
    introspector, _ = _make_introspector(execute_map)
    check = MagicMock()
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[check]))

    constraints = introspector.get_constraints("APP", "USERS")

    assert constraints[-1] is check
    introspector.get_check_constraints.assert_called_once_with("APP", "USERS")


def test_native_constraints_use_case_insensitive_rows(monkeypatch):
    execute_map = {
        "pk": [{"CONSTRAINT_NAME": "PK_USERS", "COLUMN_NAME": "ID"}],
        "fk": [
            {
                "NAME": "FK_USERS_ACCOUNT",
                "COLUMN_NAME": "ACCOUNT_ID",
                "REF_SCHEMA": "APP",
                "REF_TABLE": "ACCOUNTS",
                "REF_COLUMN": "ID",
                "ON_DELETE": "CASCADE",
                "ON_UPDATE": None,
            }
        ],
    }
    introspector, _ = _make_introspector(execute_map)
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))

    constraints = introspector.get_constraints("APP", "USERS")

    assert constraints[0].name == "PK_USERS"
    assert constraints[0].column_names == ["ID"]
    assert constraints[1].name == "FK_USERS_ACCOUNT"
    assert constraints[1].column_names == ["ACCOUNT_ID"]
    assert constraints[1].reference_schema == "APP"
    assert constraints[1].reference_table == "ACCOUNTS"
    assert constraints[1].reference_columns == ["ID"]
    assert constraints[1].on_delete == "CASCADE"


def test_native_constraints_preserve_oracle_constraint_state(monkeypatch):
    execute_map = {
        "pk": [
            {
                "CONSTRAINT_NAME": "PK_USERS",
                "COLUMN_NAME": "ID",
                "IS_DEFERRABLE": "Y",
                "INITIALLY_DEFERRED": "Y",
                "IS_ENABLED": "N",
                "IS_VALIDATED": "N",
            }
        ],
        "fk": [
            {
                "NAME": "FK_USERS_ACCOUNT",
                "COLUMN_NAME": "ACCOUNT_ID",
                "REF_SCHEMA": "APP",
                "REF_TABLE": "ACCOUNTS",
                "REF_COLUMN": "ID",
                "ON_DELETE": "CASCADE",
                "ON_UPDATE": None,
                "IS_DEFERRABLE": "Y",
                "INITIALLY_DEFERRED": "N",
                "IS_ENABLED": "Y",
                "IS_VALIDATED": "N",
            }
        ],
        "unique": [
            {
                "CONSTRAINT_NAME": "UQ_USERS_EMAIL",
                "COLUMN_NAME": "EMAIL",
                "IS_DEFERRABLE": "N",
                "INITIALLY_DEFERRED": "N",
                "IS_ENABLED": "N",
                "IS_VALIDATED": "Y",
            }
        ],
    }
    introspector, _ = _make_introspector(execute_map)
    introspector.vendor_queries.get_unique_constraints_query.return_value = (
        "SELECT unique",
        ["APP", "USERS"],
    )
    monkeypatch.setattr(introspector, "get_check_constraints", MagicMock(return_value=[]))

    constraints = introspector.get_constraints("APP", "USERS")

    assert constraints[0].is_deferrable is True
    assert constraints[0].initially_deferred is True
    assert constraints[0].is_enabled is False
    assert constraints[0].is_validated is False
    assert constraints[1].is_deferrable is True
    assert constraints[1].initially_deferred is False
    assert constraints[1].is_enabled is True
    assert constraints[1].is_validated is False
    assert constraints[2].is_deferrable is False
    assert constraints[2].initially_deferred is False
    assert constraints[2].is_enabled is False
    assert constraints[2].is_validated is True


def test_columns_query_reads_tables_and_views():
    sql, params = OracleMetadataQueries().get_columns_query("APP", "ACTIVE_USERS")

    assert "all_tab_cols" in sql
    assert "all_tables" not in sql
    assert params == ["APP", "ACTIVE_USERS"]


def test_tables_query_excludes_materialized_views_and_support_tables():
    sql, params = OracleMetadataQueries().get_tables_query("APP")

    assert "CASE WHEN t.temporary = 'Y' THEN 1 ELSE 0 END AS is_temporary" in sql
    assert "t.duration AS temporary_duration" in sql
    assert "all_mviews" in sql
    assert "mv.owner = t.owner" in sql
    assert "mv.mview_name = t.table_name" in sql
    assert "t.table_name NOT LIKE 'MLOG$%'" in sql
    assert "t.table_name NOT LIKE 'RUPD$%'" in sql
    assert "t.table_name NOT LIKE 'I_SNAP$%'" in sql
    assert params == ["APP"]


def test_columns_query_preserves_character_length_semantics():
    sql, params = OracleMetadataQueries().get_columns_query("APP", "USERS")

    assert "c.char_used = 'C'" in sql
    assert "TO_CHAR(c.char_length)" in sql
    assert "c.data_type = 'RAW'" in sql
    assert "TO_CHAR(c.data_length)" in sql
    assert params == ["APP", "USERS"]


def test_columns_query_preserves_unconstrained_number_scale():
    sql, params = OracleMetadataQueries().get_columns_query("APP", "USERS")

    assert "c.data_type = 'NUMBER' AND c.data_precision IS NULL" in sql
    assert "c.data_scale IS NOT NULL" in sql
    assert "'(*,' || TO_CHAR(c.data_scale) || ')'" in sql
    assert params == ["APP", "USERS"]


def test_columns_query_can_match_exact_quoted_table_names():
    sql, params = OracleMetadataQueries().get_columns_query("APP", '"Users"')

    assert "c.table_name = ?" in sql
    assert "UPPER(c.table_name) = UPPER(?)" not in sql
    assert params == ["APP", "Users"]


def test_constraint_queries_include_oracle_constraint_state():
    queries = OracleMetadataQueries()

    pk_sql, _ = queries.get_primary_key_query("APP", "USERS")
    fk_sql, _ = queries.get_foreign_keys_query("APP", "USERS")
    unique_sql, _ = queries.get_unique_constraints_query("APP", "USERS")

    for sql in (pk_sql, fk_sql, unique_sql):
        assert "AS is_deferrable" in sql
        assert "AS initially_deferred" in sql
        assert "AS is_enabled" in sql
        assert "AS is_validated" in sql


def test_identity_query_uses_valid_identity_columns():
    sql, params = OracleMetadataQueries().get_identity_columns_query("APP", "USERS")

    assert "all_tab_identity_cols" in sql
    assert "sequence_name" not in sql.lower()
    assert "ic.identity_options" in sql
    assert "START WITH: ([^,]+)" in sql
    assert "INCREMENT BY: ([^,]+)" in sql
    assert "NULL AS last_value" in sql
    assert params == ["APP", "USERS"]
