"""DB2 native provider behavior."""

from types import SimpleNamespace

from config import DbliftConfig
from db.plugins.db2.provider import DB2_LOCK_STALE_SECONDS, Db2Provider


class DummyDb2Provider(Db2Provider):
    def __init__(self) -> None:
        self.calls = []
        self.config = SimpleNamespace(database=SimpleNamespace(type="db2"))
        self.log = SimpleNamespace(
            debug=lambda *_args, **_kwargs: None,
            info=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        )

    def _ensure_connection(self):
        return None

    def execute_query(self, sql, params=None):
        self.calls.append(("query", sql, params))
        return []

    def execute_statement(self, sql, schema=None, params=None):
        self.calls.append(("statement", sql, schema, params))
        return 1


def test_native_provider_exposes_native_transport() -> None:
    provider = DummyDb2Provider()

    assert provider.provider_transport == "native"
    assert provider.canonical_dialect_key == "db2"


def test_get_schema_qualified_name_quotes_db2_identifiers() -> None:
    provider = DummyDb2Provider()

    assert provider.get_schema_qualified_name("APP", "CUSTOMER") == '"APP"."CUSTOMER"'


def test_get_add_column_sql_uses_db2_add_column_syntax() -> None:
    provider = DummyDb2Provider()

    assert (
        provider.get_add_column_sql("APP", "CUSTOMER", "NAME", "VARCHAR(100)")
        == 'ALTER TABLE "APP"."CUSTOMER" ADD COLUMN "NAME" VARCHAR(100)'
    )


def test_get_columns_query_matches_db2_catalog_names_case_insensitively() -> None:
    provider = DummyDb2Provider()

    sql, params = provider.get_columns_query("app", "customer")

    assert "UPPER(TABSCHEMA) = UPPER(?)" in sql
    assert "UPPER(TABNAME) = UPPER(?)" in sql
    assert params == ["app", "customer"]


def test_create_schema_if_not_exists_creates_missing_schema() -> None:
    provider = DummyDb2Provider()

    provider.create_schema_if_not_exists("APP")

    assert (
        "query",
        "SELECT SCHEMANAME FROM SYSCAT.SCHEMATA WHERE SCHEMANAME = ?",
        ["APP"],
    ) in provider.calls
    assert ("statement", 'CREATE SCHEMA "APP"', None, None) in provider.calls


def test_table_exists_queries_syscat_tables() -> None:
    provider = DummyDb2Provider()
    provider.execute_query = lambda sql, params=None: [{"tabname": "CUSTOMER"}]

    assert provider.table_exists("APP", "CUSTOMER") is True


def test_table_exists_matches_db2_catalog_names_case_insensitively() -> None:
    provider = DummyDb2Provider()

    provider.table_exists("app", "customer")

    query_call = provider.calls[-1]
    assert query_call[0] == "query"
    assert "UPPER(TABSCHEMA) = UPPER(?)" in query_call[1]
    assert "UPPER(TABNAME) = UPPER(?)" in query_call[1]
    assert query_call[2] == ["app", "customer"]


def test_lock_table_creation_uses_db2_catalog_and_uppercase_table() -> None:
    provider = DummyDb2Provider()
    provider.table_exists = lambda schema, table_name: False

    provider.create_migration_lock_table_if_not_exists("APP")

    assert any(
        call[0] == "statement"
        and "CREATE TABLE" in call[1]
        and '"APP"."DBLIFT_MIGRATION_LOCK"' in call[1]
        for call in provider.calls
    )


def test_acquire_migration_lock_inserts_lock_row_without_overwriting_holder() -> None:
    provider = DummyDb2Provider()
    provider.create_migration_lock_table_if_not_exists = lambda schema: None

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is True

    statements = [call[1] for call in provider.calls if call[0] == "statement"]
    lock_insert = next(stmt for stmt in statements if "INSERT INTO" in stmt)
    assert '"APP"."DBLIFT_MIGRATION_LOCK"' in lock_insert
    assert "WHEN MATCHED" not in "\n".join(statements)


def test_acquire_migration_lock_treats_unreported_rowcount_as_success() -> None:
    provider = DummyDb2Provider()
    provider.create_migration_lock_table_if_not_exists = lambda schema: None

    def execute_statement(sql, schema=None, params=None):
        provider.calls.append(("statement", sql, schema, params))
        return -1 if "INSERT INTO" in sql else 0

    provider.execute_statement = execute_statement

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is True


def test_acquire_migration_lock_uses_separate_stale_cleanup_threshold() -> None:
    provider = DummyDb2Provider()
    provider.create_migration_lock_table_if_not_exists = lambda schema: None

    provider.acquire_migration_lock("APP", wait_timeout_seconds=1)

    statements = [call[1] for call in provider.calls if call[0] == "statement"]
    cleanup_statements = [stmt for stmt in statements if "DELETE FROM" in stmt]
    assert len(cleanup_statements) == 1
    assert f"{DB2_LOCK_STALE_SECONDS} SECONDS" in cleanup_statements[0]
    assert " 1 SECONDS" not in cleanup_statements[0]


