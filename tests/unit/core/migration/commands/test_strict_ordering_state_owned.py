"""Strict-mode ordering is one rule, decided by the state manager and read by ``migrate`` and ``validate``.

Each test drives real SQLite clients. Order is measured against the schema's
current version, so a migration that was undone no longer counts as applied.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Tuple

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


class Env:
    """A SQLite database and its migrations directory, shared by several clients."""

    def __init__(self, tmp_path: Path) -> None:
        self.db = tmp_path / "db.sqlite"
        self.migrations = tmp_path / "migrations"
        self.migrations.mkdir()
        self.clients: List[DBLiftClient] = []

    def write(self, name: str, sql: str) -> None:
        (self.migrations / name).write_text(sql)

    def client(self, strict: bool = False) -> DBLiftClient:
        client = DBLiftClient.from_sqlalchemy(
            create_engine(f"sqlite:///{self.db}"), migrations_dir=str(self.migrations)
        )
        client.config.strict_mode = strict
        self.clients.append(client)
        return client

    def successes(self) -> List[Tuple[str, str]]:
        with sqlite3.connect(self.db) as conn:
            return [
                (str(script), str(type_))
                for script, type_ in conn.execute(
                    "SELECT script, type FROM dblift_schema_history WHERE success = 1 "
                    "ORDER BY installed_rank"
                )
            ]


@pytest.fixture
def env(tmp_path: Path):
    environment = Env(tmp_path)
    yield environment
    for client in environment.clients:
        client.close()


def _applied_v1_v3(env: Env, with_undo: bool) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER);")
    env.write("V3__c.sql", "CREATE TABLE c (id INTEGER);")
    if with_undo:
        env.write("U3__c.sql", "DROP TABLE c;")
    assert env.client().migrate().success


def _executed(result) -> List[str]:
    return [m.script for m in result.migrations]


def test_strict_after_undo_accepts_lower_pending(env: Env) -> None:
    _applied_v1_v3(env, with_undo=True)
    assert env.client().undo().success
    env.write("V2__b.sql", "CREATE TABLE b (id INTEGER);")

    validated = env.client(strict=True).validate()
    migrated = env.client(strict=True).migrate()

    assert validated.success, validated.error_message
    assert migrated.success, migrated.error_message
    assert _executed(migrated) == ["V2__b.sql", "V3__c.sql"]


def test_strict_refuses_true_out_of_order(env: Env) -> None:
    _applied_v1_v3(env, with_undo=False)
    env.write("V2__b.sql", "CREATE TABLE b (id INTEGER);")

    validated = env.client(strict=True).validate()
    migrated = env.client(strict=True).migrate()

    assert not validated.success
    assert validated.error_message == (
        "Strict mode validation failed. Found 1 pending migration(s) with version(s) lower "
        "than the highest applied version (3): V2__b.sql (version: 2). ."
    )
    assert not migrated.success
    assert "Strict mode: out-of-order migration V2__b.sql" in (migrated.error_message or "")
    assert env.successes() == [("V1__a.sql", "SQL"), ("V3__c.sql", "SQL")]


def test_non_strict_out_of_order_warns_and_applies(env: Env) -> None:
    _applied_v1_v3(env, with_undo=False)
    env.write("V2__b.sql", "CREATE TABLE b (id INTEGER);")
    client = env.client()
    warnings: List[str] = []
    logger = client.executor.state_manager.logger
    real = logger.warning

    def warning(message, *args, **kwargs):
        warnings.append(str(message))
        return real(message, *args, **kwargs)

    logger.warning = warning

    result = client.migrate()

    assert result.success, result.error_message
    assert _executed(result) == ["V2__b.sql"]
    assert (
        "Out-of-order migration V2__b.sql (version 2 <= current version 3). "
        "Applying anyway; use --strict to enforce strict ordering."
    ) in warnings
    assert ("V2__b.sql", "SQL") in env.successes()


def test_equal_version_pending_rejected_by_duplicate_check(env: Env) -> None:
    _applied_v1_v3(env, with_undo=False)
    env.write("V3__other.sql", "CREATE TABLE other (id INTEGER);")

    migrated = env.client(strict=True).migrate()
    validated = env.client(strict=True).validate()

    for result in (migrated, validated):
        assert not result.success
        assert "is used by both" in (result.error_message or "")
        assert "out-of-order" not in (result.error_message or "")
        assert "lower than the highest applied version" not in (result.error_message or "")
    assert env.successes() == [("V1__a.sql", "SQL"), ("V3__c.sql", "SQL")]
