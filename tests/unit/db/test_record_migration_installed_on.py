"""``record_migration`` must persist a caller-supplied ``installed_on``.

``import-flyway`` copies rows out of ``flyway_schema_history`` into
``dblift_schema_history``. The source row's ``installed_on`` is the date
Flyway really applied the migration, and it is paired with a real
``installed_by``. Every SQL provider used to leave the column out of its
INSERT and let the DDL default (``CURRENT_TIMESTAMP``) stamp the row, so an
imported row ended up attributing a fabricated date to a real person.

Only the SQL dialects Flyway itself targets are covered here. MongoDB and
Cosmos DB are document stores Flyway does not support; their history managers
already honour ``installed_on`` and are out of scope.
"""

from __future__ import annotations

import datetime
import importlib
from typing import Any, Dict, List, Optional, Type

import pytest

from dblift.db.plugins.db2.provider import Db2Provider
from dblift.db.plugins.duckdb.provider import DuckDBProvider
from dblift.db.plugins.mariadb.provider import MariadbProvider
from dblift.db.plugins.mysql.provider import MySqlProvider
from dblift.db.plugins.oracle.provider import OracleProvider
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.plugins.sqlserver.provider import SqlServerProvider

pytestmark = pytest.mark.unit

#: A date only Flyway could have produced — years before this test runs, so a
#: row carrying it cannot have been stamped by the history table's default.
FLYWAY_INSTALLED_ON = datetime.datetime(2023, 4, 15, 9, 12, 0)

_SQL_PROVIDERS = [
    pytest.param(PostgreSqlProvider, id="postgresql"),
    pytest.param(MySqlProvider, id="mysql"),
    pytest.param(MariadbProvider, id="mariadb"),
    pytest.param(OracleProvider, id="oracle"),
    pytest.param(SqlServerProvider, id="sqlserver"),
    pytest.param(Db2Provider, id="db2"),
    pytest.param(DuckDBProvider, id="duckdb"),
]

#: PostgreSQL-wire-compatible distributions. They must reuse PostgreSQL's
#: ``record_migration`` rather than carrying a copy that could drift.
_PG_COMPATIBLE_DIALECTS = [
    "neon",
    "supabase",
    "aurora_postgresql",
    "alloydb",
    "yugabytedb",
    "timescaledb",
    "citus",
    "cockroachdb",
]


class _StatementRecorder:
    """Capture the SQL and bound parameters of the last statement executed.

    An explicit fake rather than a ``MagicMock``: a mock would accept any
    call shape, so a provider that stopped calling ``execute_statement``
    altogether would still look green.
    """

    def __init__(self) -> None:
        self.sql: str = ""
        self.params: List[Any] = []

    def __call__(self, sql: str, params: Optional[List[Any]] = None, **_: Any) -> int:
        self.sql = sql
        self.params = list(params or [])
        return 1


def _provider(provider_cls: Type[Any]) -> Any:
    """Build a provider with only the surface ``record_migration`` uses.

    ``object.__new__`` skips the driver/config wiring the write path does not
    need, keeping the test focused on the INSERT the provider emits.
    """
    provider = object.__new__(provider_cls)
    provider.create_migration_history_table_if_not_exists = lambda *a, **k: None
    provider.get_schema_qualified_name = lambda schema, table: f"{schema}.{table}"
    provider.execute_statement = _StatementRecorder()
    return provider


def _migration_info(**extra: Any) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "version": "1",
        "description": "flyway import",
        "type": "SQL",
        "script": "V1__a.sql",
        "checksum": 123,
        "installed_by": "alice",
        "execution_time": 42,
        "success": True,
    }
    info.update(extra)
    return info


@pytest.mark.parametrize("provider_cls", _SQL_PROVIDERS)
def test_supplied_installed_on_is_written(provider_cls: Type[Any]) -> None:
    """A caller-supplied ``installed_on`` must reach the INSERT as a bound value."""
    provider = _provider(provider_cls)

    provider.record_migration(
        "myschema",
        _migration_info(installed_on=FLYWAY_INSTALLED_ON),
        "dblift_schema_history",
    )

    recorder = provider.execute_statement
    assert "installed_on" in recorder.sql.lower(), recorder.sql
    assert FLYWAY_INSTALLED_ON in recorder.params, recorder.params


@pytest.mark.parametrize("provider_cls", _SQL_PROVIDERS)
def test_omitted_installed_on_leaves_the_column_default_in_charge(
    provider_cls: Type[Any],
) -> None:
    """The ``migrate`` path supplies no ``installed_on``; the DDL default must still apply.

    Asserted as "no timestamp is bound" rather than "the column is absent"
    because Oracle's INSERT names ``INSTALLED_ON`` with a ``SYSDATE`` literal
    — that literal is the default behaviour being preserved, not a bound value.
    """
    provider = _provider(provider_cls)

    provider.record_migration("myschema", _migration_info(), "dblift_schema_history")

    recorder = provider.execute_statement
    assert not any(isinstance(p, datetime.datetime) for p in recorder.params), recorder.params
    assert recorder.sql.count("?") == len(recorder.params), recorder.sql


@pytest.mark.parametrize("provider_cls", _SQL_PROVIDERS)
def test_blank_installed_on_falls_back_to_the_column_default(
    provider_cls: Type[Any],
) -> None:
    """``None``/empty must not be bound — ``installed_on`` is NOT NULL on some dialects."""
    for blank in (None, "", "   "):
        provider = _provider(provider_cls)

        provider.record_migration(
            "myschema", _migration_info(installed_on=blank), "dblift_schema_history"
        )

        recorder = provider.execute_statement
        assert blank not in recorder.params, (blank, recorder.params)
        assert recorder.sql.count("?") == len(recorder.params), recorder.sql


@pytest.mark.parametrize("dialect", _PG_COMPATIBLE_DIALECTS)
def test_pg_compatible_providers_reuse_postgresql_record_migration(dialect: str) -> None:
    """PG-wire-compatible plugins must inherit the fix, not re-implement it."""
    plugin = importlib.import_module(f"dblift.db.plugins.{dialect}.plugin").PLUGIN

    assert (
        plugin.provider_class.record_migration is PostgreSqlProvider.record_migration
    ), f"{dialect} overrides record_migration and needs its own installed_on handling"
