"""A caller-owned connection never holds uncommitted DDL the lock session must read.

The migration lease runs on a second connection, so its lock table has to be
committed before the caller's connection starts creating the schema and the
history table. Created afterwards, the second connection's catalog read waits
behind the caller's uncommitted catalog rows (engines with transactional DDL)
and never returns.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from dblift.api import DBLiftClient
from dblift.core.logger import NullLog
from dblift.db.plugins.db2.provider import Db2Provider

pytestmark = [pytest.mark.unit]


class _LeaseProvider(Db2Provider):
    """A lease provider with no database behind it, recording what it does."""

    def __init__(self, caller_owned: bool, private: bool = False, fail=None) -> None:
        # No super().__init__: no database behind it.
        self._external_connection = caller_owned
        self._private = private
        self.fail = fail
        self.log = NullLog()
        self.events: List[str] = []

    engine = SimpleNamespace(connect=lambda: None)

    def _migration_lease_is_private(self) -> bool:
        return self._private

    def _ensure_migration_lock_table_for_external_connection(self, schema: str) -> None:
        self.events.append("ensure")
        if self.fail is not None:
            raise self.fail

    def _acquire_migration_lease(self, schema, session, wait_timeout_seconds, heartbeat=True):
        self.events.append("lease")
        return True


def test_prepared_lock_table_is_not_ensured_again_by_the_acquire() -> None:
    provider = _LeaseProvider(caller_owned=True)

    provider.prepare_migration_lock("S")
    provider.acquire_migration_lock("S")

    assert provider.events == ["ensure", "lease"]


def test_preparation_serves_one_acquire_only() -> None:
    provider = _LeaseProvider(caller_owned=True)

    provider.prepare_migration_lock("S")
    provider.acquire_migration_lock("S")
    provider._migration_lease = None
    provider.acquire_migration_lock("S")

    assert provider.events == ["ensure", "lease", "ensure", "lease"]


def test_acquire_without_preparation_ensures_the_lock_table() -> None:
    provider = _LeaseProvider(caller_owned=True)

    provider.acquire_migration_lock("S")

    assert provider.events == ["ensure", "lease"]


@pytest.mark.parametrize("caller_owned, private", [(False, False), (True, True)])
def test_preparation_does_nothing_without_a_second_connection(caller_owned, private) -> None:
    provider = _LeaseProvider(caller_owned=caller_owned, private=private)

    provider.prepare_migration_lock("S")

    assert provider.events == []


def _client(tmp_path, with_migration: bool = True) -> DBLiftClient:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    if with_migration:
        (migrations / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path / 'a.sqlite'}")
    return DBLiftClient.from_sqlalchemy(connection=engine.connect(), migrations_dir=migrations)


def _record_preparation_and_history(client: DBLiftClient) -> List[str]:
    events: List[str] = []
    history = client.executor.history_manager
    real = history.create_schema_and_history_table

    def create(*args, **kwargs):
        events.append("history")
        return real(*args, **kwargs)

    client.provider.prepare_migration_lock = lambda schema: events.append("prepare")
    return events, patch.object(history, "create_schema_and_history_table", create)


def test_migrate_prepares_the_lock_table_before_the_history_table(tmp_path) -> None:
    client = _client(tmp_path)
    events, patched = _record_preparation_and_history(client)
    try:
        with patched:
            assert client.migrate().success
    finally:
        client.close()

    assert events == ["prepare", "history"]


def test_dry_run_prepares_nothing(tmp_path) -> None:
    client = _client(tmp_path)
    events, patched = _record_preparation_and_history(client)
    try:
        with patched:
            client.migrate(dry_run=True)
    finally:
        client.close()

    assert events == []


def test_validate_prepares_nothing(tmp_path) -> None:
    client = _client(tmp_path, with_migration=False)
    events, patched = _record_preparation_and_history(client)
    try:
        with patched:
            client.validate()
    finally:
        client.close()

    assert "prepare" not in events


@pytest.mark.parametrize(
    "error", [RuntimeError("one connection"), OperationalError("s", {}, Exception())]
)
def test_a_failed_preparation_is_left_to_the_acquire(error) -> None:
    provider = _LeaseProvider(caller_owned=True, fail=error)

    provider.prepare_migration_lock("S")
    provider.fail = None
    provider.acquire_migration_lock("S")

    assert provider.events == ["ensure", "ensure", "lease"]
