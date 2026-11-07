"""DB2 native provider behavior."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.config import DbliftConfig
from dblift.core.migration.clean_summary import CleanExecutionSummary
from dblift.db.plugins.db2.provider import DB2_LOCK_STALE_SECONDS, Db2Provider, _is_lock_conflict
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider
from tests.unit.db.plugins.lease_support import route_lease_to


class DummyDb2Provider(Db2Provider):
    def __init__(self, *_args) -> None:
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


def test_set_current_schema_executes_set_schema_statement() -> None:
    provider = DummyDb2Provider()

    provider.set_current_schema("APP")

    assert ("statement", 'SET SCHEMA "APP"', None, None) in provider.calls


def test_set_current_schema_skips_reissue_for_same_schema() -> None:
    """A second call for the same schema does not re-issue ``SET SCHEMA``.

    Otherwise dblift resets the current schema before every migration
    statement, silently overwriting a ``SET SCHEMA`` the migration itself
    runs as soon as the next statement fires.
    """
    provider = DummyDb2Provider()

    provider.set_current_schema("APP")
    provider.set_current_schema("APP")

    set_schema_calls = [c for c in provider.calls if c[0] == "statement" and "SET SCHEMA" in c[1]]
    assert len(set_schema_calls) == 1


def test_begin_transaction_alone_does_not_clear_the_schema_cache(monkeypatch) -> None:
    """``begin_transaction`` no longer clears the cache on its own.

    Invalidation is owned by ``ExecutionEngine.reset_schema_cache()``, called
    once at the start of every migration/callback before the transaction
    begins. A provider-level clear here as well would leave nothing between
    the two clears, so the migration's first statement reapplied the schema
    a second time — a duplicate ``SET SCHEMA`` per migration.
    """
    monkeypatch.setattr(SqlAlchemyProvider, "begin_transaction", lambda self: None)
    provider = DummyDb2Provider()

    provider.set_current_schema("APP")
    Db2Provider.begin_transaction(provider)
    provider.set_current_schema("APP")

    set_schema_calls = [c for c in provider.calls if c[0] == "statement" and "SET SCHEMA" in c[1]]
    assert len(set_schema_calls) == 1


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


def test_table_exists_matches_quoted_name_exactly() -> None:
    """Flyway's quoted lowercase table must not be satisfied by an uppercase one."""
    provider = DummyDb2Provider()

    provider.table_exists("APP", '"flyway_schema_history"')

    query_call = provider.calls[-1]
    assert "UPPER(TABSCHEMA) = UPPER(?)" in query_call[1]
    assert "AND TABNAME = ?" in query_call[1]
    assert "UPPER(TABNAME)" not in query_call[1]
    assert query_call[2] == ["APP", "flyway_schema_history"]


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


def _lease_provider() -> DummyDb2Provider:
    provider = DummyDb2Provider()
    provider.create_migration_lock_table_if_not_exists = lambda schema: None
    route_lease_to(provider)
    return provider


def test_acquire_migration_lock_inserts_lock_row_without_overwriting_holder() -> None:
    provider = _lease_provider()

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is True
    provider.release_migration_lock("APP")

    statements = [call[1] for call in provider.calls if call[0] == "statement"]
    lock_insert = next(stmt for stmt in statements if "INSERT INTO" in stmt)
    assert '"APP"."DBLIFT_MIGRATION_LOCK"' in lock_insert
    assert "WHEN MATCHED" not in "\n".join(statements)


def test_acquire_migration_lock_treats_unreported_rowcount_as_success() -> None:
    provider = _lease_provider()

    def execute_statement(sql, schema=None, params=None):
        provider.calls.append(("statement", sql, schema, params))
        return -1 if "INSERT INTO" in sql else 0

    provider.execute_statement = execute_statement

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is True
    provider.release_migration_lock("APP")


def test_acquire_migration_lock_reclaims_ownerless_rows_after_the_stale_threshold(
    monkeypatch,
) -> None:
    """A row an earlier dblift wrote (no owner) is reclaimed only after
    ``DB2_LOCK_STALE_SECONDS``; a lease row after the short lease expiry."""
    monkeypatch.setattr("dblift.db.plugins.lease_lock.POLL_INTERVAL_SECONDS", 0.01)
    provider = _lease_provider()
    attempts = {"insert": 0}

    def execute_statement(sql, schema=None, params=None):
        provider.calls.append(("statement", sql, schema, params))
        if "INSERT INTO" in sql:
            attempts["insert"] += 1
            if attempts["insert"] == 1:
                raise RuntimeError("SQL0803N duplicate values for the index key")
        return 1

    provider.execute_statement = execute_statement

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is True
    provider.release_migration_lock("APP")

    statements = [call[1] for call in provider.calls if call[0] == "statement"]
    reclaim = next(stmt for stmt in statements if "DELETE FROM" in stmt)
    assert f"CURRENT TIMESTAMP - {DB2_LOCK_STALE_SECONDS} SECONDS" in reclaim
    assert "OWNER_TOKEN IS NULL" in reclaim


