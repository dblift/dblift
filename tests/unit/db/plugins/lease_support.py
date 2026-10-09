"""Test double for the dedicated connection a migration lock lease runs on.

Provider tests record the statements a provider runs through a stubbed
``execute_statement``. The lease runs its statements on its own connection
(``provider.engine.connect()``); routing that connection to the same stub
keeps those tests asserting on one recorder.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, List, Optional


class RoutedLeaseConnection:
    """A lease connection whose statements go to *execute(sql, params)*."""

    def __init__(
        self,
        execute: Callable[[str, List[Any]], Any],
        rollback_error: Optional[Exception] = None,
    ) -> None:
        self._execute = execute
        self._rollback_error = rollback_error
        self.dialect = SimpleNamespace(paramstyle="qmark")
        self.events: List[str] = []

    def exec_driver_sql(self, sql: str, params: Any = None) -> SimpleNamespace:
        rowcount = self._execute(sql, list(params or ()))
        return SimpleNamespace(rowcount=1 if rowcount is None else rowcount, fetchall=list)

    def in_transaction(self) -> bool:
        return False

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")
        if self._rollback_error is not None:
            raise self._rollback_error

    def close(self) -> None:
        self.events.append("close")


def route_lease_to(
    provider: Any, rollback_error: Optional[Exception] = None
) -> List[RoutedLeaseConnection]:
    """Give *provider* an engine whose connections run on ``provider.execute_statement``.

    Returns the list the opened lease connections are appended to.
    """
    opened: List[RoutedLeaseConnection] = []

    def connect() -> RoutedLeaseConnection:
        connection = RoutedLeaseConnection(
            lambda sql, params: provider.execute_statement(sql, params=params), rollback_error
        )
        opened.append(connection)
        return connection

    provider._conn_mgr = SimpleNamespace(engine=SimpleNamespace(connect=connect))
    return opened
