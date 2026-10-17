"""The text a provider hands its driver is the text the engine's client would execute.

A splitter that keeps a statement's last character is no use if the provider strips it again before
the driver sees it. These tests feed each provider what the splitter returns for a script that ends
in a no-break space, and compare what reaches the driver, byte for byte, with what the engine's
client sends. The seam is the provider built with ``object.__new__``, its connection mocked and a
recorder on ``exec_driver_sql``; SQLite goes through its query executor. YugabyteDB runs through the
PostgreSQL provider, so it has no case of its own.

A no-break space is a name character for PostgreSQL, CockroachDB, Redshift (kept for lack of a
measurement), MySQL, MariaDB, Db2, Snowflake (the same) and SQLite; a blank for SQL Server; a blank
for DuckDB before a terminator and a name character as the last character of the text.
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional, Tuple
from unittest import mock

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.migration_sql_parser import parse_migration_sql
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.cockroachdb.provider import CockroachdbProvider
from dblift.db.plugins.db2.provider import Db2Provider
from dblift.db.plugins.duckdb.provider import DuckDBProvider
from dblift.db.plugins.mariadb.provider import MariadbProvider
from dblift.db.plugins.mysql.provider import MySqlProvider
from dblift.db.plugins.oracle.provider import OracleProvider
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.plugins.redshift.provider import RedshiftProvider
from dblift.db.plugins.snowflake.provider import SnowflakeProvider
from dblift.db.plugins.sqlite.provider import SQLiteProvider
from dblift.db.plugins.sqlserver.provider import SqlServerProvider

NBSP = chr(0xA0)
PARAGRAPH_SEPARATOR = chr(0x2029)

PROVIDERS = {
    "postgresql": PostgreSqlProvider,
    "redshift": RedshiftProvider,
    "cockroachdb": CockroachdbProvider,
    "mysql": MySqlProvider,
    "mariadb": MariadbProvider,
    "db2": Db2Provider,
    "oracle": OracleProvider,
    "sqlserver": SqlServerProvider,
    "snowflake": SnowflakeProvider,
    "sqlite": SQLiteProvider,
    "duckdb": DuckDBProvider,
}


def provider_with_recorder(dialect: str):  # type: ignore[no-untyped-def]
    """A provider of ``dialect`` whose driver is a recorder; returns it with the list it records into."""
    provider = object.__new__(PROVIDERS[dialect])
    sent: List[str] = []
    connection = mock.MagicMock()
    connection.exec_driver_sql.side_effect = lambda sql, *a, **k: (
        sent.append(sql) or mock.MagicMock(rowcount=0)
    )
    provider._lock = threading.RLock()
    provider._tx = None
    provider._external_connection = True
    provider._ensure_connection = lambda: connection
    provider._ensure_schema_ready = lambda schema: None
    if dialect == "sqlite":
        executor = mock.MagicMock()
        executor.execute_statement.side_effect = (
            lambda conn, sql, params=None: sent.append(sql) or 0
        )
        provider.query_executor = executor
        provider._get_connection = lambda: None
        provider.connection = None
    return provider, sent


def drive(dialect: str, script: str) -> List[str]:
    """Split ``script`` as a migration is, run each statement through the provider, return what the driver got."""
    statements = parse_migration_sql(SqlAnalyzer(dialect=dialect), script, mock.MagicMock())
    provider, sent = provider_with_recorder(dialect)
    for statement in statements:
        provider.execute_statement(statement)
    return sent


SEMICOLON = f"DROP TABLE t{NBSP};"
END_OF_FILE = f"DROP TABLE t{NBSP}"
WITHOUT = "DROP TABLE t"

#: dialect -> (what the client sends for the ``;`` form, for the end-of-file form)
CLIENT_SENDS = {
    "postgresql": (SEMICOLON, END_OF_FILE),
    "redshift": (SEMICOLON, END_OF_FILE),
    "cockroachdb": (SEMICOLON, END_OF_FILE),
    "mysql": (END_OF_FILE, END_OF_FILE),
    "mariadb": (END_OF_FILE, END_OF_FILE),
    "db2": (END_OF_FILE, END_OF_FILE),
    "snowflake": (END_OF_FILE, END_OF_FILE),
    "sqlite": (END_OF_FILE, END_OF_FILE),
    # a no-break space is a blank to SQL Server (sqlcmd sends it, the server reads a blank): trimming it
    # at the end of the batch changes nothing the server reads
    "sqlserver": (SEMICOLON, WITHOUT),
    # before the terminator the shell reads a blank; as the last character of the text it is a name
    "duckdb": (WITHOUT, END_OF_FILE),
    # Oracle: python-oracledb would strip the character and the server rejects it, so it is refused
    "oracle": (None, None),
}

#: (dialect, form) -> why the case fails today
RED = {
    ("mysql", "semicolon"): "the splitter strips the character before the terminator",
    ("mysql", "end_of_file"): "the splitter strips the last character of the script",
    ("mariadb", "semicolon"): "the splitter strips the character before the terminator",
    ("mariadb", "end_of_file"): "the splitter strips the last character of the script",
    ("db2", "semicolon"): "the splitter and the provider strip the character before the terminator",
    ("db2", "end_of_file"): "the splitter and the provider strip the last character",
    ("duckdb", "semicolon"): "the splitter keeps a no-break space the shell reads as a blank",
}

SCRIPTS = {"semicolon": SEMICOLON, "end_of_file": END_OF_FILE}


def _cases() -> List[object]:
    cases = []
    for dialect in CLIENT_SENDS:
        for index, form in enumerate(SCRIPTS):
            marks = []
            if (dialect, form) in RED:
                marks.append(pytest.mark.xfail(strict=True, reason=RED[(dialect, form)]))
            cases.append(
                pytest.param(
                    dialect, form, CLIENT_SENDS[dialect][index], marks=marks, id=f"{dialect}-{form}"
                )
            )
    return cases


@pytest.mark.parametrize("dialect,form,expected", _cases())
def test_driver_receives_the_statement_as_the_client_sends_it(
    dialect: str, form: str, expected: Optional[str]
) -> None:
    if expected is None:  # refused before anything is sent
        with pytest.raises(UnsafeStatementSplitError):
            drive(dialect, SCRIPTS[form])
        return
    sent = drive(dialect, SCRIPTS[form])
    assert sent == [expected], f"the driver was handed {sent!r}, the client sends {expected!r}"


def test_sqlserver_batch_keeps_an_unmeasured_blank_at_its_end() -> None:
    text = f"SELECT 1{PARAGRAPH_SEPARATOR}"
    assert drive("sqlserver", text) == [text]


# Oracle: python-oracledb strips both sides of a statement before sending, and the server rejects a
# no-break space, so every white space character outside Oracle's blanks (probed or not) is refused
# rather than sent without it.
ORACLE_STRIPPED_BY_THE_DRIVER = {
    "U+00A0": f"DROP TABLE t{NBSP}",
    "U+00A0-semicolon": f"DROP TABLE t{NBSP};",
    "U+2003": f"DROP TABLE t{chr(0x2003)}",
    "U+0085": f"DROP TABLE t{chr(0x85)}",
    "U+2028": f"DROP TABLE t{chr(0x2028)}",
    "U+2029": f"DROP TABLE t{chr(0x2029)}",
    "U+1680": f"DROP TABLE t{chr(0x1680)}",
    "leading": f"{chr(0x2028)}SELECT 1 FROM dual;",
}


@pytest.mark.parametrize(
    "script", ORACLE_STRIPPED_BY_THE_DRIVER.values(), ids=ORACLE_STRIPPED_BY_THE_DRIVER
)
def test_oracle_never_sends_the_driver_stripped_form(script: str) -> None:
    refusal: Optional[UnsafeStatementSplitError] = None
    sent: List[str] = []
    try:
        sent = drive("oracle", script)
    except UnsafeStatementSplitError as exc:
        refusal = exc
    assert sent == [], f"the driver was handed {sent!r}"
    edge = next(c for c in script if c.isspace() and c != " ")
    assert refusal is not None and f"U+{ord(edge):04X}" in str(refusal)


def test_oracle_sends_a_trailing_comment_with_its_blank() -> None:
    text = f"SELECT 1 FROM dual -- note{NBSP}"
    assert drive("oracle", text) == [text]


ORACLE_ACCEPTED_SHAPES = {
    "comment": f"SELECT 1 FROM dual -- note{NBSP}",
    "comment-then-slash": f"SELECT 1 FROM dual -- note{NBSP}\n/\n",
    "slash": "SELECT 1 FROM dual\n/\n",
    "end-then-slash": "CREATE PROCEDURE p AS BEGIN NULL; END;\n/\n",
}


@pytest.mark.parametrize("script", ORACLE_ACCEPTED_SHAPES.values(), ids=ORACLE_ACCEPTED_SHAPES)
def test_oracle_does_not_refuse_a_blank_the_driver_leaves_alone(script: str) -> None:
    """Green pin: a blank inside a trailing comment, or a statement a ``/`` ends, is sent, not refused."""
    sent = drive("oracle", script)
    assert len(sent) == 1 and sent[0].startswith(("SELECT 1 FROM dual", "CREATE PROCEDURE p"))


def test_copy_from_stdin_header_keeps_its_last_character() -> None:
    script = f"COPY t (a) FROM STDIN{NBSP};\n1\n\\.\n"
    statements = parse_migration_sql(SqlAnalyzer(dialect="postgresql"), script, mock.MagicMock())
    provider = object.__new__(PostgreSqlProvider)
    headers: List[Tuple[str, str]] = []
    provider._lock = threading.RLock()
    provider._tx = None
    provider._ensure_connection = lambda: mock.MagicMock()
    provider._ensure_schema_ready = lambda schema: None
    provider._copy_from_stdin = lambda conn, header, data: headers.append((header, data)) or 1
    for statement in statements:
        provider.execute_statement(statement)
    assert headers == [(f"COPY t (a) FROM STDIN{NBSP}", "1\n")]


@pytest.mark.xfail(
    strict=True,
    reason="RETURNING is appended after the no-break space, which turns it into a blank",
)
def test_duckdb_returning_rewrite_keeps_a_final_no_break_space() -> None:
    provider = object.__new__(DuckDBProvider)
    sent: List[str] = []
    connection = mock.MagicMock()
    connection.exec_driver_sql.side_effect = lambda sql, *a, **k: (
        sent.append(sql) or mock.MagicMock(fetchall=lambda: [])
    )
    provider._tx = None
    provider._external_connection = True
    provider._ensure_connection = lambda: connection
    result = provider._try_dml_rowcount_via_returning(f"DELETE FROM t{NBSP}")
    assert sent == [], f"the driver was handed {sent!r}"
    assert result is None


@pytest.mark.parametrize("method", ["execute_statement", "execute_query"])
def test_oracle_provider_refuses_a_text_the_driver_would_strip(method: str) -> None:
    """The provider is called directly, with no splitter in front of it."""
    provider, sent = provider_with_recorder("oracle")
    refusal: Optional[UnsafeStatementSplitError] = None
    try:
        getattr(provider, method)(f"DROP TABLE t{NBSP}")
    except UnsafeStatementSplitError as exc:
        refusal = exc
    assert sent == [], f"the driver was handed {sent!r}"
    assert refusal is not None
