"""A chunk holding several statements runs as one query and reports every error."""

from __future__ import annotations

from typing import Any, List, Optional

import pytest
from pymysql.constants import CLIENT

from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.provider import _drain_result_sets
from dblift.db.plugins.mysql.quirks import MysqlQuirks


class _FakeCursor:
    """Pymysql-shaped cursor: ``nextset`` walks a script of results or errors."""

    def __init__(self, script: List[Optional[Exception]]) -> None:
        self._script = list(script)
        self.calls = 0

    def nextset(self) -> Optional[bool]:
        self.calls += 1
        if not self._script:
            return None
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return True


def _drain(cursor: Any) -> None:
    _drain_result_sets(None, cursor, "", None, None, False)


@pytest.mark.parametrize("quirks", [MysqlQuirks(), MariadbQuirks()])
def test_engine_options_enable_multi_statements(quirks: Any) -> None:
    flag = quirks.engine_pool_options()["connect_args"]["client_flag"]
    assert flag & CLIENT.MULTI_STATEMENTS


def test_drain_consumes_every_result_set() -> None:
    cursor = _FakeCursor([None, None])
    _drain(cursor)
    # Two further results, then the call that reports there are no more.
    assert cursor.calls == 3


def test_drain_on_a_single_statement_is_one_call() -> None:
    cursor = _FakeCursor([])
    _drain(cursor)
    assert cursor.calls == 1


def test_drain_surfaces_a_later_statement_error() -> None:
    cursor = _FakeCursor([None, RuntimeError("1146 table doesn't exist")])
    with pytest.raises(RuntimeError, match="1146"):
        _drain(cursor)
