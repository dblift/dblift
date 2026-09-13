"""Repair reuses one full pre-write catalog without hiding later file changes."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.migration.commands.repair_command import RepairCommand, RepairSafetyError
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.state.migration_state_manager import MigrationStateManager

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


@pytest.fixture
def database_client(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    database = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{database}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    try:
        yield client, migrations, database
    finally:
        client.close()
        engine.dispose()


def _history(database):
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT script, checksum, success, type, description "
            "FROM dblift_schema_history ORDER BY installed_rank"
        ).fetchall()


@pytest.mark.parametrize("extension", ["sql", "py"])
@pytest.mark.parametrize("drift", [False, True])
def test_noop_and_preview_load_catalog_once(database_client, extension, drift):
    client, migrations, database = database_client
    script = migrations / f"V1__app.{extension}"
    body = (
        "CREATE TABLE app (id INTEGER PRIMARY KEY);\n"
        if extension == "sql"
        else 'def migrate(context):\n    context.execute("CREATE TABLE app (id INTEGER PRIMARY KEY)")\n'
    )
    script.write_text(body)
    assert client.migrate().success
    if drift:
        script.write_text(body + ("-- edited\n" if extension == "sql" else "# edited\n"))
    before = database.read_bytes()
    before_history = _history(database)
    script_manager = client.executor.script_manager
    with patch.object(
        script_manager, "load_migration_scripts", wraps=script_manager.load_migration_scripts
    ) as load:
        result = client.repair(dry_run=drift)
    assert result.success
    assert result.checksums_fixed == result.failed_migrations_removed == 0
    assert result.deleted_migrations_marked == 0
    assert _history(database) == before_history
    assert database.read_bytes() == before
    assert load.call_count == 1
    assert client.validate().success is (not drift)


def test_post_write_and_next_command_read_fresh_catalog(database_client):
    client, migrations, database = database_client
    script = migrations / "V1__app.sql"
    body = "CREATE TABLE app (id INTEGER PRIMARY KEY);\n"
    script.write_text(body)
    assert client.migrate().success
    original_checksum = _history(database)[0][1]
    script.write_text(body + "-- edit before repair\n")
    manager = client.executor.state_manager
    history = client.executor.history_manager
    script_manager = client.executor.script_manager
    repair_checksum = history.repair_checksum
    states = []
    build_state = manager.build_state

    def capture_state(*args, **kwargs):
        state = build_state(*args, **kwargs)
        states.append(state)
        return state

    def edit_after_write(*args, **kwargs):
        repaired = repair_checksum(*args, **kwargs)
        script.write_text(body + "-- edit after history write\n")
        return repaired

    with (
        patch.object(history, "repair_checksum", side_effect=edit_after_write),
        patch.object(manager, "build_state", side_effect=capture_state),
        patch.object(
            script_manager, "load_migration_scripts", wraps=script_manager.load_migration_scripts
        ) as load,
    ):
        result = client.repair()
    assert result.success and result.checksums_fixed == 1
    assert _history(database)[0][1] != original_checksum
    assert len(states) == 2
    assert states[0].resolved_objects[0].checksum != states[1].resolved_objects[0].checksum
    assert load.call_count == 2
    assert client.validate().success is False
    with patch.object(
        script_manager, "load_migration_scripts", wraps=script_manager.load_migration_scripts
    ) as load:
        result = client.repair()
    assert result.success and result.checksums_fixed == 1
    assert load.call_count == 2
    assert client.validate().success


def test_recursion_map_and_additional_directories_use_same_catalog(database_client, tmp_path):
    client, migrations, database = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER);")
    hidden = migrations / "nested"
    hidden.mkdir()
    (hidden / "V9__excluded.sql").write_text("invalid SQL should not be loaded;")
    extra = tmp_path / "extra"
    (extra / "nested").mkdir(parents=True)
    extra_script = extra / "nested" / "V2__extra.sql"
    extra_script.write_text("CREATE TABLE extra (id INTEGER);")
    options = dict(recursive=False, additional_dirs=[extra], dir_recursive_map={extra: True})
    assert client.migrate(**options).success
    before = database.read_bytes()
    script_manager = client.executor.script_manager
    with patch.object(
        script_manager, "load_migration_scripts", wraps=script_manager.load_migration_scripts
    ) as load:
        result = client.repair(**options)
    assert result.success and result.deleted_migrations_marked == 0
    assert database.read_bytes() == before
    assert load.call_count == 1
    assert {row[0] for row in _history(database)} == {"V1__app.sql", "V2__extra.sql"}


def _command(script_manager):
    command = RepairCommand.__new__(RepairCommand)
    command.log = MagicMock()
    history = MagicMock()
    history.get_applied_migrations.return_value = []
    command.state_manager = MigrationStateManager(command.log, history, script_manager, MagicMock())
    return command


def test_built_catalog_preserves_group_order_and_last_duplicate_wins(tmp_path):
    first = Migration(script_name="V1__same.sql", content="SELECT 1;", type=MigrationType.SQL)
    last = Migration(script_name="V1__same.sql", content="SELECT 2;", type=MigrationType.SQL)
    catalog = {MigrationType.REPEATABLE: [first], MigrationType.SQL: [last]}
    scripts = MagicMock()
    scripts.load_migration_scripts.return_value = catalog
    command = _command(scripts)
    state = command.state_manager.build_state(tmp_path)
    state.all_applied_objects = [
        SimpleNamespace(script_name=first.script_name, type=MigrationType.SQL, checksum=0)
    ]
    repairs = command._detect_checksum_drift(state, [], tmp_path)
    assert repairs[0]["new_checksum"] == last.checksum
    assert list(state.grouped_objects) == list(catalog)
    assert scripts.load_migration_scripts.call_count == 1


@pytest.mark.parametrize("has_history", [False, True])
def test_empty_built_catalog_is_authoritative(tmp_path, has_history):
    scripts = MagicMock()
    scripts.load_migration_scripts.return_value = {}
    command = _command(scripts)
    state = command.state_manager.build_state(tmp_path)
    if has_history:
        state.applied_objects = [
            SimpleNamespace(script_name="V1__gone.sql", type=MigrationType.SQL)
        ]
    scripts.load_migration_scripts.side_effect = AssertionError("must reuse empty catalog")
    if has_history:
        with pytest.raises(RepairSafetyError):
            command._detect_missing_migrations(state, tmp_path)
    else:
        assert command._detect_missing_migrations(state, tmp_path) == []
    assert command._detect_checksum_drift(state, [], tmp_path) == []
    assert scripts.load_migration_scripts.call_count == 1


def test_missing_catalog_fallback_preserves_errors_and_freshness(tmp_path):
    scripts = MagicMock()
    scripts.load_migration_scripts.side_effect = PermissionError("unreadable catalog")
    command = _command(scripts)
    state = command._build_migration_state(tmp_path)
    with pytest.raises(PermissionError, match="unreadable catalog"):
        command._detect_missing_migrations(state, tmp_path)
    assert command._detect_checksum_drift(state, [], tmp_path) == []
    command.log.warning.assert_called_once_with(
        "Unable to load filesystem migrations during repair: unreadable catalog"
    )
    scripts.load_migration_scripts.side_effect = None
    scripts.load_migration_scripts.return_value = {}
    assert command.state_manager.get_grouped_migrations(tmp_path) == {}
    scripts.load_migration_scripts.return_value = {MigrationType.SQL: ["new catalog"]}
    assert command.state_manager.get_grouped_migrations(tmp_path) == {
        MigrationType.SQL: ["new catalog"]
    }


def test_missing_delete_and_baseline_markers_survive_reuse(database_client):
    client, migrations, database = database_client
    assert client.baseline(version="0").success
    missing = migrations / "V1__gone.sql"
    missing.write_text("CREATE TABLE gone (id INTEGER);")
    (migrations / "V2__kept.sql").write_text("CREATE TABLE kept (id INTEGER);")
    assert client.migrate().success
    missing.unlink()
    scripts = client.executor.script_manager
    with patch.object(
        scripts, "load_migration_scripts", wraps=scripts.load_migration_scripts
    ) as load:
        result = client.repair()
    assert result.success and result.deleted_migrations_marked == 1
    assert load.call_count == 2
    rows = _history(database)
    assert [row[3] for row in rows].count("BASELINE") == 1
    deleted = [row for row in rows if row[3] == "DELETE"]
    assert len(deleted) == 1 and deleted[0][0] == missing.name
    assert "[DELETE:SQL]" in deleted[0][4]
    with patch.object(
        scripts, "load_migration_scripts", wraps=scripts.load_migration_scripts
    ) as load:
        result = client.repair()
    assert result.success and result.deleted_migrations_marked == 0
    assert _history(database) == rows
    assert load.call_count == 1


def test_failed_row_is_removed_with_reused_catalog(database_client):
    client, migrations, database = database_client
    script = migrations / "V1__app.sql"
    script.write_text("CREATE TABLE app (id INTEGER);")
    assert client.migrate().success
    # A persisted failed row is the repair input; avoid transaction rollback
    # differences between engines when constructing it.
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE dblift_schema_history SET success = 0")
    script.write_text("CREATE TABLE app (id INTEGER);\n-- corrected\n")
    scripts = client.executor.script_manager
    with patch.object(
        scripts, "load_migration_scripts", wraps=scripts.load_migration_scripts
    ) as load:
        result = client.repair()
    assert result.success and result.failed_migrations_removed == 1
    assert result.checksums_fixed == 0
    assert _history(database) == []
    assert load.call_count == 2