def test_acquire_migration_lock_honors_timeout_when_row_is_held(monkeypatch) -> None:
    provider = DummyDb2Provider()
    provider.create_migration_lock_table_if_not_exists = lambda schema: None

    clock = iter([0.0, 0.0, 0.5, 2.0])
    monkeypatch.setattr("db.plugins.db2.provider.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("db.plugins.db2.provider.time.sleep", lambda _seconds: None)

    def fail_insert(sql, schema=None, params=None):
        provider.calls.append(("statement", sql, schema, params))
        if "INSERT INTO" in sql:
            raise RuntimeError("duplicate lock")
        return 0

    provider.execute_statement = fail_insert

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is False


def test_release_migration_lock_deletes_row_and_keeps_table() -> None:
    provider = DummyDb2Provider()
    provider.table_exists = lambda schema, table_name: True

    assert provider.release_migration_lock("APP") is True

    assert (
        "statement",
        'DELETE FROM "APP"."DBLIFT_MIGRATION_LOCK" WHERE LOCK_NAME = ?',
        None,
        ["migration"],
    ) in provider.calls
    assert (
        "statement",
        'DROP TABLE "APP"."DBLIFT_MIGRATION_LOCK"',
        None,
        None,
    ) not in provider.calls


def test_native_provider_exposes_schema_operations_adapter() -> None:
    config = DbliftConfig.from_dict(
        {
            "database": {
                "type": "db2",
                "url": "ibm_db_sa://localhost:50000/SAMPLE",
                "username": "u",
                "password": "p",
            }
        }
    )
    provider = Db2Provider(config)
    calls = []
    provider.create_schema_if_not_exists = lambda schema: calls.append(schema)

    provider.schema_operations.create_schema_if_not_exists(None, "APP")

    assert calls == ["APP"]


def test_create_history_table_uses_db2_identity() -> None:
    provider = DummyDb2Provider()

    ddl = provider.create_history_table("APP", "DBLIFT_SCHEMA_HISTORY")

    assert 'CREATE TABLE "APP"."DBLIFT_SCHEMA_HISTORY"' in ddl
    assert "GENERATED ALWAYS AS IDENTITY" in ddl


def test_create_history_table_normalizes_db2_history_table_name() -> None:
    provider = DummyDb2Provider()

    ddl = provider.create_history_table("APP", "dblift_schema_history")

    assert 'CREATE TABLE "APP"."DBLIFT_SCHEMA_HISTORY"' in ddl


def test_create_snapshot_table_stores_captured_at_as_string() -> None:
    provider = DummyDb2Provider()
    provider.table_exists = lambda schema, table_name: False

    provider.create_snapshot_table_if_not_exists("APP", "dblift_schema_snapshots")

    create_statement = next(
        call[1]
        for call in provider.calls
        if call[0] == "statement" and "DBLIFT_SCHEMA_SNAPSHOTS" in call[1]
    )
    assert 'CREATE TABLE "APP"."DBLIFT_SCHEMA_SNAPSHOTS"' in create_statement
    assert "CAPTURED_AT VARCHAR(255) NOT NULL" in create_statement
    assert "CAPTURED_AT TIMESTAMP" not in create_statement


def test_clean_schema_continues_when_catalog_query_fails() -> None:
    provider = DummyDb2Provider()

    def fake_query(sql, params=None):
        provider.calls.append(("query", sql, params))
        if "SYSCAT.TRIGGERS" in sql:
            raise RuntimeError("no trigger privilege")
        if "SYSCAT.TABLES" in sql and "TYPE = 'V'" in sql:
            return [{"TABNAME": "APP_VIEW"}]
        return []

    provider.execute_query = fake_query

    summary = provider.clean_schema("APP")

    assert ("statement", 'SET SCHEMA "APP"', None, None) in provider.calls
    assert ("statement", 'DROP VIEW "APP"."APP_VIEW"', None, None) in provider.calls
    assert any(drop.object_type == "view" for drop in summary.objects)


def test_clean_schema_drops_foreign_keys_before_tables() -> None:
    provider = DummyDb2Provider()

    def fake_query(sql, params=None):
        provider.calls.append(("query", sql, params))
        if "SYSCAT.TABCONST" in sql:
            return [{"CONSTNAME": "FK_ORDER_CUSTOMER", "TABNAME": "ORDERS"}]
        if "SYSCAT.TABLES" in sql and "TYPE = 'T'" in sql:
            return [{"TABNAME": "ORDERS"}]
        return []

    provider.execute_query = fake_query

    summary = provider.clean_schema("APP")

    statements = [call[1] for call in provider.calls if call[0] == "statement"]
    fk_drop = 'ALTER TABLE "APP"."ORDERS" DROP CONSTRAINT "FK_ORDER_CUSTOMER"'
    table_drop = 'DROP TABLE "APP"."ORDERS"'
    assert fk_drop in statements
    assert table_drop in statements
    assert statements.index(fk_drop) < statements.index(table_drop)
    assert any(drop.object_type == "foreign_key" for drop in summary.objects)


def test_clean_schema_includes_db2_global_temporary_tables() -> None:
    provider = DummyDb2Provider()

    def fake_query(sql, params=None):
        provider.calls.append(("query", sql, params))
        if "SYSCAT.TABLES" in sql and "TYPE = 'G'" in sql:
            return [{"TABNAME": "SESSION_CACHE"}]
        return []

    provider.execute_query = fake_query

    summary = provider.clean_schema("APP")

    assert (
        "statement",
        'DROP TABLE "APP"."SESSION_CACHE"',
        None,
        None,
    ) in provider.calls
    assert any(drop.object_type == "global_temporary_table" for drop in summary.objects)
