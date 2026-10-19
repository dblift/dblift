"""A script missing from the migrations directory is one rule, decided by the state manager.

Strict ``validate`` and ``repair`` both read the state layer's answer, so the scripts
``validate`` reports as missing are exactly the scripts ``repair`` marks as deleted.
Each test drives real SQLite clients.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, Dict, List, Set

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

    def history(self, sql: str, params: tuple = ()) -> None:
        with sqlite3.connect(self.db) as conn:
            assert conn.execute(sql, params).rowcount == 1

    def strict_validate_missing(self) -> Set[str]:
        return {m.script for m in self.client(strict=True).validate().failed_migrations}

    def repair_missing(self) -> Set[str]:
        return {m.script for m in self.client().repair(dry_run=True).repaired_migrations}


@pytest.fixture
def env(tmp_path: Path):
    environment = Env(tmp_path)
    environment.write("V1__a.sql", "CREATE TABLE a (id INTEGER);")
    environment.write("V2__b.sql", "CREATE TABLE b (id INTEGER);")
    yield environment
    for client in environment.clients:
        client.close()


def test_strict_accepts_repair_deleted_script(env: Env) -> None:
    assert env.client().migrate().success
    (env.migrations / "V1__a.sql").unlink()

    before = env.client(strict=True).validate()
    assert not before.success
    assert before.error_message == (
        "Strict mode validation failed. Found 1 applied migration(s) without corresponding "
        "script files: V1__a.sql (version: 1). ."
    )

    assert env.client().repair().success

    assert env.client().validate().success
    strict = env.client(strict=True).validate()
    assert strict.success, strict.error_message
    assert env.client(strict=True).migrate().success


def _delete_v2(env: Env) -> Set[str]:
    (env.migrations / "V2__b.sql").unlink()
    return {"V2__b.sql"}


def _qualified_row_and_delete_v2(env: Env) -> Set[str]:
    env.history(
        "UPDATE dblift_schema_history SET script = ? WHERE script = ?",
        ("extra/V1__a.sql", "V1__a.sql"),
    )
    return _delete_v2(env)


def _undone_then_deleted(env: Env) -> Set[str]:
    env.write("U2__b.sql", "DROP TABLE b;")
    assert env.client().undo().success
    (env.migrations / "U2__b.sql").unlink()
    return _delete_v2(env)


def _reapplied_then_deleted(env: Env) -> Set[str]:
    env.write("U2__b.sql", "DROP TABLE b;")
    assert env.client().undo().success
    assert env.client().migrate().success
    (env.migrations / "U2__b.sql").unlink()
    return _delete_v2(env)


_SCENARIOS: Dict[str, Callable[[Env], Set[str]]] = {
    "missing": _delete_v2,
    "qualified_row_matches_by_file_name": _qualified_row_and_delete_v2,
    "undone_then_deleted": _undone_then_deleted,
    "reapplied_then_deleted": _reapplied_then_deleted,
}


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_missing_script_rule_shared(env: Env, scenario: str) -> None:
    assert env.client().migrate().success
    expected = _SCENARIOS[scenario](env)

    assert env.strict_validate_missing() == expected
    assert env.repair_missing() == expected

    assert env.client().repair().success
    assert env.repair_missing() == set()
    strict = env.client(strict=True).validate()
    assert strict.success, strict.error_message


def test_strict_lists_a_reapplied_missing_script_once(env: Env) -> None:
    assert env.client().migrate().success
    _reapplied_then_deleted(env)

    result = env.client(strict=True).validate()

    assert result.error_message == (
        "Strict mode validation failed. Found 1 applied migration(s) without corresponding "
        "script files: V2__b.sql (version: 2). ."
    )
