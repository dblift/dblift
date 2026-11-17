"""PostgreSQL tells a transaction the script left open from the driver's status."""

import threading
from enum import IntEnum
from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import ExecutionError
from dblift.db.plugins.alloydb.plugin import PLUGIN as ALLOYDB
from dblift.db.plugins.aurora_postgresql.plugin import PLUGIN as AURORA
from dblift.db.plugins.citus.plugin import PLUGIN as CITUS
from dblift.db.plugins.cockroachdb.provider import CockroachdbProvider
from dblift.db.plugins.neon.plugin import PLUGIN as NEON
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.plugins.redshift.provider import RedshiftProvider
from dblift.db.plugins.supabase.plugin import PLUGIN as SUPABASE
from dblift.db.plugins.timescaledb.plugin import PLUGIN as TIMESCALEDB
from dblift.db.plugins.yugabytedb.plugin import PLUGIN as YUGABYTEDB


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


_PG_WIRE_PLUGINS = [NEON, SUPABASE, AURORA, ALLOYDB, YUGABYTEDB, TIMESCALEDB, CITUS]


def test_only_postgresql_itself_supports_a_script_session():
    assert object.__new__(PostgreSqlProvider).supports_script_session() is True


@pytest.mark.parametrize("plugin", _PG_WIRE_PLUGINS, ids=lambda p: p.name)
def test_pg_wire_compatible_providers_do_not_inherit_the_session(plugin):
    assert object.__new__(plugin.provider_class).supports_script_session() is False


@pytest.mark.parametrize("cls", [CockroachdbProvider, RedshiftProvider])
def test_cockroachdb_and_redshift_do_not_support_a_script_session(cls):
    assert object.__new__(cls).supports_script_session() is False


def test_a_subclass_with_another_dialect_key_is_not_enabled():
    class Other(PostgreSqlProvider):
        canonical_dialect_key = "other"

    assert object.__new__(Other).supports_script_session() is False
