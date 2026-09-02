"""Oracle native provider behavior."""

import re
from types import SimpleNamespace

from dblift.db.plugins.oracle.provider import OracleProvider


class DummyOracleProvider(OracleProvider):
    def __init__(self) -> None:
        self.calls = []
        self.config = SimpleNamespace(database=SimpleNamespace(type="oracle", username="SYSTEM"))
        self.log = SimpleNamespace(
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        )

    def _ensure_connection(self):
        return None

    def execute_query(self, sql, params=None):
        self.calls.append(("query", sql, params))
        return []


def test_native_provider_exposes_native_transport() -> None:
    provider = DummyOracleProvider()

    assert provider.provider_transport == "native"
    assert provider.canonical_dialect_key == "oracle"


def test_native_provider_does_not_own_snapshot_table_creation() -> None:
    assert "create_snapshot_table_if_not_exists" not in OracleProvider.__dict__


def test_get_schema_qualified_name_quotes_oracle_identifiers() -> None:
    provider = DummyOracleProvider()

    assert provider.get_schema_qualified_name("APP", "CUSTOMER") == '"APP"."CUSTOMER"'


def test_get_add_column_sql_uses_oracle_add_column_syntax() -> None:
    provider = DummyOracleProvider()

    assert (
        provider.get_add_column_sql("APP", "CUSTOMER", "NAME", "VARCHAR2(100)")
        == 'ALTER TABLE "APP"."CUSTOMER" ADD ("NAME" VARCHAR2(100))'
    )


def test_plsql_block_keeps_trailing_semicolon(monkeypatch) -> None:
    provider = DummyOracleProvider()
    captured = {}

    def fake_execute(self, sql, schema=None, params=None):
        captured["sql"] = sql
        return 1

    monkeypatch.setattr(
        "dblift.db.sqlalchemy_provider.SqlAlchemyProvider.execute_statement", fake_execute
    )

    provider.execute_statement("BEGIN NULL; END;", schema=None)

    assert captured["sql"] == "BEGIN NULL; END;"


def test_plain_sql_strips_trailing_semicolon(monkeypatch) -> None:
    provider = DummyOracleProvider()
    captured = {}

    def fake_execute(self, sql, schema=None, params=None):
        captured["sql"] = sql
        return 1

    monkeypatch.setattr(
        "dblift.db.sqlalchemy_provider.SqlAlchemyProvider.execute_statement", fake_execute
    )

    provider.execute_statement("CREATE TABLE t (id NUMBER);", schema=None)

    assert captured["sql"] == "CREATE TABLE t (id NUMBER)"