def test_acquire_migration_lock_honors_timeout_when_row_is_held(monkeypatch) -> None:
    monkeypatch.setattr("dblift.db.plugins.lease_lock.POLL_INTERVAL_SECONDS", 0.01)
    provider = _lease_provider()

    def fail_insert(sql, schema=None, params=None):
        provider.calls.append(("statement", sql, schema, params))
        if "INSERT INTO" in sql:
            raise RuntimeError("SQL0803N duplicate values for the index key")
        return 0

    provider.execute_statement = fail_insert

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=0.1) is False


@pytest.mark.parametrize(
    ("timeout", "error", "busy"),
    [
        (2, "SQL0911N reason code 68: lock timeout", True),
        (0.1, "SQL0911N reason code 68: lock timeout", True),
        (0, "SQL0911N reason code 68: lock timeout", True),
        (2, "SQL0204N undefined name", False),
    ],
)
def test_caller_owned_lock_preparation_bounds_db2_catalog_wait(
    monkeypatch, timeout, error, busy
) -> None:
    """An unrelated uncommitted CREATE TABLE must not hang lock preparation."""
    from dblift.db.plugins import sql_lease_store

    engine = SimpleNamespace(pool=object())
    calls = []
    helper_connection = SimpleNamespace(
        invalidate=lambda: calls.append("helper_invalidated"),
    )

    class FakeManager:
        def __init__(self, *_args, **_kwargs):
            self.engine = engine

        def close(self):
            calls.append("helper_closed")

    def query(self, sql, params=None):
        calls.append(sql)
        if busy and timeout >= 1 and "SYSCAT.SCHEMATA" in sql:
            raise Exception(error)
        if "SYSCAT.TABLES" in sql:
            assert any("SET CURRENT LOCK TIMEOUT" in call for call in calls)
            raise Exception(error)
        return [{"SCHEMANAME": "APP"}]

    def statement(self, sql, schema=None, params=None):
        calls.append(sql)
        self._connection = helper_connection
        return 1

    monkeypatch.setattr(sql_lease_store, "NativeConnectionManager", FakeManager)
    monkeypatch.setattr(DummyDb2Provider, "execute_query", query)
    monkeypatch.setattr(DummyDb2Provider, "execute_statement", statement)
    monkeypatch.setattr(DummyDb2Provider, "close", lambda self: self._conn_mgr.close())
    provider = DummyDb2Provider()
    provider._conn_mgr = FakeManager()
    provider._external_connection = True

    if busy:
        assert provider.acquire_migration_lock("APP", wait_timeout_seconds=timeout) is False
    else:
        with pytest.raises(Exception, match="SQL0204N"):
            provider.acquire_migration_lock("APP", wait_timeout_seconds=timeout)
    assert "SET CURRENT LOCK TIMEOUT 0" in calls
    assert "helper_closed" in calls
    assert "helper_invalidated" in calls
    if busy:
        if timeout >= 1:
            assert sum("SYSCAT.SCHEMATA" in call for call in calls) == 1
            assert not any("SYSCAT.TABLES" in call for call in calls)
        else:
            assert sum("SYSCAT.SCHEMATA" in call for call in calls) == 1
            assert sum("SYSCAT.TABLES" in call for call in calls) == 1
    assert not any("CREATE TABLE" in call for call in calls)


@pytest.mark.parametrize("link", ("__cause__", "__context__"))
def test_db2_lock_conflict_uses_immediate_fetch_error_cause(link) -> None:
    fetch_error = SystemError("ibm_db.fetchone failed")
    driver_error = Exception("SQL0911N reason code 68 SQLSTATE=40001")
    setattr(fetch_error, link, driver_error)
    provider = DummyDb2Provider()
    helper = DummyDb2Provider()
    calls = []
    helper._connection = SimpleNamespace(invalidate=lambda: calls.append("invalidated"))
    helper.execute_statement = lambda sql, schema=None, params=None: calls.append(sql)

    def fail_preparation(schema):
        raise fetch_error

    helper.create_migration_lock_table_if_not_exists = fail_preparation

    assert _is_lock_conflict(fetch_error) is True
    assert provider._prepare_external_migration_lock_table(helper, "APP", 2) is False
    assert calls == ["SET CURRENT LOCK TIMEOUT 0", "invalidated"]


