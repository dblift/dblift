"""Extended unit tests for :class:`db.plugins.oracle.provider.OracleProvider`."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import db.plugins.oracle.provider as oracle_provider_module
from db.plugins.oracle.provider import OracleProvider, _oracle_name, _schema_object


def _raise(exc):
    def _fn(*_args, **_kwargs):
        raise exc

    return _fn


class _Provider(OracleProvider):
    def __init__(self, username="DBLIFT"):
        self.queries = []
        self.statements = []
        self.query_results: dict = {}
        self.statement_results: dict = {}
        self.log = MagicMock()
        self.config = SimpleNamespace(database=SimpleNamespace(type="oracle", username=username))
        self._lock_handles = {}

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        for key, val in self.query_results.items():
            if key in sql:
                if callable(val):
                    return val(params)
                return val
        return []

    def execute_statement(self, sql, schema=None, params=None):
        self.statements.append((sql, schema, params))
        for key, val in self.statement_results.items():
            if key in sql:
                if isinstance(val, Exception):
                    raise val
                if callable(val):
                    return val(sql, schema, params)
                return val
        return 1


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(oracle_provider_module.time, "sleep", lambda *_: None)


class TestCreateSchemaIfNotExists:
    def test_creates_user_and_grants_succeed(self):
        p = _Provider(username="ADMIN")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 0}]

        p.create_schema_if_not_exists("APPSCHEMA")

        assert any("CREATE USER" in s[0] for s in p.statements)
        assert any("GRANT" in s[0] for s in p.statements)

    def test_create_user_already_exists_breaks_after_one_attempt(self):
        p = _Provider(username="ADMIN")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 0}]
        p.statement_results["CREATE USER"] = Exception("ORA-01920: user name already exists")

        p.create_schema_if_not_exists("APPSCHEMA")

        create_user_attempts = [s for s in p.statements if "CREATE USER" in s[0]]
        assert len(create_user_attempts) == 1

    def test_all_grants_fail_logs_warning(self):
        p = _Provider(username="ADMIN")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.statement_results["GRANT"] = Exception("ORA-01031: insufficient privileges")

        p.create_schema_if_not_exists("APPSCHEMA")

        p.log.warning.assert_called()

    def test_skips_grants_for_configured_user(self):
        p = _Provider(username="APPSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]

        p.create_schema_if_not_exists("APPSCHEMA")

        assert not any("GRANT" in s[0] for s in p.statements)

    def test_all_create_user_attempts_fail_with_other_error_logs_warning(self):
        p = _Provider(username="ADMIN")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 0}]
        p.statement_results["CREATE USER"] = Exception("ORA-12345: unexpected error")

        p.create_schema_if_not_exists("APPSCHEMA")

        create_user_attempts = [s for s in p.statements if "CREATE USER" in s[0]]
        assert len(create_user_attempts) == 2
        p.log.warning.assert_called()


class TestSetCurrentSchema:
    def test_executes_alter_session_statement(self):
        p = _Provider()

        p.set_current_schema("myschema")

        sql = p.statements[-1][0]
        assert sql == 'ALTER SESSION SET CURRENT_SCHEMA = "myschema"'


class TestTableExists:
    def test_true(self):
        p = _Provider()
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]
        assert p.table_exists("MYSCHEMA", "orders") is True

    def test_false(self):
        p = _Provider()
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]
        assert p.table_exists("MYSCHEMA", "orders") is False

    def test_empty_rows(self):
        p = _Provider()
        assert p.table_exists("MYSCHEMA", "orders") is False


class TestGetActualObjectName:
    def test_found(self):
        p = _Provider()
        p.query_results["FETCH FIRST 1 ROWS ONLY"] = [{"object_name": "ORDERS"}]
        assert p.get_actual_object_name("MYSCHEMA", "orders") == "ORDERS"

    def test_not_found(self):
        p = _Provider()
        assert p.get_actual_object_name("MYSCHEMA", "orders") is None


class TestIsSystemGeneratedSequence:
    def test_true(self):
        p = _Provider()
        p.query_results["ALL_TAB_IDENTITY_COLS"] = [{"cnt": 1}]
        assert p.is_system_generated_sequence("MYSCHEMA", "ISEQ$$_1") is True

    def test_false(self):
        p = _Provider()
        p.query_results["ALL_TAB_IDENTITY_COLS"] = [{"cnt": 0}]
        assert p.is_system_generated_sequence("MYSCHEMA", "seq1") is False


class TestGetDatabaseVersion:
    def test_with_rows(self):
        p = _Provider()
        p.query_results["V$VERSION"] = [{"banner": "Oracle Database 19c"}]
        assert p.get_database_version() == "Oracle Database 19c"

    def test_without_rows(self):
        p = _Provider()
        assert p.get_database_version() == "Unknown Oracle Version"


class TestSupportsTransactionalDdl:
    def test_returns_false(self):
        assert _Provider().supports_transactional_ddl() is False


class TestSchemaHelpers:
    def test_get_schema_qualified_name(self):
        p = _Provider()
        assert p.get_schema_qualified_name("myschema", "orders") == '"myschema"."orders"'

    def test_get_columns_query(self):
        p = _Provider()
        sql, params = p.get_columns_query("myschema", "orders")
        assert "ALL_TAB_COLUMNS" in sql
        assert params[0] == "myschema"

    def test_get_add_column_sql(self):
        p = _Provider()
        sql = p.get_add_column_sql("myschema", "orders", "amount", "NUMBER(10,2)")
        assert sql == 'ALTER TABLE "myschema"."orders" ADD ("amount" NUMBER(10,2))'

    def test_get_parameter_placeholders(self):
        p = _Provider()
        assert p.get_parameter_placeholders(3) == "?, ?, ?"


class TestGetTables:
    def test_returns_table_names(self):
        p = _Provider()
        p.query_results["TABLE_NAME NOT LIKE 'BIN$%'"] = [
            {"table_name": "ORDERS"},
            {"table_name": "ITEMS"},
        ]
        assert p.get_tables("MYSCHEMA") == ["ORDERS", "ITEMS"]

    def test_empty(self):
        p = _Provider()
        assert p.get_tables("MYSCHEMA") == []


class TestGetSchemas:
    def test_returns_usernames(self):
        p = _Provider()
        p.query_results["ALL_USERS ORDER BY USERNAME"] = [
            {"username": "APP"},
            {"username": "DBLIFT"},
        ]
        assert p.get_schemas() == ["APP", "DBLIFT"]


class TestCreateMigrationLockTableIfNotExists:
    def test_skips_when_exists(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        p.create_migration_lock_table_if_not_exists("MYSCHEMA")

        assert not any("CREATE TABLE" in s[0] for s in p.statements)

    def test_creates_when_missing(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]

        p.create_migration_lock_table_if_not_exists("MYSCHEMA")

        assert any("CREATE TABLE" in s[0] and "DBLIFT_MIGRATION_LOCK" in s[0] for s in p.statements)

    def test_already_exists_error_is_swallowed(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]
        p.statement_results["CREATE TABLE"] = Exception("ORA-00955: name is already used")

        p.create_migration_lock_table_if_not_exists("MYSCHEMA")  # no raise

        p.log.debug.assert_called()

    def test_other_error_propagates(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]
        p.statement_results["CREATE TABLE"] = Exception("ORA-12345: boom")

        with pytest.raises(Exception, match="ORA-12345"):
            p.create_migration_lock_table_if_not_exists("MYSCHEMA")


class TestAcquireMigrationLock:
    def test_immediate_success(self):
        p = _Provider()
        p.query_results["GET_HASH_VALUE"] = [{"lock_hash": 123}]
        p.query_results["DBMS_LOCK.REQUEST"] = [{"result": 0}]

        assert p.acquire_migration_lock("MYSCHEMA") is True
        assert p._lock_handles[p.get_lock_key("MYSCHEMA")] == 123

    def test_already_own_lock(self):
        p = _Provider()
        p.query_results["GET_HASH_VALUE"] = [{"lock_hash": 123}]
        p.query_results["DBMS_LOCK.REQUEST"] = [{"result": 4}]

        assert p.acquire_migration_lock("MYSCHEMA") is True

    def test_retries_then_succeeds(self):
        p = _Provider()
        p.query_results["GET_HASH_VALUE"] = [{"lock_hash": 123}]
        results = iter([[{"result": 1}], [{"result": 0}]])
        p.query_results["DBMS_LOCK.REQUEST"] = lambda params: next(results)

        assert p.acquire_migration_lock("MYSCHEMA") is True

    def test_no_hash_row_uses_fallback_hash(self):
        p = _Provider()
        p.query_results["GET_HASH_VALUE"] = []
        p.query_results["DBMS_LOCK.REQUEST"] = [{"result": 0}]

        assert p.acquire_migration_lock("MYSCHEMA") is True

    def test_other_result_code_falls_back_to_table_lock(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["GET_HASH_VALUE"] = [{"lock_hash": 123}]
        p.query_results["DBMS_LOCK.REQUEST"] = [{"result": 99}]
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]

        assert p.acquire_migration_lock("MYSCHEMA") is True
        assert any("INSERT INTO" in s[0] for s in p.statements)

    def test_exception_during_request_falls_back_to_table_lock(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["GET_HASH_VALUE"] = [{"lock_hash": 123}]
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]
        p.query_results["DBMS_LOCK.REQUEST"] = _raise(Exception("DBMS_LOCK not available"))

        assert p.acquire_migration_lock("MYSCHEMA") is True

    def test_timeout_returns_false(self):
        p = _Provider()
        p.query_results["GET_HASH_VALUE"] = [{"lock_hash": 123}]

        result = p.acquire_migration_lock("MYSCHEMA", wait_timeout_seconds=0)

        assert result is False
        p.log.warning.assert_called()


class TestAcquireTableLock:
    def test_succeeds_first_try(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        result = p._acquire_table_lock("MYSCHEMA", "LOCK1", "LOCK1", 60)

        assert result is True
        assert p._lock_handles["LOCK1"] is None

    def test_retries_on_unique_violation_then_succeeds(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]
        attempts = iter([Exception("ORA-00001: unique constraint violated"), 1])

        def insert_result(_sql, _schema, _params):
            outcome = next(attempts)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        p.statement_results["INSERT INTO"] = insert_result

        result = p._acquire_table_lock("MYSCHEMA", "LOCK1", "LOCK1", 60)

        assert result is True

    def test_non_retryable_error_returns_false(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]
        p.statement_results["INSERT INTO"] = Exception("ORA-00942: table or view does not exist")

        result = p._acquire_table_lock("MYSCHEMA", "LOCK1", "LOCK1", 60)

        assert result is False
        p.log.warning.assert_called()

    def test_timeout_returns_false(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        result = p._acquire_table_lock("MYSCHEMA", "LOCK1", "LOCK1", 0)

        assert result is False


class TestReleaseMigrationLock:
    def test_native_release_success_no_table(self):
        p = _Provider()
        lock_key = p.get_lock_key("MYSCHEMA")
        p._lock_handles[lock_key] = 555
        p.query_results["DBMS_LOCK.RELEASE"] = [{"result": 0}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]

        result = p.release_migration_lock("MYSCHEMA")

        assert result is True
        assert lock_key not in p._lock_handles

    def test_native_release_nonzero_and_table_delete_succeeds(self):
        p = _Provider()
        lock_key = p.get_lock_key("MYSCHEMA")
        p._lock_handles[lock_key] = 555
        p.query_results["DBMS_LOCK.RELEASE"] = [{"result": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]
        p.statement_results["DELETE FROM"] = 1

        result = p.release_migration_lock("MYSCHEMA")

        assert result is True

    def test_native_release_raises_is_handled(self):
        p = _Provider()
        lock_key = p.get_lock_key("MYSCHEMA")
        p._lock_handles[lock_key] = 555
        p.query_results["DBMS_LOCK.RELEASE"] = _raise(Exception("release failed"))
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]

        result = p.release_migration_lock("MYSCHEMA")

        assert result is False
        p.log.debug.assert_called()

    def test_no_lock_handle_checks_table_only(self):
        p = _Provider()
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]
        p.statement_results["DELETE FROM"] = 0

        result = p.release_migration_lock("MYSCHEMA")

        assert result is False

    def test_table_exists_check_raises_is_handled(self):
        p = _Provider()
        lock_key = p.get_lock_key("MYSCHEMA")
        p._lock_handles[lock_key] = 555
        p.query_results["DBMS_LOCK.RELEASE"] = [{"result": 0}]
        p.query_results["TABLE_NAME = ?"] = _raise(Exception("table check failed"))

        result = p.release_migration_lock("MYSCHEMA")

        assert result is True
        p.log.debug.assert_called()


class TestCreateHistoryTable:
    def test_returns_ddl(self):
        p = _Provider()
        sql = p.create_history_table("myschema", "dblift_schema_history")
        assert "CREATE TABLE" in sql
        assert "INSTALLED_RANK" in sql
        assert _schema_object("myschema", _oracle_name("dblift_schema_history")) in sql


class TestCreateMigrationHistoryTableIfNotExists:
    def test_creates_when_missing(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]

        p.create_migration_history_table_if_not_exists("MYSCHEMA")

        assert any("INSTALLED_RANK" in s[0] for s in p.statements)

    def test_skips_when_exists_no_create_schema(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        p.create_migration_history_table_if_not_exists("MYSCHEMA")

        assert p.statements == []

    def test_existing_with_create_schema_runs_baseline_check(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]
        p.query_results["SELECT COUNT(1) AS count"] = [{"count": 0}]

        p.create_migration_history_table_if_not_exists("MYSCHEMA", create_schema=True)

        assert p.statements == []


class TestCheckBaselineSafety:
    def test_raises_when_history_present(self):
        p = _Provider()
        p.query_results["SELECT COUNT(1) AS count"] = [{"count": 5}]

        with pytest.raises(RuntimeError, match="5 migration"):
            p._check_baseline_safety("MYSCHEMA", "dblift_schema_history")

    def test_passes_with_empty_history(self):
        p = _Provider()
        p.query_results["SELECT COUNT(1) AS count"] = [{"count": 0}]

        p._check_baseline_safety("MYSCHEMA", "dblift_schema_history")  # no exception


class TestCreateSnapshotTableIfNotExists:
    def test_creates_when_missing(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]

        p.create_snapshot_table_if_not_exists("MYSCHEMA")

        assert any("MODEL_DATA CLOB" in s[0] for s in p.statements)

    def test_skips_when_exists(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        p.create_snapshot_table_if_not_exists("MYSCHEMA")

        assert p.statements == []


class TestRecordMigration:
    def test_inserts_row_success(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        p.record_migration(
            "MYSCHEMA",
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

        sql, _schema, params = p.statements[-1]
        assert "INSERT INTO" in sql
        assert params[0] == "1"
        assert params[-1] == 1

    def test_failure_uses_zero_success(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        p.record_migration("MYSCHEMA", {"version": "1", "success": False})

        _sql, _schema, params = p.statements[-1]
        assert params[-1] == 0


class TestGetAppliedMigrations:
    def test_no_table(self):
        p = _Provider()
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]
        assert p.get_applied_migrations("MYSCHEMA") == []

    def test_normalizes_success_and_status(self):
        p = _Provider()
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]
        p.query_results["ORDER BY INSTALLED_RANK"] = [
            {"SCRIPT": "V1.sql", "SUCCESS": 1},
            {"SCRIPT": "V2.sql", "SUCCESS": 0},
            {"SCRIPT": "V3.sql", "SUCCESS": None},
        ]

        rows = p.get_applied_migrations("MYSCHEMA")

        assert rows[0]["success"] is True and rows[0]["status"] == "SUCCESS"
        assert rows[1]["success"] is False and rows[1]["status"] == "FAILED"
        assert rows[2]["success"] is None and rows[2]["status"] == "FAILED"


class TestRecordUndo:
    def test_records_synthetic_undo_migration(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        assert p.record_undo("MYSCHEMA", "1", script_name="U1__undo.sql") is True

        sql, _schema, params = p.statements[-1]
        assert "INSERT INTO" in sql
        assert params[2] == "UNDO_SQL"
        assert params[3] == "U1__undo.sql"

    def test_default_script_name(self):
        p = _Provider(username="MYSCHEMA")
        p.query_results["FROM ALL_USERS WHERE username"] = [{"user_count": 1}]
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        p.record_undo("MYSCHEMA", "2")

        _sql, _schema, params = p.statements[-1]
        assert params[3] == "UNDO_2.sql"


class TestRepairMigrationHistory:
    def test_no_table(self):
        p = _Provider()
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 0}]
        assert p.repair_migration_history("MYSCHEMA", "V1.sql", 123) is False

    def test_without_success_value(self):
        p = _Provider()
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        result = p.repair_migration_history("MYSCHEMA", "V1.sql", 999)

        assert result is True
        sql, _schema, params = p.statements[-1]
        assert "SUCCESS = 0" in sql
        assert params == [999, "V1.sql"]

    def test_with_success_value(self):
        p = _Provider()
        p.query_results["TABLE_NAME = ?"] = [{"cnt": 1}]

        result = p.repair_migration_history("MYSCHEMA", "V1.sql", 999, success_value=True)

        assert result is True
        sql, _schema, params = p.statements[-1]
        assert "SUCCESS = ?" in sql
        assert params == [999, 1, "V1.sql"]


class TestCleanSchema:
    def _query_map(self, include_sys_sequence=False):
        seq_rows = [{"object_name": "SEQ1"}]
        if include_sys_sequence:
            seq_rows.append({"object_name": "ISEQ$$_1"})
        return {
            "ALL_DB_LINKS": [{"object_name": "REMOTE_LINK"}, {"object_name": None}],
            "ALL_VIEWS": [{"object_name": "V1"}, {"object_name": None}],
            "ALL_MVIEWS": [{"object_name": "MV1"}],
            "TABLE_NAME NOT LIKE 'BIN$%'": [{"object_name": "T1"}],
            "ALL_SEQUENCES": seq_rows,
            "ALL_TAB_IDENTITY_COLS": lambda params: (
                [{"cnt": 1}] if params[1] == "ISEQ$$_1" else [{"cnt": 0}]
            ),
            "DECODE(OBJECT_TYPE": [
                {"object_name": "PROC1", "object_type": "PROCEDURE"},
                {"object_name": "TYPE1", "object_type": "TYPE"},
                {"object_name": None, "object_type": "FUNCTION"},
            ],
            "ALL_SYNONYMS": [{"object_name": "SYN1"}, {"object_name": None}],
        }

    def test_drops_all_object_types(self):
        p = _Provider()
        p.query_results = self._query_map(include_sys_sequence=True)

        summary = p.clean_schema("MYSCHEMA")

        statements = [s[0] for s in p.statements]
        assert any("DROP DATABASE LINK" in s for s in statements)
        assert any("DROP VIEW" in s for s in statements)
        assert any("DROP MATERIALIZED VIEW" in s for s in statements)
        assert any(s.startswith("DROP TABLE") and "CASCADE CONSTRAINTS" in s for s in statements)
        assert any("DROP SEQUENCE" in s and "SEQ1" in s for s in statements)
        assert not any("ISEQ$$_1" in s for s in statements)
        assert any("DROP PROCEDURE" in s for s in statements)
        assert any("DROP TYPE" in s and "FORCE" in s for s in statements)
        assert any("DROP SYNONYM" in s for s in statements)
        assert summary.statements

    def test_get_clean_preview_does_not_execute(self):
        p = _Provider()
        p.query_results = self._query_map()

        summary = p.get_clean_preview("MYSCHEMA")

        assert p.statements == []
        assert summary.statements

    def test_query_failures_for_each_section_are_handled(self):
        p = _Provider()

        def execute_query(sql, params=None):
            p.queries.append((sql, params))
            raise Exception("query failed")

        p.execute_query = execute_query

        summary = p.clean_schema("MYSCHEMA")

        assert p.log.debug.call_count >= 6
        assert summary.statements == []
        assert summary.errors == []

    def test_drop_failures_are_recorded_as_errors(self):
        p = _Provider()
        p.query_results = self._query_map()
        p.statement_results["DROP DATABASE LINK"] = Exception("link drop failed")
        p.statement_results["DROP VIEW"] = Exception("view drop failed")
        p.statement_results["DROP PROCEDURE"] = Exception("procedure drop failed")
        p.statement_results["DROP SYNONYM"] = Exception("synonym drop failed")

        summary = p.clean_schema("MYSCHEMA")

        assert any("database_link" in e for e in summary.errors)
        assert any("view" in e for e in summary.errors)
        assert any("procedure" in e for e in summary.errors)
        assert any("synonym" in e for e in summary.errors)
