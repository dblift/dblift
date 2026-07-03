"""Extended unit tests for :mod:`db.plugins.db2.provider` (Db2Provider)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from db.plugins.db2.provider import Db2Provider


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


class TestExecuteStatement:
    def test_strips_trailing_semicolons_and_creates_schema(self) -> None:
        provider = DummyDb2Provider()
        provider.create_schema_if_not_exists = lambda schema: provider.calls.append(
            ("create_schema", schema)
        )
        provider.set_current_schema = lambda schema: provider.calls.append(("set_schema", schema))
        connection = MagicMock()
        provider._ensure_connection = lambda: connection
        provider._tx = None
        provider._external_connection = False

        Db2Provider.execute_statement(provider, "SELECT 1;;  ", schema="APP")

        assert ("create_schema", "APP") in provider.calls
        assert ("set_schema", "APP") in provider.calls
        connection.exec_driver_sql.assert_called_once_with("SELECT 1")


class TestGetDatabaseVersion:
    def test_returns_dbms_ver_from_driver_connection(self) -> None:
        # No SQL query at all — reads the version the driver already got
        # from the CLI handshake at connect time (avoids the fenced
        # SYSIBMADM.ENV_INST_INFO route entirely; see BUG OBS-01).
        provider = DummyDb2Provider()
        raw = SimpleNamespace(dbms_ver="12.01.0500")
        provider._ensure_connection = lambda: SimpleNamespace(connection=raw)
        provider.execute_query = lambda sql, params=None: (_ for _ in ()).throw(
            AssertionError("should not query SYSIBMADM.ENV_INST_INFO")
        )

        assert provider.get_database_version() == "DB2 12.01.0500"

    def test_falls_back_to_current_server_when_dbms_ver_missing(self) -> None:
        provider = DummyDb2Provider()
        raw = SimpleNamespace(dbms_ver=None)
        provider._ensure_connection = lambda: SimpleNamespace(connection=raw)
        provider.execute_query = lambda sql, params=None: [{"DB_NAME": "SAMPLE"}]

        assert provider.get_database_version() == "DB2 SAMPLE"

    def test_returns_unknown_when_dbms_ver_missing_and_fallback_empty(self) -> None:
        provider = DummyDb2Provider()
        raw = SimpleNamespace(dbms_ver=None)
        provider._ensure_connection = lambda: SimpleNamespace(connection=raw)
        provider.execute_query = lambda sql, params=None: []

        assert provider.get_database_version() == "DB2 Unknown Version"

    def test_returns_unknown_on_exception(self) -> None:
        provider = DummyDb2Provider()

        def ensure_connection():
            raise RuntimeError("connection lost")

        provider._ensure_connection = ensure_connection

        assert provider.get_database_version() == "DB2 Unknown Version"


class TestCreateMigrationLockTable:
    def test_skips_creation_when_table_exists(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: True

        provider.create_migration_lock_table_if_not_exists("APP")

        assert not any(
            call[0] == "statement" and "CREATE TABLE" in call[1] for call in provider.calls
        )


class TestAcquireMigrationLock:
    def test_stale_cleanup_failure_logs_debug(self) -> None:
        provider = DummyDb2Provider()
        provider.create_migration_lock_table_if_not_exists = lambda schema: None

        def execute_statement(sql, schema=None, params=None):
            provider.calls.append(("statement", sql, schema, params))
            if "DELETE FROM" in sql:
                raise RuntimeError("cleanup failed")
            return 1

        provider.execute_statement = execute_statement

        assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is True

    def test_insert_failure_rolls_back_connection_then_retries(self, monkeypatch) -> None:
        provider = DummyDb2Provider()
        provider.create_migration_lock_table_if_not_exists = lambda schema: None
        provider._connection = SimpleNamespace(
            rollback=lambda: provider.calls.append(("rollback",))
        )

        clock = iter([0.0, 0.0, 0.5])
        monkeypatch.setattr("db.plugins.db2.provider.time.monotonic", lambda: next(clock))
        monkeypatch.setattr("db.plugins.db2.provider.time.sleep", lambda _seconds: None)

        attempts = {"count": 0}

        def execute_statement(sql, schema=None, params=None):
            provider.calls.append(("statement", sql, schema, params))
            if "INSERT INTO" in sql:
                attempts["count"] += 1
                if attempts["count"] == 1:
                    raise RuntimeError("duplicate lock")
                return 1
            return 1

        provider.execute_statement = execute_statement

        assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is True
        assert ("rollback",) in provider.calls

    def test_insert_failure_rollback_also_fails(self, monkeypatch) -> None:
        provider = DummyDb2Provider()
        provider.create_migration_lock_table_if_not_exists = lambda schema: None

        def failing_rollback():
            raise RuntimeError("rollback error")

        provider._connection = SimpleNamespace(rollback=failing_rollback)

        monkeypatch.setattr("db.plugins.db2.provider.time.sleep", lambda _seconds: None)

        def execute_statement(sql, schema=None, params=None):
            provider.calls.append(("statement", sql, schema, params))
            if "INSERT INTO" in sql:
                raise RuntimeError("duplicate lock")
            return 1

        provider.execute_statement = execute_statement

        assert provider.acquire_migration_lock("APP", wait_timeout_seconds=0) is False


class TestReleaseMigrationLock:
    def test_returns_true_when_table_missing(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: False

        assert provider.release_migration_lock("APP") is True
        assert provider.calls == []

    def test_returns_false_when_no_rows_deleted(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: True
        provider.execute_statement = lambda sql, schema=None, params=None: 0

        assert provider.release_migration_lock("APP") is False


class TestCreateMigrationHistoryTable:
    def test_creates_schema_when_requested(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: False

        provider.create_migration_history_table_if_not_exists("APP", create_schema=True)

        create_schema_calls = [
            c for c in provider.calls if c[0] == "query" and "SYSCAT.SCHEMATA" in c[1]
        ]
        assert create_schema_calls

    def test_existing_table_with_create_schema_checks_baseline_safety(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: True

        def fake_query(sql, params=None):
            provider.calls.append(("query", sql, params))
            return [{"COUNT": 0}]

        provider.execute_query = fake_query

        provider.create_migration_history_table_if_not_exists("APP", create_schema=True)

        assert any("COUNT" in c[1] for c in provider.calls if c[0] == "query")

    def test_existing_table_without_create_schema_returns_early(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: True

        provider.create_migration_history_table_if_not_exists("APP")

        assert not any(c[0] == "statement" and "CREATE TABLE" in c[1] for c in provider.calls)


class TestCheckBaselineSafety:
    def test_raises_when_history_has_rows(self) -> None:
        provider = DummyDb2Provider()
        provider.execute_query = lambda sql, params=None: [{"COUNT": 3}]

        try:
            provider._check_baseline_safety("APP", "DBLIFT_SCHEMA_HISTORY")
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "3 migration(s)" in str(exc)

    def test_passes_with_empty_history(self) -> None:
        provider = DummyDb2Provider()
        provider.execute_query = lambda sql, params=None: [{"COUNT": 0}]

        provider._check_baseline_safety("APP", "DBLIFT_SCHEMA_HISTORY")  # no exception

    def test_passes_with_no_rows(self) -> None:
        provider = DummyDb2Provider()
        provider.execute_query = lambda sql, params=None: []

        provider._check_baseline_safety("APP", "DBLIFT_SCHEMA_HISTORY")  # no exception


class TestCreateSnapshotTable:
    def test_returns_early_when_table_exists(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: True

        provider.create_snapshot_table_if_not_exists("APP")

        assert not any(c[0] == "statement" and "CREATE TABLE" in c[1] for c in provider.calls)


class TestGetAppliedMigrations:
    def test_returns_empty_when_table_missing(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: False

        assert provider.get_applied_migrations("APP") == []

    def test_normalizes_rows_and_converts_success_flag(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: True
        provider.execute_query = lambda sql, params=None: [
            {"SCRIPT": "V1__init.sql", "SUCCESS": 1},
            {"SCRIPT": "V2__more.sql", "SUCCESS": 0},
        ]

        result = provider.get_applied_migrations("APP")

        assert result[0]["script"] == "V1__init.sql"
        assert result[0]["success"] is True
        assert result[1]["success"] is False


class TestRecordMigration:
    def test_inserts_migration_row(self) -> None:
        provider = DummyDb2Provider()
        provider.create_migration_history_table_if_not_exists = (
            lambda schema, table_name=None: provider.calls.append(
                ("ensure_history", schema, table_name)
            )
        )

        provider.record_migration(
            "APP",
            {
                "version": "1",
                "description": "init",
                "type": "SQL",
                "script": "V1.sql",
                "checksum": 123,
                "installed_by": "tester",
                "execution_time": 5,
                "success": True,
            },
        )

        insert_call = next(c for c in provider.calls if c[0] == "statement")
        assert "INSERT INTO" in insert_call[1]
        assert insert_call[3][-1] == 1

    def test_record_migration_failure_uses_zero_success(self) -> None:
        provider = DummyDb2Provider()
        provider.create_migration_history_table_if_not_exists = lambda schema, table_name=None: None

        provider.record_migration("APP", {"version": "1", "success": False})

        insert_call = next(c for c in provider.calls if c[0] == "statement")
        assert insert_call[3][-1] == 0


class TestRecordUndo:
    def test_records_synthetic_undo_migration(self) -> None:
        provider = DummyDb2Provider()
        provider.create_migration_history_table_if_not_exists = lambda schema, table_name=None: None

        assert provider.record_undo("APP", "1", script_name="U1__undo.sql") is True

        insert_call = next(c for c in provider.calls if c[0] == "statement")
        assert insert_call[3][2] == "UNDO_SQL"
        assert insert_call[3][3] == "U1__undo.sql"

    def test_record_undo_default_script_name(self) -> None:
        provider = DummyDb2Provider()
        provider.create_migration_history_table_if_not_exists = lambda schema, table_name=None: None

        provider.record_undo("APP", "2")

        insert_call = next(c for c in provider.calls if c[0] == "statement")
        assert insert_call[3][3] == "UNDO_2.sql"


class TestRepairMigrationHistory:
    def test_returns_false_when_table_missing(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: False

        assert provider.repair_migration_history("APP", "V1.sql", 123) is False

    def test_without_success_value_sets_success_zero(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: True

        result = provider.repair_migration_history("APP", "V1.sql", 999)

        assert result is True
        statement_call = next(c for c in provider.calls if c[0] == "statement")
        assert "SUCCESS = 0" in statement_call[1]
        assert statement_call[3] == [999, "V1.sql"]

    def test_with_success_value_sets_param(self) -> None:
        provider = DummyDb2Provider()
        provider.table_exists = lambda schema, table_name: True

        result = provider.repair_migration_history("APP", "V1.sql", 999, success_value=True)

        assert result is True
        statement_call = next(c for c in provider.calls if c[0] == "statement")
        assert "SUCCESS = ?" in statement_call[1]
        assert statement_call[3] == [999, 1, "V1.sql"]


class TestCleanSchema:
    def test_skips_rows_without_a_resolvable_name(self) -> None:
        provider = DummyDb2Provider()

        def fake_query(sql, params=None):
            provider.calls.append(("query", sql, params))
            if "SYSCAT.TRIGGERS" in sql:
                return [{"UNRELATED": "x"}]
            return []

        provider.execute_query = fake_query

        summary = provider.clean_schema("APP")

        assert not any(c[0] == "statement" and "DROP TRIGGER" in c[1] for c in provider.calls)
        assert summary.objects == []

    def test_skips_foreign_key_rows_without_table_name(self) -> None:
        provider = DummyDb2Provider()

        def fake_query(sql, params=None):
            provider.calls.append(("query", sql, params))
            if "SYSCAT.TABCONST" in sql:
                return [{"CONSTNAME": "FK1"}]
            return []

        provider.execute_query = fake_query

        summary = provider.clean_schema("APP")

        assert not any(c[0] == "statement" and "DROP CONSTRAINT" in c[1] for c in provider.calls)
        assert summary.objects == []

    def test_drop_statement_failure_is_recorded_as_error(self) -> None:
        provider = DummyDb2Provider()

        def fake_query(sql, params=None):
            provider.calls.append(("query", sql, params))
            if "SYSCAT.TABLES" in sql and "TYPE = 'V'" in sql:
                return [{"TABNAME": "APP_VIEW"}]
            return []

        def fake_statement(sql, schema=None, params=None):
            provider.calls.append(("statement", sql, schema, params))
            if "DROP VIEW" in sql:
                raise RuntimeError("drop failed")
            return 1

        provider.execute_query = fake_query
        provider.execute_statement = fake_statement

        summary = provider.clean_schema("APP")

        assert summary.errors
        assert "Failed to drop view APP_VIEW" in summary.errors[0]
