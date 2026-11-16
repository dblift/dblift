"""PostgreSQL tells a transaction the script left open from the driver's status."""

import threading
from enum import IntEnum
from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import ExecutionError
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider


class _Status(IntEnum):
    IDLE = 0
    ACTIVE = 1
    INTRANS = 2
    INERROR = 3


def _provider(driver_connection) -> PostgreSqlProvider:
    provider = object.__new__(PostgreSqlProvider)
    provider._lock = threading.RLock()
    provider._tx = None
    provider._connection = MagicMock()
    provider._connection.connection.dbapi_connection = driver_connection
    return provider


def _driver(status) -> MagicMock:
    driver = MagicMock()
    driver.info.transaction_status = status
    return driver


@pytest.mark.parametrize(
    "status,expected",
    [(_Status.IDLE, False), (_Status.INTRANS, True), (_Status.INERROR, True)],
)
def test_transaction_open_is_a_status_other_than_idle(status, expected):
    provider = _provider(_driver(status))

    assert provider._script_transaction_open(provider._connection) is expected


def test_a_driver_without_a_transaction_status_is_refused_before_the_switch():
    driver = MagicMock(spec=[])
    provider = _provider(driver)
    provider._ensure_connection = MagicMock(return_value=provider._connection)
    provider._connection.in_transaction.return_value = False

    with pytest.raises(ExecutionError, match="dblift:no-transaction needs a database driver"):
        provider.begin_script_session()

    provider._connection.execution_options.assert_not_called()
    assert not provider.has_explicit_transaction()
