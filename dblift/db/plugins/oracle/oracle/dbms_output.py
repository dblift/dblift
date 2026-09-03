"""Oracle DBMS_OUTPUT capture via native DB-API connections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dblift.core.logger import Log

__all__ = ["enable_dbms_output", "read_dbms_output"]


def _dbapi_connection(connection: Any) -> Any:
    """Return the DB-API connection behind a SQLAlchemy Connection if present."""
    return getattr(connection, "connection", connection)


def enable_dbms_output(connection: Any) -> None:
    """Enable Oracle DBMS_OUTPUT with unlimited buffer size."""
    execute = getattr(connection, "exec_driver_sql", None)
    if callable(execute):
        execute("BEGIN DBMS_OUTPUT.ENABLE(NULL); END;")
        return

    cursor = _dbapi_connection(connection).cursor()
    try:
        cursor.execute("BEGIN DBMS_OUTPUT.ENABLE(NULL); END;")
    finally:
        cursor.close()


def read_dbms_output(connection: Any, log: "Log") -> None:
    """Drain the DBMS_OUTPUT buffer and log each line via log.info.

    Calls DBMS_OUTPUT.GET_LINE in a loop until status != 0 (no more lines).
    """
    cursor = _dbapi_connection(connection).cursor()
    try:
        line_var = cursor.var(str)
        status_var = cursor.var(int)
        while True:
            cursor.callproc("DBMS_OUTPUT.GET_LINE", [line_var, status_var])
            if status_var.getvalue() != 0:
                break
            line = line_var.getvalue()
            if line is not None:
                log.info(f"[DB] {line}")
    finally:
        cursor.close()