def test_db2_unrelated_fetch_system_error_propagates() -> None:
    fetch_error = SystemError("ibm_db.fetchone failed")
    fetch_error.__cause__ = Exception("SQL0204N undefined table")
    fetch_error.__context__ = fetch_error
    provider = DummyDb2Provider()
    helper = DummyDb2Provider()
    helper.execute_statement = lambda sql, schema=None, params=None: None
    helper._connection = SimpleNamespace(invalidate=lambda: None)
    helper.create_migration_lock_table_if_not_exists = lambda schema: (_ for _ in ()).throw(
        fetch_error
    )

    assert _is_lock_conflict(fetch_error) is False
    with pytest.raises(SystemError, match="ibm_db.fetchone failed"):
        provider._prepare_external_migration_lock_table(helper, "APP", 2)


def test_db2_unrelated_explicit_cause_does_not_use_hidden_lock_context() -> None:
    fetch_error = SystemError("ibm_db.fetchone failed")
    fetch_error.__cause__ = Exception("SQL0204N undefined table")
    fetch_error.__context__ = Exception("SQL0911N earlier lock timeout")
    fetch_error.__suppress_context__ = True

    assert _is_lock_conflict(fetch_error) is False


def test_db2_suppressed_lock_context_is_not_a_current_conflict() -> None:
    fetch_error = SystemError("ibm_db.fetchone failed")
    fetch_error.__context__ = Exception("SQL0911N earlier lock timeout")
    fetch_error.__suppress_context__ = True

    assert _is_lock_conflict(fetch_error) is False


def test_db2_lock_preparation_discards_helper_after_success() -> None:
    provider = DummyDb2Provider()
    helper = DummyDb2Provider()
    calls = []
    helper.execute_statement = lambda sql, schema=None, params=None: calls.append(sql)
    helper.create_migration_lock_table_if_not_exists = lambda schema: calls.append("prepared")
    helper._connection = SimpleNamespace(invalidate=lambda: calls.append("invalidated"))

    assert provider._prepare_external_migration_lock_table(helper, "APP", 2) is True
    assert calls == ["SET CURRENT LOCK TIMEOUT 0", "prepared", "invalidated"]


def test_db2_lock_preparation_does_not_return_modified_session_to_pool() -> None:
    provider = DummyDb2Provider()
    helper = DummyDb2Provider()
    pooled_registers = []
    register = [None]  # Db2 uses the database default while this register is NULL.
    invalidated = [False]

    def statement(sql, schema=None, params=None):
        if sql.startswith("SET CURRENT LOCK TIMEOUT "):
            register[0] = int(sql.rsplit(" ", 1)[1])
        return 1

    helper.execute_query = lambda sql, params=None: [{"LOCK_TIMEOUT": 5}]
    helper.execute_statement = statement
    helper.create_migration_lock_table_if_not_exists = lambda schema: None
    helper._connection = SimpleNamespace(invalidate=lambda: invalidated.__setitem__(0, True))
    helper._conn_mgr = SimpleNamespace(
        close=lambda: pooled_registers.append(register[0]) if not invalidated[0] else None
    )
    helper.close = lambda: helper._conn_mgr.close()

    assert provider._prepare_external_migration_lock_table(helper, "APP", 2) is True
    helper.close()

    assert pooled_registers == []


def test_db2_lock_preparation_discards_helper_if_setting_timeout_fails() -> None:
    provider = DummyDb2Provider()
    helper = DummyDb2Provider()
    calls = []
    connection = SimpleNamespace(invalidate=lambda: calls.append("invalidated"))
    helper._connection = connection

    def statement(sql, schema=None, params=None):
        calls.append(sql)
        raise Exception("setting timeout failed")

    helper.execute_statement = statement

    with pytest.raises(Exception, match="setting timeout failed"):
        provider._prepare_external_migration_lock_table(helper, "APP", 2)
    assert "invalidated" in calls


def test_release_migration_lock_deletes_own_row_and_keeps_table() -> None:
    provider = _lease_provider()
    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is True

    assert provider.release_migration_lock("APP") is True

    deletes = [call for call in provider.calls if "DELETE FROM" in call[1]]
    assert deletes[-1][1] == (
        'DELETE FROM "APP"."DBLIFT_MIGRATION_LOCK" WHERE LOCK_NAME = ? AND OWNER_TOKEN = ?'
    )
    assert deletes[-1][3][0] == "migration"
    assert not any("DROP TABLE" in call[1] for call in provider.calls)


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


def test_db2_provider_disables_ibm_db_sa_traceback_logging() -> None:
    """ibm_db_sa's log_entry_exit decorator calls logger.exception() on every
    driver-call failure, printing a raw traceback to stderr before dblift's
    own exception handling ever runs. Db2Provider must disable that logger
    on construction so SQL errors surface only through dblift's own clean
    FAILED-panel formatting."""
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

    Db2Provider(config)

    assert logging.getLogger("ibm_db_sa").disabled is True


