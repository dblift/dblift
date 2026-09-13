"""Real SQLite command benchmarks with isolated database state per round."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.logger.results import InfoResult, MigrateResult, ValidateResult

ROUNDS = 3
MIGRATION_COUNT = 100


@dataclass
class _SQLiteRound:
    database: Path
    client: DBLiftClient
    result: object | None = None


@contextmanager
def _sqlite_round(database: Path, migrations: Path) -> Iterator[_SQLiteRound]:
    """Open one benchmark client and always release its external engine."""
    with closing(sqlite3.connect(database)):
        pass
    engine = create_engine(f"sqlite:///{database}")
    client = None
    try:
        client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
        yield _SQLiteRound(database=database, client=client)
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            engine.dispose()


def _remove_database(database: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(f"{database}{suffix}").unlink(missing_ok=True)


def _write_migrations(directory: Path, migration_count: int, with_callbacks: bool) -> None:
    directory.mkdir()
    for index in range(1, migration_count + 1):
        (directory / f"V{index}__create_benchmark_table_{index}.sql").write_text(
            f"CREATE TABLE benchmark_table_{index} (id INTEGER PRIMARY KEY);\n",
            encoding="utf-8",
        )

    if with_callbacks:
        (directory / "beforeMigrate__create_callback_log.sql").write_text(
            "CREATE TABLE callback_log (phase TEXT NOT NULL);\n",
            encoding="utf-8",
        )
        (directory / "beforeEach__record_callback.sql").write_text(
            "INSERT INTO callback_log (phase) VALUES ('before');\n",
            encoding="utf-8",
        )
        (directory / "afterEach__record_callback.sql").write_text(
            "INSERT INTO callback_log (phase) VALUES ('after');\n",
            encoding="utf-8",
        )


def _database_counts(database: Path) -> tuple[int, int]:
    with closing(sqlite3.connect(database)) as connection:
        table_count = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name GLOB 'benchmark_table_*'"
        ).fetchone()[0]
        history_count = connection.execute(
            "SELECT COUNT(*) FROM dblift_schema_history WHERE success = 1"
        ).fetchone()[0]
    return table_count, history_count


def _callback_row_count(database: Path) -> int:
    with closing(sqlite3.connect(database)) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM callback_log").fetchone()[0])


def _assert_fresh_migrate(state: _SQLiteRound, migration_count: int, with_callbacks: bool) -> None:
    result = state.result
    assert isinstance(result, MigrateResult)
    assert result.success, result.error_message
    assert result.migrations_applied == [str(index) for index in range(1, migration_count + 1)]
    assert result.current_schema_version == str(migration_count)
    assert _database_counts(state.database) == (migration_count, migration_count)

    if with_callbacks:
        phases = [callback.phase for callback in result.callbacks]
        assert phases.count("beforeMigrate") == 1
        assert phases.count("beforeEach") == migration_count
        assert phases.count("afterEach") == migration_count
        assert _callback_row_count(state.database) == migration_count * 2
    else:
        assert result.callbacks == []


@pytest.fixture
def populated_sqlite_workload(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    migrations = tmp_path / "migrations"
    template = tmp_path / "populated-template.db"
    _write_migrations(migrations, MIGRATION_COUNT, with_callbacks=False)

    try:
        with _sqlite_round(template, migrations) as state:
            state.result = state.client.migrate()
            _assert_fresh_migrate(state, MIGRATION_COUNT, with_callbacks=False)
        yield migrations, template
    finally:
        _remove_database(template)


@pytest.mark.parametrize(
    "migration_count,with_callbacks",
    [(10, False), (10, True), (100, False), (100, True)],
    ids=[
        "10-without-callbacks",
        "10-with-callbacks",
        "100-without-callbacks",
        "100-with-callbacks",
    ],
)
def test_fresh_migrate(
    benchmark, tmp_path: Path, migration_count: int, with_callbacks: bool
) -> None:
    migrations = tmp_path / "migrations"
    _write_migrations(migrations, migration_count, with_callbacks)
    states: list[_SQLiteRound] = []

    with ExitStack() as stack:

        def setup():
            database = tmp_path / f"fresh-round-{len(states) + 1}.db"
            _remove_database(database)
            stack.callback(_remove_database, database)
            state = stack.enter_context(_sqlite_round(database, migrations))
            states.append(state)
            return (state,), {}

        def migrate(state: _SQLiteRound) -> MigrateResult:
            result = state.client.migrate()
            state.result = result
            return result

        benchmark.pedantic(
            migrate,
            setup=setup,
            rounds=ROUNDS,
            warmup_rounds=0,
            iterations=1,
        )

        assert len(states) == ROUNDS
        for state in states:
            _assert_fresh_migrate(state, migration_count, with_callbacks)


@pytest.mark.parametrize("operation", ["noop-migrate", "validate", "info"])
def test_populated_command(
    benchmark,
    tmp_path: Path,
    populated_sqlite_workload: tuple[Path, Path],
    operation: str,
) -> None:
    migrations, template = populated_sqlite_workload
    states: list[_SQLiteRound] = []

    with ExitStack() as stack:

        def setup():
            database = tmp_path / f"{operation}-round-{len(states) + 1}.db"
            _remove_database(database)
            stack.callback(_remove_database, database)
            shutil.copyfile(template, database)
            state = stack.enter_context(_sqlite_round(database, migrations))
            states.append(state)
            return (state,), {}

        def run_command(state: _SQLiteRound) -> object:
            result: MigrateResult | ValidateResult | InfoResult
            if operation == "noop-migrate":
                result = state.client.migrate()
            elif operation == "validate":
                result = state.client.validate()
            else:
                result = state.client.info()
            state.result = result
            return result

        benchmark.pedantic(
            run_command,
            setup=setup,
            rounds=ROUNDS,
            warmup_rounds=0,
            iterations=1,
        )

        assert len(states) == ROUNDS
        for state in states:
            result = state.result
            if operation == "noop-migrate":
                assert isinstance(result, MigrateResult)
                assert result.success, result.error_message
                assert result.migrations_applied == []
                assert result.current_schema_version == str(MIGRATION_COUNT)
            elif operation == "validate":
                assert isinstance(result, ValidateResult)
                assert result.success, result.error_message
                assert result.error_count == 0
                assert result.failed_migrations == []
                assert len(result.validated_migrations) == MIGRATION_COUNT
                assert all(
                    migration.status == "SUCCESS" for migration in result.validated_migrations
                )
            else:
                assert isinstance(result, InfoResult)
                assert result.success, result.error_message
                assert result.current_schema_version == str(MIGRATION_COUNT)
                assert len(result.applied_migrations) == MIGRATION_COUNT
                assert result.pending_count == 0
                assert result.failed_count == 0
            assert _database_counts(state.database) == (MIGRATION_COUNT, MIGRATION_COUNT)
            assert state.database.read_bytes() == template.read_bytes()
