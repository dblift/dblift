"""Tests for Oracle DBMS_OUTPUT capture."""

from unittest.mock import MagicMock

import pytest

from dblift.db.plugins.oracle.oracle.dbms_output import enable_dbms_output, read_dbms_output


class TestEnableDbmsOutput:
    def test_executes_enable_block_with_dbapi_cursor(self):
        conn = MagicMock()
        conn.connection = conn
        conn.exec_driver_sql = None
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        enable_dbms_output(conn)

        cursor.execute.assert_called_once_with("BEGIN DBMS_OUTPUT.ENABLE(NULL); END;")
        cursor.close.assert_called_once()

    def test_uses_sqlalchemy_exec_driver_sql_when_available(self):
        conn = MagicMock()

        enable_dbms_output(conn)

        conn.exec_driver_sql.assert_called_once_with("BEGIN DBMS_OUTPUT.ENABLE(NULL); END;")
        conn.cursor.assert_not_called()

    def test_closes_cursor_on_exception(self):
        conn = MagicMock()
        conn.connection = conn
        conn.exec_driver_sql = None
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("DB-API error")
        conn.cursor.return_value = cursor

        with pytest.raises(RuntimeError):
            enable_dbms_output(conn)

        cursor.close.assert_called_once()


class TestReadDbmsOutput:
    def _make_connection(self, statuses, lines=None):
        conn = MagicMock()
        conn.connection = conn
        cursor = MagicMock()
        line_var = MagicMock()
        status_var = MagicMock()
        cursor.var.side_effect = [line_var, status_var]
        status_var.getvalue.side_effect = statuses
        line_var.getvalue.side_effect = lines or []
        conn.cursor.return_value = cursor
        return conn, cursor

    def test_reads_and_logs_all_lines(self):
        conn, cursor = self._make_connection([0, 0, 1], ["Hello", "World"])
        log = MagicMock()

        read_dbms_output(conn, log)

        assert cursor.callproc.call_count == 3
        log_calls = [str(c) for c in log.info.call_args_list]
        assert any("Hello" in c for c in log_calls)
        assert any("World" in c for c in log_calls)

    def test_skips_none_lines(self):
        conn, _ = self._make_connection([0, 1], [None])
        log = MagicMock()

        read_dbms_output(conn, log)

        log.info.assert_not_called()

    def test_no_output_exits_immediately(self):
        conn, cursor = self._make_connection([1])
        log = MagicMock()

        read_dbms_output(conn, log)

        cursor.callproc.assert_called_once()
        log.info.assert_not_called()

    def test_closes_cursor_after_loop(self):
        conn, cursor = self._make_connection([1])
        log = MagicMock()

        read_dbms_output(conn, log)

        cursor.close.assert_called_once()

    def test_closes_cursor_on_exception(self):
        conn, cursor = self._make_connection([1])
        cursor.callproc.side_effect = RuntimeError("DB-API error")
        log = MagicMock()

        with pytest.raises(RuntimeError):
            read_dbms_output(conn, log)

        cursor.close.assert_called_once()

    def test_allocates_line_and_status_vars(self):
        conn, cursor = self._make_connection([1])
        log = MagicMock()

        read_dbms_output(conn, log)

        cursor.var.assert_any_call(str)
        cursor.var.assert_any_call(int)