def test_clean_schema_delegates_to_schema_operations_path() -> None:
    provider = DummyDb2Provider()
    connection = MagicMock()
    provider._ensure_connection = lambda: connection
    summary = CleanExecutionSummary()
    provider.schema_operations = MagicMock()
    provider.schema_operations.clean_schema.return_value = summary

    result = provider.clean_schema("APP")

    assert result is summary
    provider.schema_operations.clean_schema.assert_called_once_with(connection, "APP")


def test_get_clean_preview_delegates_to_schema_operations_path() -> None:
    provider = DummyDb2Provider()
    connection = MagicMock()
    provider._ensure_connection = lambda: connection
    summary = CleanExecutionSummary()
    provider.schema_operations = MagicMock()
    provider.schema_operations.get_clean_preview.return_value = summary

    result = provider.get_clean_preview("APP")

    assert result is summary
    provider.schema_operations.get_clean_preview.assert_called_once_with(connection, "APP")


def test_clean_schema_provider_path_keeps_db2_explicit_commits() -> None:
    provider = DummyDb2Provider()
    connection = MagicMock()
    connection.getAutoCommit.return_value = False
    provider._ensure_connection = lambda: connection

    def fake_query(sql, params=None):
        provider.calls.append(("query", sql, params))
        if "SYSCAT.TABLES" in sql and "TYPE = 'T'" in sql:
            return [{"TABNAME": "USERS"}]
        return []

    provider.execute_query = fake_query

    provider.clean_schema("APP")

    assert connection.commit.call_count >= 1


def test_list_droppable_objects_uses_clean_preview_order() -> None:
    provider = DummyDb2Provider()
    summary = CleanExecutionSummary()
    summary.record_drop(
        'DROP VIEW "APP"."APP_VIEW"',
        object_type="view",
        name="APP_VIEW",
        schema="APP",
    )
    provider.schema_operations = MagicMock()
    provider.schema_operations.get_clean_preview.return_value = summary

    objects = provider.list_droppable_objects("APP")

    assert [(obj.object_type, obj.name, obj.drop_sql) for obj in objects] == [
        ("view", "APP_VIEW", 'DROP VIEW "APP"."APP_VIEW"')
    ]


def test_create_history_table_uses_db2_identity() -> None:
    provider = DummyDb2Provider()

    ddl = provider.create_history_table("APP", "DBLIFT_SCHEMA_HISTORY")

    assert 'CREATE TABLE "APP"."DBLIFT_SCHEMA_HISTORY"' in ddl
    assert "GENERATED ALWAYS AS IDENTITY" in ddl


def test_create_history_table_normalizes_db2_history_table_name() -> None:
    provider = DummyDb2Provider()

    ddl = provider.create_history_table("APP", "dblift_schema_history")

    assert 'CREATE TABLE "APP"."DBLIFT_SCHEMA_HISTORY"' in ddl


def test_clean_schema_raises_when_catalog_query_fails() -> None:
    # A failed catalog query must not read as "no objects of this kind".
    provider = DummyDb2Provider()

    def fake_query(sql, params=None):
        provider.calls.append(("query", sql, params))
        if "SYSCAT.TRIGGERS" in sql:
            raise RuntimeError("no trigger privilege")
        if "SYSCAT.TABLES" in sql and "TYPE = 'V'" in sql:
            return [{"TABNAME": "APP_VIEW"}]
        return []

    provider.execute_query = fake_query

    with pytest.raises(RuntimeError, match="no trigger privilege"):
        provider.clean_schema("APP")

    assert ("statement", 'DROP VIEW "APP"."APP_VIEW"', None, None) not in provider.calls


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


def test_clean_schema_omits_indexes_dropped_with_tables() -> None:
    provider = DummyDb2Provider()

    def fake_query(sql, params=None):
        provider.calls.append(("query", sql, params))
        if "SYSCAT.INDEXES" in sql:
            return [{"INDNAME": "IDX_USERS_EMAIL"}]
        if "SYSCAT.TABLES" in sql and "TYPE = 'T'" in sql:
            return [{"TABNAME": "USERS"}]
        return []

    provider.execute_query = fake_query

    summary = provider.clean_schema("APP")

    statements = [call[1] for call in provider.calls if call[0] == "statement"]
    table_drop = 'DROP TABLE "APP"."USERS"'
    assert table_drop in statements
    assert not any("DROP INDEX" in statement for statement in statements)
    assert not any(drop.object_type == "index" for drop in summary.objects)


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
