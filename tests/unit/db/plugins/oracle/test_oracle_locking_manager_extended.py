"""Extended unit tests for :class:`db.plugins.oracle.oracle.locking_manager.OracleLockingManager`."""

from unittest.mock import MagicMock

import pytest

from db.plugins.oracle.oracle import locking_manager as locking_manager_module
from db.plugins.oracle.oracle.locking_manager import OracleLockingManager


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(locking_manager_module.time, "sleep", lambda *_: None)


def _make(provider=None):
    qe = MagicMock()
    log = MagicMock()
    return OracleLockingManager(query_executor=qe, log=log, provider=provider), qe, log


class TestGetDropTableSql:
    def test_returns_drop_table_without_if_exists(self):
        mgr, _, _ = _make()
        assert mgr._get_drop_table_sql('"SCHEMA"."TBL"') == 'DROP TABLE "SCHEMA"."TBL"'


class TestAcquireMigrationLockDbmsLock:
    def test_lock_acquired_immediately(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.execute_query.side_effect = [
            [{"hash": 123}],  # handle hash lookup
            [{"result": 0}],  # acquire result: success
        ]

        assert mgr.acquire_migration_lock(conn, "myschema") is True

    def test_already_own_lock(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.execute_query.side_effect = [
            [{"hash": 123}],
            [{"result": 4}],
        ]

        assert mgr.acquire_migration_lock(conn, "myschema") is True

    def test_retries_on_timeout_then_succeeds(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.execute_query.side_effect = [
            [{"hash": 123}],
            [{"result": 1}],
            [{"result": 0}],
        ]

        assert mgr.acquire_migration_lock(conn, "myschema") is True

    def test_no_hash_result_falls_back_to_deterministic_hash(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.execute_query.side_effect = [
            [],  # no hash row -> deterministic fallback
            [{"result": 0}],
        ]

        assert mgr.acquire_migration_lock(conn, "myschema") is True

    def test_dbms_lock_request_other_code_falls_back_to_table(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.table_exists.return_value = False

        qe.execute_query.side_effect = [
            [{"hash": 123}],
            [{"result": 99}],
        ]
        qe.execute_statement.return_value = 1

        assert mgr.acquire_migration_lock(conn, "myschema") is True
        # falls back to table-based lock, which calls create + insert
        assert qe.execute_statement.called

    def test_empty_lock_result_falls_back_to_table(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.table_exists.return_value = False

        qe.execute_query.side_effect = [
            [{"hash": 123}],
            [],
        ]
        qe.execute_statement.return_value = 1

        assert mgr.acquire_migration_lock(conn, "myschema") is True

    def test_exception_during_acquire_falls_back_to_table(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.table_exists.return_value = False

        def execute_query_side_effect(connection, sql, params=None, silent=False):
            if "GET_HASH_VALUE" in sql:
                return [{"hash": 123}]
            raise Exception("DBMS_LOCK error")

        qe.execute_query.side_effect = execute_query_side_effect
        qe.execute_statement.return_value = 1

        assert mgr.acquire_migration_lock(conn, "myschema") is True

    def test_timeout_exhausted_returns_false(self):
        mgr, qe, log = _make()
        conn = MagicMock()
        qe.execute_query.side_effect = [
            [{"hash": 123}],
        ]

        result = mgr.acquire_migration_lock(conn, "myschema", wait_timeout_seconds=0)

        assert result is False
        log.warning.assert_called()

    def test_outer_exception_falls_back_to_table(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.table_exists.return_value = False
        qe.execute_statement.return_value = 1

        def execute_query_side_effect(connection, sql, params=None, silent=False):
            raise Exception("connection lost")

        qe.execute_query.side_effect = execute_query_side_effect

        assert mgr.acquire_migration_lock(conn, "myschema") is True


class TestAcquireTableBasedLock:
    def test_succeeds_on_first_try(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.table_exists.return_value = True
        qe.execute_statement.return_value = 1

        result = mgr._acquire_table_based_lock(conn, "myschema", "LOCK1", "LOCK1", 60)

        assert result is True
        assert mgr._lock_handles["LOCK1"] is None

    def test_retries_on_unique_violation_then_succeeds(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.table_exists.return_value = True
        qe.execute_statement.side_effect = [Exception("ORA-00001: unique constraint"), 1]

        result = mgr._acquire_table_based_lock(conn, "myschema", "LOCK1", "LOCK1", 60)

        assert result is True

    def test_non_retryable_error_returns_false(self):
        mgr, qe, log = _make()
        conn = MagicMock()
        qe.table_exists.return_value = True
        qe.execute_statement.side_effect = Exception("permission denied")

        result = mgr._acquire_table_based_lock(conn, "myschema", "LOCK1", "LOCK1", 60)

        assert result is False
        log.warning.assert_called()

    def test_timeout_returns_false(self):
        mgr, qe, log = _make()
        conn = MagicMock()
        qe.table_exists.return_value = True

        result = mgr._acquire_table_based_lock(conn, "myschema", "LOCK1", "LOCK1", 0)

        assert result is False
        log.warning.assert_called()

    def test_outer_exception_returns_false(self):
        mgr, qe, log = _make()
        conn = MagicMock()
        qe.table_exists.side_effect = Exception("boom")

        result = mgr._acquire_table_based_lock(conn, "myschema", "LOCK1", "LOCK1", 60)

        assert result is False
        log.error.assert_called()


class TestReleaseMigrationLock:
    def test_release_native_lock_success(self):
        mgr, qe, log = _make()
        conn = MagicMock()
        lock_key = mgr.get_lock_key("myschema")
        mgr._lock_handles[lock_key] = 555
        qe.execute_query.return_value = [{"result": 0}]
        qe.table_exists.return_value = False

        result = mgr.release_migration_lock(conn, "myschema")

        assert result is True
        assert lock_key not in mgr._lock_handles

    def test_release_native_lock_nonzero_code(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        lock_key = mgr.get_lock_key("myschema")
        mgr._lock_handles[lock_key] = 555
        qe.execute_query.return_value = [{"result": 4}]
        qe.table_exists.return_value = False

        result = mgr.release_migration_lock(conn, "myschema")

        assert result is False

    def test_release_native_lock_raises_is_handled(self):
        mgr, qe, log = _make()
        conn = MagicMock()
        lock_key = mgr.get_lock_key("myschema")
        mgr._lock_handles[lock_key] = 555
        qe.execute_query.side_effect = Exception("release error")
        qe.table_exists.return_value = False

        result = mgr.release_migration_lock(conn, "myschema")

        assert result is False

    def test_release_table_based_lock_with_commit(self):
        provider = MagicMock()
        mgr, qe, log = _make(provider=provider)
        conn = MagicMock()
        qe.table_exists.return_value = True
        qe.execute_statement.return_value = 1

        result = mgr.release_migration_lock(conn, "myschema")

        assert result is True
        provider.commit_transaction.assert_called_once()

    def test_release_table_based_lock_commit_error_is_non_fatal(self):
        provider = MagicMock()
        provider.commit_transaction.side_effect = Exception("commit failed")
        mgr, qe, log = _make(provider=provider)
        conn = MagicMock()
        qe.table_exists.return_value = True
        qe.execute_statement.return_value = 1

        result = mgr.release_migration_lock(conn, "myschema")

        assert result is True

    def test_release_table_based_lock_no_rows_deleted(self):
        mgr, qe, _ = _make()
        conn = MagicMock()
        qe.table_exists.return_value = True
        qe.execute_statement.return_value = 0

        result = mgr.release_migration_lock(conn, "myschema")

        assert result is False

    def test_release_table_cleanup_exception_is_handled(self):
        mgr, qe, log = _make()
        conn = MagicMock()
        qe.table_exists.side_effect = Exception("table check failed")

        result = mgr.release_migration_lock(conn, "myschema")

        assert result is False

    def test_outer_exception_returns_false(self):
        mgr, qe, log = _make()
        conn = MagicMock()
        mgr.get_lock_name = MagicMock(side_effect=Exception("boom"))

        result = mgr.release_migration_lock(conn, "myschema")

        assert result is False
        log.error.assert_called()
