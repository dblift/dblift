"""``COPY ... FROM stdin`` goes through the driver's copy API, not ``execute``.

psycopg refuses ``COPY ... FROM STDIN`` through ``cursor.execute`` and leaves
the connection mid-COPY, so the header and its data block (one statement since
the splitter keeps them together) must be streamed via ``cursor.copy()``
(psycopg 3) or ``cursor.copy_expert()`` (psycopg2).
"""

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import ExecutionError
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider

pytestmark = pytest.mark.unit


class _Psycopg3Cursor:
    def __init__(self):
        self.copy_sql = None
        self.written = []
        self.rowcount = 2
        self.closed = False

    def copy(self, sql):
        self.copy_sql = sql
        cursor = self

        class _Copy:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def write(self, data):
                cursor.written.append(data)

        return _Copy()

    def close(self):
        self.closed = True


class _Psycopg2Cursor:
    def __init__(self):
        self.copy_sql = None
        self.data = None
        self.rowcount = 2
        self.closed = False

    def copy_expert(self, sql, file):
        self.copy_sql = sql
        self.data = file.read()

    def close(self):
        self.closed = True


def _provider(cursor, driver="psycopg"):
    provider = object.__new__(PostgreSqlProvider)
    provider._tx = None
    conn = MagicMock()
    conn.dialect.driver = driver
    conn.closed = False
    conn.in_transaction.return_value = False
    conn.connection.cursor.return_value = cursor
    provider._connection = conn
    return provider, conn


def _copy_statement():
    sql = "COPY t (id, v) FROM stdin;\n1\talpha\n2\t\\N\n\\.\nSELECT 1;\n"
    return StatementSplitter("postgresql").split_statements(sql)[0]


def test_copy_from_stdin_streams_data_through_psycopg3_copy():
    cursor = _Psycopg3Cursor()
    provider, conn = _provider(cursor)

    rows = provider.execute_statement(_copy_statement())

    assert rows == 2
    assert cursor.copy_sql == "COPY t (id, v) FROM stdin"
    # The ``\.`` end-of-data line is psql framing, not data sent to the server.
    assert "".join(cursor.written) == "1\talpha\n2\t\\N\n"
    assert cursor.closed
    conn.exec_driver_sql.assert_not_called()
    conn.begin.assert_called_once()
    conn.commit.assert_called_once()


def test_copy_from_stdin_uses_copy_expert_on_psycopg2():
    cursor = _Psycopg2Cursor()
    provider, conn = _provider(cursor, driver="psycopg2")

    rows = provider.execute_statement(_copy_statement())

    assert rows == 2
    assert cursor.copy_sql == "COPY t (id, v) FROM stdin"
    assert cursor.data == "1\talpha\n2\t\\N\n"
    conn.exec_driver_sql.assert_not_called()


def test_copy_inside_open_transaction_is_not_committed():
    cursor = _Psycopg3Cursor()
    provider, conn = _provider(cursor)
    provider._tx = MagicMock()
    conn.in_transaction.return_value = True

    provider.execute_statement(_copy_statement())

    conn.begin.assert_not_called()
    conn.commit.assert_not_called()


def test_empty_copy_block_sends_no_rows():
    cursor = _Psycopg3Cursor()
    provider, _conn = _provider(cursor)
    sql = "COPY t (id) FROM stdin;\n\\.\n"
    statement = StatementSplitter("postgresql").split_statements(sql)[0]

    provider.execute_statement(statement)

    assert cursor.copy_sql == "COPY t (id) FROM stdin"
    assert "".join(cursor.written) == ""


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "COPY t FROM '/tmp/data.csv'",
        "COPY t TO '/tmp/stdout'",
    ],
)
def test_other_statements_still_go_through_exec_driver_sql(sql):
    cursor = _Psycopg3Cursor()
    provider, conn = _provider(cursor)
    conn.dialect.paramstyle = "pyformat"
    conn.exec_driver_sql.return_value.rowcount = 0

    provider.execute_statement(sql)

    conn.exec_driver_sql.assert_called_once()
    assert cursor.copy_sql is None


@pytest.mark.parametrize(
    "sql",
    [
        "COPY t TO stdout",
        'COPY "s"."T" (a, b) TO STDOUT WITH (FORMAT csv)',
        "copy (SELECT * FROM t) to Stdout;",
    ],
)
def test_copy_to_stdout_is_refused_before_anything_is_sent(sql):
    """psycopg refuses ``COPY ... TO STDOUT`` through ``execute`` and leaves
    the connection mid-COPY, so the failure could not be recorded nor the
    lock released. A migration has nowhere to send the rows anyway."""
    cursor = _Psycopg3Cursor()
    provider, conn = _provider(cursor)

    with pytest.raises(ExecutionError, match="COPY ... TO STDOUT"):
        provider.execute_statement(sql)

    conn.exec_driver_sql.assert_not_called()
    assert cursor.copy_sql is None


def test_split_copy_from_stdin_restores_the_row_terminator() -> None:
    from dblift.db.plugins.postgresql.provider import _split_copy_from_stdin

    assert _split_copy_from_stdin("COPY t (a) FROM STDIN;\n1\n2") == (
        "COPY t (a) FROM STDIN",
        "1\n2\n",
    )
    assert _split_copy_from_stdin("COPY t (a, b) FROM STDIN;\n1\t") == (
        "COPY t (a, b) FROM STDIN",
        "1\t\n",
    )
    assert _split_copy_from_stdin("COPY t FROM STDIN;") == ("COPY t FROM STDIN", "")
