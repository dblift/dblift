"""dblift commits the schema and history DDL it ran on a caller-owned connection.

The migration lock lives on a second connection. Where DDL is transactional
(Db2), that connection waits behind the schema and history table the caller's
open transaction has just created, so a later command on the same connection
never returns. Engines that autocommit DDL, or whose lock needs no second
connection, keep the caller's transaction untouched.
"""

from __future__ import annotations

from typing import List

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.db.plugins.cockroachdb.provider import CockroachdbProvider
from dblift.db.plugins.db2.provider import Db2Provider
from dblift.db.plugins.duckdb.provider import DuckDBProvider
from dblift.db.plugins.oracle.provider import OracleProvider
from dblift.db.plugins.snowflake.provider import SnowflakeProvider

pytestmark = [pytest.mark.unit]


def _provider(cls, caller_owned: bool):
    provider = object.__new__(cls)
    provider._external_connection = caller_owned
    return provider


@pytest.mark.parametrize("cls", [Db2Provider, CockroachdbProvider])
def test_transactional_ddl_on_a_caller_connection_is_settled(cls) -> None:
    assert _provider(cls, caller_owned=True).settles_preflight_ddl() is True


@pytest.mark.parametrize(
    "cls, caller_owned",
    [
        (Db2Provider, False),
        (OracleProvider, True),
        (SnowflakeProvider, True),
        (DuckDBProvider, True),
    ],
)
def test_other_providers_leave_the_caller_transaction_alone(cls, caller_owned) -> None:
    assert _provider(cls, caller_owned).settles_preflight_ddl() is False


def _client(tmp_path, command_dir: str = "migrations") -> DBLiftClient:
    migrations = tmp_path / command_dir
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path / 'a.sqlite'}")
    return DBLiftClient.from_sqlalchemy(connection=engine.connect(), migrations_dir=migrations)


def _record(client: DBLiftClient, settles: bool = True) -> List[str]:
    events: List[str] = []
    provider = client.provider
    history = client.executor.history_manager
    real = history.create_schema_and_history_table

    def create(*args, **kwargs):
        events.append("history")
        return real(*args, **kwargs)

    history.create_schema_and_history_table = create
    provider.settles_preflight_ddl = lambda: settles
    provider.note_caller_work = lambda: events.append("note")
    provider.commit_caller_work = lambda: events.append("commit")
    return events


COMMANDS = {
    "migrate": lambda c: c.migrate(),
    "validate": lambda c: c.validate(),
    "baseline": lambda c: c.baseline(version="1"),
    "repair": lambda c: c.repair(),
}


@pytest.mark.parametrize("command", COMMANDS)
def test_history_creation_is_committed_before_anything_else_runs(tmp_path, command) -> None:
    client = _client(tmp_path)
    events = _record(client)
    try:
        COMMANDS[command](client)
    finally:
        client.close()

    assert events[:3] == ["history", "note", "commit"], events


def test_an_existing_history_table_commits_nothing(tmp_path) -> None:
    client = _client(tmp_path)
    try:
        client.migrate()
        events = _record(client)
        client.validate()
    finally:
        client.close()

    assert "commit" not in events, events


def test_dry_run_commits_nothing(tmp_path) -> None:
    client = _client(tmp_path)
    events = _record(client)
    try:
        client.migrate(dry_run=True)
    finally:
        client.close()

    assert events == []


def test_a_provider_that_does_not_settle_commits_nothing(tmp_path) -> None:
    client = _client(tmp_path)
    events = _record(client, settles=False)
    try:
        client.migrate()
    finally:
        client.close()

    assert "commit" not in events and "note" not in events, events
