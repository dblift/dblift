"""``migrate`` plans what to run after it takes the migration lock.

The plan is first built before the lock so the cheap refusals (strict order,
SQL preflight, validation, dry run) stay cheap. Once the lock is held, the plan
is rebuilt from a fresh read of the history with the same state computation the
other commands use, so whatever another process applied while this one waited
is neither re-run nor mistaken for pending.

Each test runs two real SQLite clients. Client A's ``acquire_migration_lock`` is
wrapped so that client B acts first, then A takes the real lock: a genuine
interleaving, with B taking and releasing the real lock itself.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.migration.commands.base_command import MIGRATION_LOCK_REFUSAL
from dblift.core.migration.commands.migrate_command import MigrateCommand

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]

ALL_APPLIED = "All pending migrations were applied by another process while waiting for the lock"


class Env:
    """A SQLite database and its migrations directory, shared by several clients."""

    def __init__(self, tmp_path: Path) -> None:
        self.db = tmp_path / "db.sqlite"
        self.migrations = tmp_path / "migrations"
        self.migrations.mkdir()
        self.tmp_path = tmp_path
        self.clients: List[DBLiftClient] = []

    def write(self, name: str, sql: str) -> Path:
        path = self.migrations / name
        path.write_text(sql)
        return path

    def client(self, db: Optional[Path] = None, **options) -> DBLiftClient:
        client = DBLiftClient.from_sqlalchemy(
            create_engine(f"sqlite:///{db or self.db}"),
            migrations_dir=str(self.migrations),
            **options,
        )
        self.clients.append(client)
        return client

    def rows(self, db: Optional[Path] = None) -> List[Tuple[str, str, int]]:
        with sqlite3.connect(db or self.db) as conn:
            return [
                (str(script), str(type_), int(success))
                for script, type_, success in conn.execute(
                    "SELECT script, type, success FROM dblift_schema_history "
                    "ORDER BY installed_rank"
                )
            ]

    def successes(self, script: str) -> int:
        return sum(1 for s, _t, ok in self.rows() if s == script and ok)

    def execute_sql(self, sql: str) -> None:
        with sqlite3.connect(self.db) as conn:
            conn.execute(sql)


@pytest.fixture
def env(tmp_path: Path):
    environment = Env(tmp_path)
    yield environment
    for client in environment.clients:
        client.close()


def during_lock_wait(client: DBLiftClient, action: Callable[[], None]) -> None:
    """Run ``action`` just before ``client`` takes the real migration lock."""
    real = client.provider.acquire_migration_lock

    def acquire(*args, **kwargs):
        client.provider.acquire_migration_lock = real
        action()
        return real(*args, **kwargs)

    client.provider.acquire_migration_lock = acquire


def capture_info(client: DBLiftClient) -> List[str]:
    """Collect the messages ``client`` logs at info level, still logging them."""
    messages: List[str] = []
    log = client.executor.log
    real = log.info

    def info(message, *args, **kwargs):
        messages.append(str(message))
        return real(message, *args, **kwargs)

    log.info = info
    return messages


def executed(result) -> List[str]:
    return [m.script for m in result.migrations]


def test_two_clients_apply_each_script_once(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    env.write("V2__b.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")
    env.write("R__view.sql", "CREATE VIEW IF NOT EXISTS a_view AS SELECT 1 AS one;")
    a, b = env.client(), env.client()
    messages = capture_info(a)
    during_lock_wait(a, lambda: b.migrate())

    result = a.migrate()

    assert result.success, result.error_message
    assert executed(result) == []
    assert env.successes("V1__a.sql") == env.successes("V2__b.sql") == 1
    assert env.successes("R__view.sql") == 1
    assert len(env.rows()) == 3
    assert ALL_APPLIED in messages
    assert "Skipping V1__a.sql (version: 1) — applied by concurrent process" in messages
    assert "Skipping V2__b.sql (version: 2) — applied by concurrent process" in messages
    assert "Skipping R__view.sql — applied by concurrent process" in messages
    assert (
        "3 pending migration(s) applied by another process while waiting for the lock; skipping"
        in messages
    )


def test_nothing_concurrent_runs_everything(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    env.write("R__view.sql", "CREATE VIEW IF NOT EXISTS a_view AS SELECT 1 AS one;")
    a = env.client()

    result = a.migrate()

    assert result.success, result.error_message
    assert executed(result) == ["V1__a.sql", "R__view.sql"]
    assert len(env.rows()) == 2


def test_subset_applied_concurrently_runs_the_rest(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    env.write("V2__b.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")
    a, b = env.client(), env.client()
    messages = capture_info(a)
    during_lock_wait(a, lambda: b.migrate(versions="1"))

    result = a.migrate()

    assert result.success, result.error_message
    assert executed(result) == ["V2__b.sql"]
    assert env.successes("V1__a.sql") == env.successes("V2__b.sql") == 1
    assert "Skipping V1__a.sql (version: 1) — applied by concurrent process" in messages
    assert (
        "1 pending migration(s) applied by another process while waiting for the lock; skipping"
        in messages
    )


def test_failed_concurrent_row_does_not_skip(env: Env) -> None:
    env.write("V1__a.sql", "INSERT INTO missing_table VALUES (1);")
    env.write("V2__b.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")
    copy = env.tmp_path / "after_b_failure.sqlite"
    a, b = env.client(), env.client()

    def b_fails_then_copy() -> None:
        assert b.migrate().success is False
        shutil.copy(env.db, copy)

    during_lock_wait(a, b_fails_then_copy)

    result_a = a.migrate()
    c = env.client(copy)
    # A validated before B failed; skip C's validation, which would refuse the
    # failed row, so C shows what the canonical plan runs for the same history.
    c.executor.validator = None
    result_c = c.migrate()

    assert (result_a.success, result_a.error_message, executed(result_a)) == (
        result_c.success,
        result_c.error_message,
        executed(result_c),
    )
    assert env.rows() == env.rows(copy)


def test_undone_version_runs_again(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    env.write("U1__a.sql", "DROP TABLE a;")
    assert env.client().migrate().success
    env.write("V2__b.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")
    a, b = env.client(), env.client()
    during_lock_wait(a, lambda: b.undo())

    result = a.migrate()

    assert result.success, result.error_message
    assert executed(result) == ["V1__a.sql", "V2__b.sql"]
    assert env.rows() == [
        ("V1__a.sql", "SQL", 1),
        ("U1__a.sql", "UNDO_SQL", 1),
        ("V1__a.sql", "SQL", 1),
        ("V2__b.sql", "SQL", 1),
    ]


def test_reapplied_after_undo_is_skipped(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    env.write("U1__a.sql", "DROP TABLE a;")
    seed = env.client()
    assert seed.migrate().success
    assert seed.undo().success
    a, b = env.client(), env.client()
    during_lock_wait(a, lambda: b.migrate())

    result = a.migrate()

    assert result.success, result.error_message
    assert executed(result) == []
    assert [r for r in env.rows() if r[0] == "V1__a.sql"] == [
        ("V1__a.sql", "SQL", 1),
        ("V1__a.sql", "SQL", 1),
    ]


def test_repeatable_same_checksum_skipped(env: Env) -> None:
    env.write("R__view.sql", "CREATE VIEW a_view AS SELECT 1 AS one;")
    a, b = env.client(), env.client()
    during_lock_wait(a, lambda: b.migrate())

    # A non-idempotent repeatable (no IF NOT EXISTS) would fail if A re-ran it.
    result = a.migrate()

    assert result.success, result.error_message
    assert executed(result) == []
    assert env.successes("R__view.sql") == 1


def test_repeatable_changed_checksum_runs(env: Env) -> None:
    script = env.write("R__view.sql", "CREATE VIEW IF NOT EXISTS a_view AS SELECT 1 AS one;")
    a, b = env.client(), env.client()

    def b_applies_then_script_changes() -> None:
        b.migrate()
        script.write_text("CREATE VIEW IF NOT EXISTS a_view AS SELECT 2 AS two;")

    during_lock_wait(a, b_applies_then_script_changes)

    result = a.migrate()

    assert result.success, result.error_message
    assert executed(result) == ["R__view.sql"]
    assert env.successes("R__view.sql") == 2


def test_repeatable_unknown_checksum_applied_concurrently_is_skipped(env: Env) -> None:
    env.write("R__view.sql", "CREATE VIEW a_view AS SELECT 1 AS one;")
    a, b = env.client(), env.client()

    def b_applies_then_checksum_unknown() -> None:
        assert b.migrate().success
        env.execute_sql("UPDATE dblift_schema_history SET checksum = NULL")

    during_lock_wait(a, b_applies_then_checksum_unknown)

    result = a.migrate()

    assert result.success, result.error_message
    assert executed(result) == []
    assert env.successes("R__view.sql") == 1


def test_plan_is_read_after_lock(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    a = env.client()
    order: List[str] = []
    real_build = a.executor.state_manager.build_state
    real_acquire = a.provider.acquire_migration_lock

    def build_state(*args, **kwargs):
        order.append("build_state")
        return real_build(*args, **kwargs)

    def acquire(*args, **kwargs):
        order.append("acquire")
        return real_acquire(*args, **kwargs)

    a.executor.state_manager.build_state = build_state
    a.provider.acquire_migration_lock = acquire

    assert a.migrate().success

    assert order[:3] == ["build_state", "acquire", "build_state"]


def test_dry_run_neither_locks_nor_replans(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    a = env.client()
    calls: List[str] = []
    real_build = a.executor.state_manager.build_state

    def build_state(*args, **kwargs):
        calls.append("build_state")
        return real_build(*args, **kwargs)

    def acquire(*args, **kwargs):
        calls.append("acquire")
        return True

    a.executor.state_manager.build_state = build_state
    a.provider.acquire_migration_lock = acquire

    result = a.migrate(dry_run=True)

    assert result.success, result.error_message
    assert calls == ["build_state"]


def test_strict_mode_rechecked_under_lock(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    assert env.client().migrate().success
    env.write("V2__b.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")
    env.write("V3__c.sql", "CREATE TABLE c (id INTEGER PRIMARY KEY);")
    a, b = env.client(), env.client()
    a.config.strict_mode = True
    # A non-strict client applies V3 alone while A waits: under the lock, V2 is
    # now below the current version, which the check before the lock could not see.
    during_lock_wait(a, lambda: b.migrate(versions="3"))

    with patch.object(MigrateCommand, "_fire", autospec=True) as fire:
        result = a.migrate()

    assert result.success is False
    assert (result.error_message or "").startswith(
        "Strict mode: out-of-order migration V2__b.sql (version 2 <= current version 3)."
    )
    assert executed(result) == []
    assert [r[0] for r in env.rows()] == ["V1__a.sql", "V3__c.sql"]
    assert "afterMigrateError" not in [call.args[1] for call in fire.call_args_list]
    other = env.client()
    assert other.provider.acquire_migration_lock(a.config.database.schema, wait_timeout_seconds=1)
    other.provider.release_migration_lock(a.config.database.schema)


def test_new_pending_after_lock_is_preflighted(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    env.write("U1__a.sql", "DROP TABLE a;")
    assert env.client().migrate().success
    env.write("V2__b.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")
    a, b = env.client(analysis_mode="execution"), env.client()
    during_lock_wait(a, lambda: b.undo())

    seen: List[List[str]] = []
    real = MigrateCommand._preflight_execution_sql

    def spy(self, migrations, *args, **kwargs):
        seen.append([m.script_name for m in migrations])
        return real(self, migrations, *args, **kwargs)

    with patch.object(MigrateCommand, "_preflight_execution_sql", spy):
        result = a.migrate()

    assert result.success, result.error_message
    assert seen[0] == ["V2__b.sql"]
    assert seen[1:] == [["V1__a.sql"]]


def test_mark_as_executed_takes_lock(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    a = env.client()
    events: List[str] = []
    real_acquire = a.provider.acquire_migration_lock
    real_release = a.provider.release_migration_lock
    real_record = a.executor.history_manager.record_migration

    def acquire(*args, **kwargs):
        events.append("acquire")
        return real_acquire(*args, **kwargs)

    def release(*args, **kwargs):
        events.append("release")
        return real_release(*args, **kwargs)

    def record(*args, **kwargs):
        events.append("record")
        return real_record(*args, **kwargs)

    a.provider.acquire_migration_lock = acquire
    a.provider.release_migration_lock = release
    a.executor.history_manager.record_migration = record

    result = a.migrate(mark_as_executed=True)

    assert result.success, result.error_message
    assert events == ["acquire", "record", "release"]
    assert env.rows() == [("V1__a.sql", "SQL", 1)]


def test_mark_as_executed_lock_refused(env: Env) -> None:
    env.write("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    a = env.client()
    released: List[str] = []
    a.provider.acquire_migration_lock = lambda *args, **kwargs: False
    a.provider.release_migration_lock = lambda *args, **kwargs: released.append("release")

    result = a.migrate(mark_as_executed=True)

    assert result.success is False
    assert result.error_message == MIGRATION_LOCK_REFUSAL
    assert env.rows() == []
    assert released == []
