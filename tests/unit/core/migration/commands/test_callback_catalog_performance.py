"""Regression tests for command-scoped callback discovery."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.logger import NullLog
from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


@contextmanager
def _client(database: Path, migrations: Path) -> Iterator[DBLiftClient]:
    engine = create_engine(f"sqlite:///{database}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    try:
        yield client
    finally:
        client.close()
        engine.dispose()


def _run_migration_batch(tmp_path: Path, migration_count: int) -> int:
    migrations = tmp_path / "migrations"
    migrations.mkdir(parents=True)
    for index in range(1, migration_count + 1):
        (migrations / f"V{index}__create_table_{index}.sql").write_text(
            f"CREATE TABLE table_{index} (id INTEGER PRIMARY KEY);"
        )

    with _client(tmp_path / "app.db", migrations) as client:
        manager = client.executor.script_manager
        with patch.object(
            manager, "load_migration_scripts", wraps=manager.load_migration_scripts
        ) as loads:
            result = client.migrate()

        assert result.success, result.error_message
        assert len(result.migrations) == migration_count
        load_count = loads.call_count
    with sqlite3.connect(tmp_path / "app.db") as connection:
        table_names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {f"table_{index}" for index in range(1, migration_count + 1)} <= table_names
    return load_count


def test_callback_catalog_load_count_is_independent_of_migration_count(tmp_path: Path) -> None:
    small_loads = _run_migration_batch(tmp_path / "small", 3)
    large_loads = _run_migration_batch(tmp_path / "large", 12)

    assert small_loads == large_loads
    assert small_loads <= 3


def test_each_callbacks_execute_for_every_successful_migration(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "beforeMigrate__setup.sql").write_text("CREATE TABLE callback_log (phase TEXT);")
    (migrations / "beforeEach__record.sql").write_text(
        "INSERT INTO callback_log (phase) VALUES ('before');"
    )
    (migrations / "afterEach__record.sql").write_text(
        "INSERT INTO callback_log (phase) VALUES ('after');"
    )
    for index in range(1, 4):
        (migrations / f"V{index}__create_table_{index}.sql").write_text(
            f"CREATE TABLE table_{index} (id INTEGER PRIMARY KEY);"
        )

    with _client(tmp_path / "app.db", migrations) as client:
        result = client.migrate()

        assert result.success, result.error_message
        assert [callback.phase for callback in result.callbacks].count("beforeEach") == 3
        assert [callback.phase for callback in result.callbacks].count("afterEach") == 3
    with sqlite3.connect(tmp_path / "app.db") as connection:
        phases = [row[0] for row in connection.execute("SELECT phase FROM callback_log")]
    assert phases == ["before", "after", "before", "after", "before", "after"]


def test_each_callbacks_preserve_failure_behavior(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "beforeEach__record.sql").write_text("SELECT 1;")
    (migrations / "afterEach__record.sql").write_text("SELECT 1;")
    (migrations / "V1__ok.sql").write_text("CREATE TABLE ok (id INTEGER PRIMARY KEY);")
    (migrations / "V2__fails.sql").write_text("THIS IS NOT SQL;")

    with _client(tmp_path / "app.db", migrations) as client:
        result = client.migrate()

        assert result.success is False
        phases = [callback.phase for callback in result.callbacks]
        assert phases.count("beforeEach") == 2
        assert phases.count("afterEach") == 1


def test_next_client_call_refreshes_changed_callbacks_and_placeholders(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "beforeMigrate__setup.sql").write_text(
        "CREATE TABLE IF NOT EXISTS callback_log (value TEXT);"
    )
    before_each = migrations / "beforeEach__record.sql"
    before_each.write_text("INSERT INTO callback_log (value) VALUES ('${marker}-original');")
    (migrations / "V1__first.sql").write_text("CREATE TABLE first (id INTEGER PRIMARY KEY);")

    with _client(tmp_path / "app.db", migrations) as client:
        first = client.migrate(placeholders={"marker": "first"})
        assert first.success, first.error_message

        before_each.write_text("INSERT INTO callback_log (value) VALUES ('${marker}-changed');")
        (migrations / "afterEach__added.sql").write_text(
            "INSERT INTO callback_log (value) VALUES ('${marker}-added');"
        )
        (migrations / "V2__second.sql").write_text("CREATE TABLE second (id INTEGER PRIMARY KEY);")

        second = client.migrate(placeholders={"marker": "second"})

        assert second.success, second.error_message
    with sqlite3.connect(tmp_path / "app.db") as connection:
        values = [row[0] for row in connection.execute("SELECT value FROM callback_log")]
    assert values == ["first-original", "second-changed", "second-added"]


def test_reused_command_refreshes_callbacks_after_failure(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    callback = migrations / "beforeEach__gate.sql"
    callback.write_text("SELECT * FROM missing_callback_table;")
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")

    with _client(tmp_path / "app.db", migrations) as client:
        command = MigrateCommand(client.executor._make_command_context())
        first = command.execute(scripts_dir=migrations)
        assert first.success is False

        callback.write_text("CREATE TABLE callback_recovered (id INTEGER PRIMARY KEY);")
        second = command.execute(scripts_dir=migrations)

        assert second.success, second.error_message
    with sqlite3.connect(tmp_path / "app.db") as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"app", "callback_recovered"} <= tables


def test_callback_catalog_respects_directory_recursive_settings(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary_nested = primary / "nested"
    additional = tmp_path / "additional"
    additional_nested = additional / "nested"
    primary_nested.mkdir(parents=True)
    additional_nested.mkdir(parents=True)

    (primary / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    (primary_nested / "beforeMigrate__primary_nested.sql").write_text(
        "CREATE TABLE primary_nested (id INTEGER PRIMARY KEY);"
    )
    (additional / "beforeMigrate__additional.sql").write_text(
        "CREATE TABLE additional_root (id INTEGER PRIMARY KEY);"
    )
    (additional_nested / "beforeMigrate__excluded.sql").write_text(
        "CREATE TABLE additional_nested (id INTEGER PRIMARY KEY);"
    )

    with _client(tmp_path / "app.db", primary) as client:
        result = client.migrate(
            recursive=True,
            additional_dirs=[additional],
            dir_recursive_map={primary: True, additional: False},
        )

        assert result.success, result.error_message
    with sqlite3.connect(tmp_path / "app.db") as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"app", "primary_nested", "additional_root"} <= tables
    assert "additional_nested" not in tables


def test_direct_callback_lookup_keeps_fresh_discovery(tmp_path: Path) -> None:
    first = tmp_path / "beforeMigrate__first.sql"
    first.write_text("SELECT 1;")
    manager = MigrationScriptManager(logger=NullLog())

    initial = manager.get_callbacks_by_event(tmp_path, "beforeMigrate", recursive=False)
    (tmp_path / "beforeMigrate__second.sql").write_text("SELECT 2;")
    refreshed = manager.get_callbacks_by_event(tmp_path, "beforeMigrate", recursive=False)

    assert [callback.script_name for callback in initial] == [first.name]
    assert [callback.script_name for callback in refreshed] == [
        "beforeMigrate__first.sql",
        "beforeMigrate__second.sql",
    ]