def test_plain_query_strips_trailing_semicolon(monkeypatch) -> None:
    provider = DummyOracleProvider()
    captured = {}

    def fake_query(self, sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(
        "dblift.db.sqlalchemy_provider.SqlAlchemyProvider.execute_query", fake_query
    )

    OracleProvider.execute_query(provider, "SELECT 1 FROM DUAL;", params=[1])

    assert captured == {"sql": "SELECT 1 FROM DUAL", "params": [1]}


def test_ensure_schema_ready_logs_set_current_schema_failures() -> None:
    provider = DummyOracleProvider()

    def fail_set_current_schema(schema):
        raise RuntimeError(f"cannot switch to {schema}")

    provider.create_schema_if_not_exists = lambda schema: None
    provider.set_current_schema = fail_set_current_schema

    provider._ensure_schema_ready("APP")


def test_create_schema_grants_existing_user() -> None:
    provider = DummyOracleProvider()
    provider.execute_query = lambda sql, params=None: [{"user_count": 1}]
    provider.execute_statement = (
        lambda sql, schema=None, params=None: provider.calls.append(
            ("statement", sql, schema, params)
        )
        or 1
    )

    provider.create_schema_if_not_exists("APP")

    assert any("GRANT " in sql and '"APP"' in sql for _, sql, _, _ in provider.calls)


def test_create_schema_skips_self_grant_for_current_user() -> None:
    provider = DummyOracleProvider()
    warnings = []
    provider.config.database.username = "APP"
    provider.log.warning = warnings.append
    provider.execute_query = lambda sql, params=None: [{"user_count": 1}]
    provider.execute_statement = (
        lambda sql, schema=None, params=None: provider.calls.append(
            ("statement", sql, schema, params)
        )
        or 1
    )

    provider.create_schema_if_not_exists("APP")

    assert not any("GRANT " in sql for _, sql, _, _ in provider.calls)
    assert warnings == []


def test_create_schema_retries_without_quota_when_full_create_fails() -> None:
    provider = DummyOracleProvider()
    provider.execute_query = lambda sql, params=None: [{"user_count": 0}]

    def fake_execute(sql, schema=None, params=None):
        provider.calls.append(("statement", sql, schema, params))
        if "CREATE USER" in sql and "QUOTA UNLIMITED" in sql:
            raise RuntimeError("quota denied")
        return 1

    provider.execute_statement = fake_execute

    provider.create_schema_if_not_exists("APP")

    create_user_calls = [call[1] for call in provider.calls if "CREATE USER" in call[1]]
    assert len(create_user_calls) == 2
    assert "QUOTA UNLIMITED" not in create_user_calls[-1]


def test_create_schema_generates_oracle_compatible_password(monkeypatch) -> None:
    provider = DummyOracleProvider()
    provider.execute_query = lambda sql, params=None: [{"user_count": 0}]
    provider.execute_statement = (
        lambda sql, schema=None, params=None: provider.calls.append(
            ("statement", sql, schema, params)
        )
        or 1
    )
    monkeypatch.setattr("dblift.db.plugins.oracle.provider.os.urandom", lambda size: b"\xff" * size)

    provider.create_schema_if_not_exists("TEST_SCHEMA")

    create_user_sql = next(sql for _, sql, _, _ in provider.calls if "CREATE USER" in sql)
    password = re.search(r'IDENTIFIED BY "([^"]+)"', create_user_sql).group(1)
    assert len(password) <= 30


def test_migration_lock_timeout_does_not_fall_back_to_table_lock(monkeypatch) -> None:
    provider = DummyOracleProvider()
    provider.execute_query = lambda sql, params=None: (
        [{"lock_hash": 42}] if "GET_HASH_VALUE" in sql else [{"result": 1}]
    )
    provider._acquire_table_lock = lambda *_args: True
    monkeypatch.setattr("dblift.db.plugins.oracle.provider.time.sleep", lambda _seconds: None)
    times = iter([0, 2])
    monkeypatch.setattr("dblift.db.plugins.oracle.provider.time.time", lambda: next(times))

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is False


def test_lock_table_creation_treats_already_exists_as_success() -> None:
    provider = DummyOracleProvider()
    provider.create_schema_if_not_exists = lambda schema: None
    provider.table_exists = lambda schema, table_name: False

    def raise_already_exists(sql, schema=None, params=None):
        raise RuntimeError("ORA-00955: name is already used by an existing object")

    provider.execute_statement = raise_already_exists

    provider.create_migration_lock_table_if_not_exists("APP")


def test_release_table_migration_lock_deletes_row_and_keeps_table() -> None:
    provider = DummyOracleProvider()
    provider._lock_handles = {}
    provider._lock_handles[provider.get_lock_key("APP")] = None
    provider.table_exists = lambda schema, table_name: True
    provider.execute_statement = (
        lambda sql, schema=None, params=None: provider.calls.append(
            ("statement", sql, schema, params)
        )
        or 1
    )

    assert provider.release_migration_lock("APP") is True

    assert (
        "statement",
        'DELETE FROM "APP"."DBLIFT_MIGRATION_LOCK" WHERE LOCK_NAME = ?',
        None,
        ["DBLIFT_MIG_LOCK_APP"],
    ) in provider.calls
    assert (
        "statement",
        'DROP TABLE "APP"."DBLIFT_MIGRATION_LOCK"',
        None,
        None,
    ) not in provider.calls


def test_existing_history_table_checks_baseline_safety() -> None:
    provider = DummyOracleProvider()
    provider.create_schema_if_not_exists = lambda schema: None
    provider.table_exists = lambda schema, table_name: True
    called = {}

    def check_baseline_safety(schema, table_name):
        called["args"] = (schema, table_name)

    provider._check_baseline_safety = check_baseline_safety

    provider.create_migration_history_table_if_not_exists("APP", create_schema=True)

    assert called["args"] == ("APP", "DBLIFT_SCHEMA_HISTORY")


def test_baseline_safety_rejects_existing_history_rows() -> None:
    provider = DummyOracleProvider()
    provider.execute_query = lambda sql, params=None: [{"count": 2}]

    try:
        provider._check_baseline_safety("APP", "DBLIFT_SCHEMA_HISTORY")
    except RuntimeError as exc:
        assert "2 migration(s)" in str(exc)
    else:
        raise AssertionError("baseline safety should reject non-empty history")


def test_clean_schema_drops_private_database_links() -> None:
    provider = DummyOracleProvider()

    def fake_query(sql, params=None):
        if "ALL_DB_LINKS" in sql:
            return [{"db_link": "REMOTE_DB"}]
        return []

    provider.execute_query = fake_query
    provider.execute_statement = (
        lambda sql, schema=None, params=None: provider.calls.append(
            ("statement", sql, schema, params)
        )
        or 1
    )

    summary = provider.clean_schema("APP")

    assert ("statement", 'DROP DATABASE LINK "REMOTE_DB"', None, None) in provider.calls
    assert any(drop.object_type == "database_link" for drop in summary.objects)


def test_clean_schema_continues_after_program_object_query_failure() -> None:
    provider = DummyOracleProvider()

    def fake_query(sql, params=None):
        provider.calls.append(("query", sql, None, params))
        if "ALL_OBJECTS" in sql:
            raise RuntimeError("program query denied")
        if "ALL_SYNONYMS" in sql:
            return [{"object_name": "APP_SYNONYM"}]
        return []

    provider.execute_query = fake_query
    provider.execute_statement = (
        lambda sql, schema=None, params=None: provider.calls.append(
            ("statement", sql, schema, params)
        )
        or 1
    )

    summary = provider.clean_schema("APP")

    query_sql = [call[1] for call in provider.calls if call[0] == "query"]
    program_query_index = next(index for index, sql in enumerate(query_sql) if "ALL_OBJECTS" in sql)
    synonym_query_index = next(
        index for index, sql in enumerate(query_sql) if "ALL_SYNONYMS" in sql
    )
    assert program_query_index < synonym_query_index
    assert ("statement", 'DROP SYNONYM "APP"."APP_SYNONYM"', None, None) in provider.calls
    assert any(drop.object_type == "synonym" for drop in summary.objects)


def test_clean_schema_records_program_object_drop() -> None:
    provider = DummyOracleProvider()

    def fake_query(sql, params=None):
        if "ALL_OBJECTS" in sql:
            return [{"object_name": "DO_WORK", "object_type": "PROCEDURE"}]
        return []

    provider.execute_query = fake_query
    provider.execute_statement = (
        lambda sql, schema=None, params=None: provider.calls.append(
            ("statement", sql, schema, params)
        )
        or 1
    )

    summary = provider.clean_schema("APP")

    assert ("statement", 'DROP PROCEDURE "APP"."DO_WORK"', None, None) in provider.calls
    assert any(drop.object_type == "procedure" for drop in summary.objects)
