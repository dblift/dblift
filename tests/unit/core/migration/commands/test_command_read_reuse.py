"""Command read phases reuse inputs without hiding later database or file changes."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.migration.commands.base_command import BaseCommand
from dblift.core.migration.commands.baseline_command import BaselineCommand
from dblift.core.migration.commands.info_command import InfoCommand
from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.migration.commands.repair_command import RepairCommand
from dblift.core.migration.commands.validate_command import ValidateCommand
from dblift.core.migration.state.migration_data_service import MigrationDataService
from dblift.core.migration.state.migration_state import MigrationState

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


@pytest.fixture
def database_client(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    database = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{database}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    try:
        yield client, engine, migrations, database
    finally:
        client.close()
        engine.dispose()


@contextmanager
def observe_reads(client, migrations):
    counts = {"history": 0, "files": Counter(), "scans": 0}
    read_text = Path.read_text
    get_all_scripts = client.executor.script_manager.get_all_scripts

    def count_query(statement):
        sql = " ".join(statement.lower().replace('"', "").split())
        if sql.startswith("select ") and " from dblift_schema_history" in sql:
            counts["history"] += 1

    def count_file(path, *args, **kwargs):
        if path.is_relative_to(migrations) and path.suffix in (".sql", ".py"):
            counts["files"][path.name] += 1
        return read_text(path, *args, **kwargs)

    def count_scan(*args, **kwargs):
        counts["scans"] += 1
        return get_all_scripts(*args, **kwargs)

    client.provider.connection.set_trace_callback(count_query)
    try:
        with (
            patch.object(Path, "read_text", count_file),
            patch.object(client.executor.script_manager, "get_all_scripts", count_scan),
        ):
            yield counts
    finally:
        client.provider.connection.set_trace_callback(None)


@pytest.mark.parametrize(
    "operation,populated,expected_history,expected_loads",
    [
        ("migrate", False, 4, 2),
        ("migrate", True, 2, 1),
        ("info", False, 2, 1),
        ("info", True, 2, 1),
        ("validate", True, 2, 2),
    ],
)
def test_commands_reuse_initial_reads(
    database_client, operation, populated, expected_history, expected_loads
):
    client, engine, migrations, database = database_client
    script = migrations / "V1__app.sql"
    script.write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    if populated:
        assert client.migrate().success

    headers = []
    original_header = BaseCommand._format_command_header

    def capture_header(command, *args, **kwargs):
        headers.append(kwargs["schema_version"])
        return original_header(command, *args, **kwargs)

    with (
        observe_reads(client, migrations) as counts,
        patch.object(BaseCommand, "_format_command_header", capture_header),
    ):
        result = getattr(client, operation)()

    assert result.success, result.error_message
    assert headers == (["1"] if populated else [None])
    if operation == "migrate":
        assert [row.script for row in result.migrations] == ([] if populated else [script.name])
        assert result.current_schema_version == "1"
    elif operation == "info":
        assert [(row.script, row.status) for row in result.migrations] == [
            (script.name, "SUCCESS" if populated else "PENDING")
        ]
    else:
        assert [row.script for row in result.validated_migrations] == [script.name]
    if populated or operation == "migrate":
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT count(*) FROM dblift_schema_history").fetchone() == (
                1,
            )
            assert connection.execute("SELECT count(*) FROM app").fetchone() == (0,)
    assert counts == {
        "history": expected_history,
        "files": {script.name: expected_loads},
        "scans": expected_loads,
    }


def test_empty_history_snapshot_is_used_by_state_and_strict_validation(database_client):
    client, engine, migrations, _ = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    client.executor.history_manager.create_schema_and_history_table(create_schema=False)
    snapshot = client.executor.state_manager.new_read_snapshot()
    assert snapshot.get_applied_migrations() == []
    assert client.migrate().success
    client.config.strict_mode = True

    with observe_reads(client, migrations) as counts:
        state = client.executor.state_manager.build_state(migrations, read_snapshot=snapshot)
        validation = client.executor.validator.validate_migrations(
            migrations, "validate", resolved_migrations=[], preloaded_records=[]
        )

    assert [entry.script for entry in state.pending] == ["V1__app.sql"]
    assert state.applied == []
    assert validation.success, validation.error_message
    assert counts == {"history": 0, "files": {"V1__app.sql": 1}, "scans": 1}


@pytest.mark.parametrize("operation", ["info", "migrate"])
def test_populated_commands_analyse_display_history_only_for_state(database_client, operation):
    client, _, migrations, _ = database_client
    script = migrations / "V1__app.sql"
    script.write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    assert client.migrate().success
    manager = client.executor.state_manager
    with (
        observe_reads(client, migrations) as counts,
        patch.object(
            MigrationDataService,
            "_sort_applied_migrations",
            autospec=True,
            side_effect=MigrationDataService._sort_applied_migrations,
        ) as sort_history,
        patch.object(manager, "_analyse_history", wraps=manager._analyse_history) as analyse,
        patch.object(
            BaseCommand,
            "_format_command_header",
            autospec=True,
            side_effect=BaseCommand._format_command_header,
        ) as header,
        patch.object(
            BaseCommand,
            "_format_command_footer",
            autospec=True,
            side_effect=BaseCommand._format_command_footer,
        ) as footer,
    ):
        result = getattr(client, operation)()

    assert result.success, result.error_message
    assert header.call_args.kwargs["schema_version"] == "1"
    assert footer.call_args.kwargs["schema_version"] == "1"
    if operation == "info":
        assert [(entry.script, entry.status) for entry in result.migrations] == [
            (script.name, "SUCCESS")
        ]
    else:
        assert result.migrations == []
        assert result.current_schema_version == "1"
    assert counts == {"history": 2, "files": {script.name: 1}, "scans": 1}
    assert sort_history.call_count == 1
    assert analyse.call_count == 1


def test_resolved_catalog_copy_preserves_order_and_state_json(database_client):
    client, engine, migrations, _ = database_client
    names = [
        "V1__app.sql",
        "R__refresh.sql",
        "U1__app.sql",
        "beforeMigrate__check.sql",
    ]
    for name in names:
        (migrations / name).write_text("SELECT 1;")
    client.executor.history_manager.create_schema_and_history_table(create_schema=False)

    with observe_reads(client, migrations) as counts:
        state = client.executor.state_manager.build_state(migrations)
        copied = state.copy()
        validation = client.executor.validator.validate_migrations(
            migrations,
            resolved_migrations=copied.resolved_objects,
            preloaded_records=copied.all_applied_objects,
        )

    assert [script.script_name for script in copied.resolved_objects] == names
    assert copied.resolved_objects is not state.resolved_objects
    assert [script.script_name for script in validation.migrations] == names
    # Pending state keeps its existing SQL/undo/repeatable order.
    assert [entry.script for entry in state.pending] == [names[0], names[2], names[1]]
    assert validation.success, validation.error_message
    assert counts == {"history": 1, "files": dict.fromkeys(names, 1), "scans": 1}
    payload = copied.to_dict()
    assert set(payload) == set(MigrationState().to_dict())
    assert "resolved_objects" not in payload
    json.dumps(payload)
    assert MigrationState().copy().resolved_objects is None
    assert MigrationState(resolved_objects=[]).copy().resolved_objects == []


@pytest.mark.parametrize("mutation", ["history", "file"])
def test_before_validate_mutation_forces_fresh_validation(database_client, mutation):
    client, _, migrations, _ = database_client
    script = migrations / "V1__app.sql"
    script.write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    assert client.migrate().success
    callback = migrations / "beforeValidate__change.sql"
    if mutation == "history":
        callback.write_text("UPDATE dblift_schema_history SET checksum = '0' WHERE version = '1';")
    else:

        def change_file():
            script.write_text("CREATE TABLE app (id INTEGER PRIMARY KEY, changed TEXT);")
            return 1

        client.provider.connection.create_function("change_file", 0, change_file)
        callback.write_text("SELECT change_file();")

    with observe_reads(client, migrations) as counts:
        result = client.validate()

    assert not result.success
    assert [row.script for row in result.failed_migrations] == [script.name]
    assert any("has been modified" in issue for issue in result.issues)
    assert [(record.phase, record.status) for record in result.callbacks] == [
        ("beforeValidate", "OK")
    ]
    assert counts == {
        "history": 3,
        "files": {script.name: 2, callback.name: 2},
        "scans": 2,
    }


def test_after_validate_history_change_is_visible_in_footer(database_client):
    client, _, migrations, _ = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    assert client.migrate().success
    (migrations / "afterValidate__change.sql").write_text(
        "UPDATE dblift_schema_history SET version = '2' WHERE version = '1';"
    )
    footer_versions = []
    format_footer = BaseCommand._format_command_footer

    def capture_footer(command, *args, **kwargs):
        footer_versions.append(kwargs["schema_version"])
        return format_footer(command, *args, **kwargs)

    with (
        observe_reads(client, migrations) as counts,
        patch.object(BaseCommand, "_format_command_footer", capture_footer),
    ):
        result = client.validate()

    assert result.success, result.error_message
    assert footer_versions == ["2"]
    assert counts["history"] == 2


def test_lock_refresh_sees_other_client_apply_pending_migration(database_client):
    client, _, migrations, database = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    acquire_lock = client.provider.acquire_migration_lock

    def another_client_applies_before_lock(*args, **kwargs):
        other_engine = create_engine(f"sqlite:///{database}")
        other = DBLiftClient.from_sqlalchemy(other_engine, migrations_dir=str(migrations))
        try:
            result = other.migrate()
            assert result.success, result.error_message
        finally:
            other.close()
            other_engine.dispose()
        return acquire_lock(*args, **kwargs)

    with (
        observe_reads(client, migrations) as counts,
        patch.object(client.provider, "acquire_migration_lock", another_client_applies_before_lock),
    ):
        result = client.migrate()

    assert result.success, result.error_message
    assert result.migrations == []
    assert result.current_schema_version == "1"
    assert counts["history"] == 4
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT script, success FROM dblift_schema_history"
        ).fetchall() == [("V1__app.sql", 1)]
        assert connection.execute("SELECT count(*) FROM app").fetchone() == (0,)


def test_same_client_refreshes_files_and_history_after_failure(database_client):
    client, _, migrations, database = database_client
    script = migrations / "V1__app.sql"
    original = "CREATE TABLE app (id INTEGER PRIMARY KEY);"
    script.write_text(original)
    assert client.migrate().success
    assert client.info().migrations[0].status == "SUCCESS"

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE dblift_schema_history SET success = 0 WHERE version = '1'")
    with observe_reads(client, migrations) as counts:
        failed_history = client.validate()
    assert not failed_history.success
    assert failed_history.failed_migrations[0].script == script.name
    assert counts["history"] == 2

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE dblift_schema_history SET success = 1 WHERE version = '1'")
    script.write_text(original + "\n-- changed")
    failed_file = client.validate()
    assert not failed_file.success
    assert any("has been modified" in issue for issue in failed_file.issues)

    script.write_text(original)
    (migrations / "V2__second.sql").write_text("CREATE TABLE second (id INTEGER);")
    info = client.info()
    assert [(row.script, row.status) for row in info.migrations] == [
        (script.name, "SUCCESS"),
        ("V2__second.sql", "PENDING"),
    ]
    recovered = client.migrate()
    assert recovered.success, recovered.error_message
    assert [row.script for row in recovered.migrations] == ["V2__second.sql"]
    assert recovered.current_schema_version == "2"


def test_same_client_refreshes_directory_and_placeholders(database_client):
    client, _, migrations, database = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (value TEXT);")
    (migrations / "R__refresh.sql").write_text("INSERT INTO app VALUES ('${marker}');")
    first = client.migrate(placeholders={"marker": "first"})
    assert first.success, first.error_message

    moved = migrations.with_name("moved")
    migrations.rename(moved)
    client.config.migrations.directory = str(moved)
    (moved / "R__refresh.sql").write_text("INSERT INTO app VALUES ('${marker}-changed');")
    second = client.migrate(placeholders={"marker": "second"})
    assert second.success, second.error_message
    assert [row.script for row in second.migrations] == ["R__refresh.sql"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM app").fetchall() == [
            ("first",),
            ("second-changed",),
        ]


def test_reused_command_refreshes_history_after_header_read_failure(database_client):
    client, _, migrations, _ = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    assert client.migrate().success
    (migrations / "V2__second.sql").write_text("CREATE TABLE second (id INTEGER);")
    command = MigrateCommand(client.executor._make_command_context())
    read_history = command.history_manager.get_applied_migrations
    attempts = 0

    def transient_read_failure():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary history read failure")
        return read_history()

    with patch.object(command.history_manager, "get_applied_migrations", transient_read_failure):
        result = command.execute(migrations)
    assert result.success, result.error_message
    assert [row.script for row in result.migrations] == ["V2__second.sql"]
    with observe_reads(client, migrations) as counts:
        repeated = command.execute(migrations)
    assert repeated.success
    assert repeated.migrations == []
    assert repeated.current_schema_version == "2"
    assert counts["history"] == 2


def test_migrate_dry_run_keeps_database_bytes_and_pending_results(database_client):
    client, _, migrations, database = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    assert client.migrate().success
    (migrations / "V2__second.sql").write_text("CREATE TABLE second (id INTEGER);")
    original = database.read_bytes()

    with observe_reads(client, migrations) as counts:
        result = client.migrate(dry_run=True)

    assert result.success, result.error_message
    assert [row.script for row in result.migrations] == ["V2__second.sql"]
    assert result.dry_run_count == 1
    assert database.read_bytes() == original
    assert counts == {
        "history": 2,
        "files": {"V1__app.sql": 1, "V2__second.sql": 1},
        "scans": 1,
    }


def test_nonempty_recursion_map_preserves_validator_discovery_scope(database_client):
    client, _, migrations, _ = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    nested = migrations / "nested"
    nested.mkdir()
    (nested / "V1__duplicate.sql").write_text("SELECT 1;")
    with observe_reads(client, migrations) as counts:
        result = client.migrate(recursive=True, dir_recursive_map={migrations: False})

    assert result.success, result.error_message
    assert [m.script for m in result.migrations] == ["V1__app.sql"]
    assert counts == {"history": 4, "files": {"V1__app.sql": 2}, "scans": 2}


@pytest.mark.parametrize("state_fails", [False, True])
def test_info_duplicate_warning_reuses_catalog_or_falls_back_after_state_failure(
    database_client, state_fails
):
    client, _, migrations, _ = database_client
    (migrations / "V1__app.sql").write_text("SELECT 1;")
    (migrations / "V1__duplicate.sql").write_text("SELECT 2;")
    state_manager = client.executor.state_manager
    with (
        observe_reads(client, migrations) as counts,
        patch.object(client.executor.log, "warning", wraps=client.executor.log.warning) as warnings,
        patch.object(
            state_manager,
            "build_state",
            side_effect=RuntimeError("cannot build state") if state_fails else None,
            wraps=state_manager.build_state,
        ),
    ):
        result = client.info()

    assert result.success, result.error_message
    assert len(result.migrations) == (0 if state_fails else 2)
    assert any("Duplicate version 1" in call.args[0] for call in warnings.call_args_list)
    assert counts == {
        "history": 2,
        "files": {"V1__app.sql": 1, "V1__duplicate.sql": 1},
        "scans": 1,
    }


def test_empty_info_catalog_does_not_retry_discovery(database_client):
    client, _, migrations, _ = database_client
    with observe_reads(client, migrations) as counts:
        result = client.info()
    assert result.success
    assert result.migrations == []
    assert counts == {"history": 2, "files": {}, "scans": 1}


def test_strict_empty_validate_reuses_header_history(database_client):
    client, _, migrations, _ = database_client
    script = migrations / "V1__app.sql"
    script.write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    assert client.migrate().success
    script.unlink()
    client.config.strict_mode = True
    with observe_reads(client, migrations) as counts:
        result = client.validate()
    assert not result.success
    assert counts == {"history": 2, "files": {}, "scans": 2}


def test_filtered_migrate_keeps_full_catalog_for_missing_file_validation(database_client):
    client, _, migrations, _ = database_client
    excluded = migrations / "V1__excluded[other].sql"
    excluded.write_text("CREATE TABLE other (id INTEGER);")
    (migrations / "V2__included[keep].sql").write_text("CREATE TABLE kept (id INTEGER);")
    assert client.migrate().success
    (migrations / "V3__new[keep].sql").write_text("CREATE TABLE new (id INTEGER);")
    with (
        observe_reads(client, migrations) as counts,
        patch.object(client.executor.log, "warning", wraps=client.executor.log.warning) as warnings,
    ):
        filtered = client.migrate(tags="keep")
    assert filtered.success, filtered.error_message
    assert [row.script for row in filtered.migrations] == ["V3__new[keep].sql"]
    assert not any("is missing from" in call.args[0] for call in warnings.call_args_list)
    assert counts["scans"] == 2

    excluded.unlink()
    with (
        observe_reads(client, migrations) as counts,
        patch.object(client.executor.log, "warning", wraps=client.executor.log.warning) as warnings,
    ):
        missing = client.migrate(tags="keep")
    assert missing.success, missing.error_message
    assert any("is missing from" in call.args[0] for call in warnings.call_args_list)
    assert counts["history"] == 2
    assert counts["scans"] == 1

    client.config.strict_mode = True
    strict_missing = client.migrate(tags="keep")
    assert not strict_missing.success
    assert excluded.name in strict_missing.error_message
    assert "without corresponding script files" in strict_missing.error_message


@pytest.mark.parametrize("command_type", [MigrateCommand, InfoCommand, ValidateCommand])
def test_commands_consume_history_through_state_manager(database_client, command_type):
    client, _, migrations, _ = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    (migrations / "beforeEach__check.sql").write_text("SELECT 1;")
    command = command_type(client.executor._make_command_context())
    command.history_manager = MagicMock(wraps=client.executor.history_manager)
    command.history_manager.get_applied_migrations.side_effect = AssertionError(
        "Command bypassed the state manager for history"
    )
    command.history_manager.get_applied_migration_records.side_effect = AssertionError(
        "Command bypassed the state manager for typed history"
    )
    command.script_manager = MagicMock(wraps=client.executor.script_manager)
    for method in ("load_migration_scripts", "get_migration_scripts", "get_callbacks_by_event"):
        getattr(command.script_manager, method).side_effect = AssertionError(
            "Command bypassed the state manager for script data"
        )
    command.validator.script_manager = command.script_manager

    with observe_reads(client, migrations) as counts:
        result = command.execute(migrations)

    assert result.success, result.error_message
    command.history_manager.get_applied_migrations.assert_not_called()
    command.history_manager.get_applied_migration_records.assert_not_called()
    command.script_manager.load_migration_scripts.assert_not_called()
    command.script_manager.get_migration_scripts.assert_not_called()
    command.script_manager.get_callbacks_by_event.assert_not_called()
    assert counts["history"] == (4 if command_type is MigrateCommand else 2)


def test_info_catalog_fallback_consumes_state_manager_data(database_client):
    client, _, migrations, _ = database_client
    (migrations / "V1__first.sql").write_text("SELECT 1;")
    (migrations / "V1__duplicate.sql").write_text("SELECT 2;")
    command = InfoCommand(client.executor._make_command_context())
    command.script_manager = MagicMock(wraps=client.executor.script_manager)
    command.script_manager.get_migration_scripts.side_effect = AssertionError(
        "Command bypassed the state manager for fallback catalog"
    )

    with (
        observe_reads(client, migrations) as counts,
        patch.object(
            command.state_manager, "build_state", side_effect=RuntimeError("state unavailable")
        ),
        patch.object(command.log, "warning", wraps=command.log.warning) as warnings,
    ):
        result = command.execute(migrations, display_human=False)

    assert result.success, result.error_message
    assert any("Duplicate version 1" in call.args[0] for call in warnings.call_args_list)
    command.script_manager.get_migration_scripts.assert_not_called()
    assert counts["scans"] == 1


@pytest.mark.parametrize(
    "rows,expected_version",
    [
        ([("BASELINE", "3", True)], "3"),
        ([("SQL", "1", True), ("SQL", "2", True), ("UNDO_SQL", "2", True)], "1"),
        (
            [
                ("SQL", "1", True),
                ("SQL", "2", True),
                ("UNDO_SQL", "2", True),
                ("SQL", "2", True),
            ],
            "2",
        ),
        ([("SQL", "1", True), ("SQL", "3", False)], "1"),
    ],
)
def test_state_manager_snapshot_preserves_header_version_semantics(
    database_client, rows, expected_version
):
    client, _, migrations, database = database_client
    client.executor.history_manager.create_schema_and_history_table(create_schema=False)
    with sqlite3.connect(database) as connection:
        for rank, (migration_type, version, success) in enumerate(rows, 1):
            connection.execute(
                "INSERT INTO dblift_schema_history "
                "(installed_rank, script, type, version, success) VALUES (?, ?, ?, ?, ?)",
                (rank, f"{migration_type}{version}__test.sql", migration_type, version, success),
            )
    manager = client.executor.state_manager
    command = InfoCommand(client.executor._make_command_context())
    with observe_reads(client, migrations) as counts:
        snapshot = manager.new_read_snapshot()
        assert counts["history"] == 0
        assert manager.resolve_current_schema_version(snapshot) == expected_version
        assert command._resolve_current_schema_version(read_snapshot=snapshot) == expected_version
        assert len(manager.build_state(None, read_snapshot=snapshot).all_applied_objects) == len(
            rows
        )
    assert counts["history"] == 1


def test_manager_snapshot_retries_failed_reads_and_retains_successful_empty_history(
    database_client,
):
    client, _, migrations, _ = database_client
    client.executor.history_manager.create_schema_and_history_table(create_schema=False)
    manager = client.executor.state_manager
    snapshot = manager.new_read_snapshot()
    command = InfoCommand(client.executor._make_command_context())
    read_history = client.executor.history_manager.get_applied_migrations
    attempts = 0

    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary history failure")
        return read_history()

    with (
        observe_reads(client, migrations) as counts,
        patch.object(client.executor.history_manager, "get_applied_migrations", fail_once),
    ):
        assert command._resolve_current_schema_version(read_snapshot=snapshot) is None
        assert manager.build_state(migrations, read_snapshot=snapshot).all_applied_objects == []
        assert snapshot.get_applied_migrations() == []
    assert attempts == 2
    assert counts["history"] == 1


def test_callback_discovery_sees_file_created_during_lock_acquisition(database_client):
    client, _, migrations, database = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    acquire_lock = client.provider.acquire_migration_lock

    def create_callback_then_lock(*args, **kwargs):
        (migrations / "beforeMigrate__late.sql").write_text(
            "CREATE TABLE callback_discovered_after_lock (id INTEGER);"
        )
        return acquire_lock(*args, **kwargs)

    with (
        observe_reads(client, migrations) as counts,
        patch.object(client.provider, "acquire_migration_lock", create_callback_then_lock),
    ):
        result = client.migrate()

    assert result.success, result.error_message
    assert [(record.phase, record.file, record.status) for record in result.callbacks] == [
        ("beforeMigrate", "beforeMigrate__late.sql", "OK")
    ]
    assert counts == {
        "history": 4,
        "files": {"V1__app.sql": 2, "beforeMigrate__late.sql": 1},
        "scans": 2,
    }
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM callback_discovered_after_lock"
        ).fetchone() == (0,)


def test_grouped_state_catalog_preserves_collector_data_and_refreshes(database_client):
    client, _, migrations, _ = database_client
    (migrations / "V1__app.sql").write_text("SELECT 1;")
    (migrations / "U1__app.sql").write_text("SELECT 2;")
    (migrations / "R__app.sql").write_text("SELECT 3;")
    (migrations / "beforeMigrate__app.sql").write_text("SELECT 4;")
    additional = migrations.parent / "additional"
    additional.mkdir()
    (additional / "V2__extra.sql").write_text("SELECT 5;")
    options = {
        "recursive": False,
        "additional_dirs": [additional],
        "dir_recursive_map": {additional: True},
    }
    collector = client.executor.script_manager
    collected = []
    original_load = collector.load_migration_scripts

    def capture_catalog(*args, **kwargs):
        catalog = original_load(*args, **kwargs)
        collected.append(catalog)
        return catalog

    with patch.object(collector, "load_migration_scripts", side_effect=capture_catalog) as load:
        first = client.executor.state_manager.get_grouped_migrations(migrations, **options)
        (migrations / "V1__app.sql").write_text("SELECT 100;")
        second = client.executor.state_manager.get_grouped_migrations(migrations, **options)

    assert first is collected[0]
    assert second is collected[1]
    assert first is not second
    assert [kind.name for kind in first] == [
        "SQL",
        "UNDO_SQL",
        "REPEATABLE",
        "BASELINE",
        "CALLBACK",
    ]
    assert [[migration.script_name for migration in group] for group in first.values()] == [
        ["V1__app.sql", "V2__extra.sql"],
        ["U1__app.sql"],
        ["R__app.sql"],
        [],
        ["beforeMigrate__app.sql"],
    ]
    assert next(iter(first.values()))[0].checksum != next(iter(second.values()))[0].checksum
    assert load.call_count == 2
    for invocation in load.call_args_list:
        assert invocation.args == (migrations,)
        assert invocation.kwargs == options


def test_repair_consumes_fresh_grouped_state_data_for_preview_and_write(database_client):
    client, _, migrations, database = database_client
    script = migrations / "V1__app.sql"
    script.write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);")
    assert client.migrate().success
    script.write_text("CREATE TABLE app (id INTEGER PRIMARY KEY);\n-- changed checksum\n")
    command = RepairCommand(client.executor._make_command_context())
    command.script_manager = MagicMock(wraps=client.executor.script_manager)
    command.script_manager.load_migration_scripts.side_effect = AssertionError(
        "Repair bypassed the state manager for grouped scripts"
    )
    before = database.read_bytes()
    preview = command.execute(migrations, dry_run=True)
    assert preview.success, preview.error_message
    assert database.read_bytes() == before
    assert not client.validate().success

    repaired = command.execute(migrations)
    assert repaired.success, repaired.error_message
    assert client.validate().success
    command.script_manager.load_migration_scripts.assert_not_called()


def test_baseline_dry_run_consumes_fresh_typed_state_history(database_client):
    client, _, _, database = database_client
    history = client.executor.history_manager
    command = BaselineCommand(client.executor._make_command_context())

    class HistoryOperationsOnly:
        def __getattr__(self, name):
            if name == "get_applied_migration_records":
                raise AssertionError("Baseline bypassed the state manager for typed history")
            return getattr(history, name)

    command.history_manager = HistoryOperationsOnly()
    manager = command.state_manager
    with patch.object(
        manager, "get_applied_migration_records", wraps=manager.get_applied_migration_records
    ) as read:
        absent = command.execute("2", dry_run=True)
        assert absent.success, absent.error_message
        read.assert_not_called()
        assert not history.has_history_table

        history.create_schema_and_history_table(create_schema=False)
        empty = command.execute("2", dry_run=True)
        assert empty.success, empty.error_message
        assert read.call_count == 1

        assert client.baseline("1").success
        before = database.read_bytes()
        populated = command.execute("2", dry_run=True)
        assert not populated.success
        assert "1 migration(s)" in populated.error_message
        assert read.call_count == 2
        assert database.read_bytes() == before


@pytest.mark.parametrize("operation", ["validate", "migrate"])
def test_commands_validate_state_snapshots_without_public_collection_adapters(
    database_client, operation
):
    client, _, migrations, _ = database_client
    (migrations / "V1__app.sql").write_text("SELECT 1;")
    manager = client.executor.state_manager
    validator = client.executor.validator
    with (
        patch.object(
            manager, "build_validation_snapshot", wraps=manager.build_validation_snapshot
        ) as build,
        patch.object(validator, "validate_snapshot", wraps=validator.validate_snapshot) as validate,
        patch.object(
            validator, "validate_migrations", side_effect=AssertionError("legacy adapter")
        ),
        patch.object(
            validator, "validate_resolved_migrations", side_effect=AssertionError("legacy adapter")
        ),
    ):
        result = getattr(client, operation)()
    assert result.success, result.error_message
    assert build.call_count == validate.call_count == 1
    assert validate.call_args.args[0].selected_migrations[0].script_name == "V1__app.sql"


@pytest.mark.parametrize(
    "collection_method", ["get_migration_scripts", "migration_directory_exists"]
)
@pytest.mark.parametrize("error_message", ["catalog unavailable", ""])
def test_validate_catalog_error_preserves_after_validate_callback(
    database_client, collection_method, error_message
):
    client, _, migrations, database = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE callback_audit (event TEXT);")
    assert client.migrate().success
    (migrations / "afterValidate__audit.sql").write_text(
        "INSERT INTO callback_audit VALUES ('afterValidate');"
    )

    with patch.object(
        client.executor.script_manager,
        collection_method,
        side_effect=PermissionError(error_message),
    ):
        result = client.validate()

    assert result.success is False
    assert result.error_message == f"Validation failed: {error_message}"
    assert [(record.phase, record.status) for record in result.callbacks] == [
        ("afterValidate", "OK")
    ]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT event FROM callback_audit").fetchall() == [
            ("afterValidate",)
        ]


def test_migrate_preloaded_catalog_remains_authoritative_on_probe_failure(database_client):
    client, _, migrations, database = database_client
    (migrations / "V1__app.sql").write_text("CREATE TABLE app (id INTEGER);")
    with (
        patch.object(
            client.executor.script_manager,
            "get_migration_scripts",
            side_effect=PermissionError("catalog unavailable"),
        ) as catalog,
        patch.object(
            client.executor.script_manager,
            "migration_directory_exists",
            side_effect=PermissionError("directory unavailable"),
        ) as directory,
    ):
        result = client.migrate()
    assert result.success, result.error_message
    assert [row.script for row in result.migrations] == ["V1__app.sql"]
    catalog.assert_not_called()
    directory.assert_not_called()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM app").fetchone() == (0,)


@pytest.mark.parametrize(
    "description,expected_description", [("", "B1__"), ("snapshot", "snapshot")]
)
def test_baseline_synthetic_record_never_uses_model_filename_inference(
    database_client, monkeypatch, description, expected_description
):
    from dblift.core.migration.migration import Migration

    client, _, _, database = database_client

    def forbidden(*args, **kwargs):
        raise AssertionError("synthetic record invoked model filename inference")

    monkeypatch.setattr(Migration, "_parse_filename", forbidden)
    result = client.baseline("1", description=description)
    assert result.success, result.error_message
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT script, version, description, type FROM dblift_schema_history"
        ).fetchall()
    assert rows == [(f"B1__{description}.sql", "1", expected_description, "BASELINE")]


@pytest.mark.parametrize("version,expected_version", [(None, "1.2"), ("9", "9")])
def test_repair_delete_record_never_uses_model_filename_inference(
    database_client, monkeypatch, version, expected_version
):
    from dblift.core.logger.results import RepairResult
    from dblift.core.migration.migration import Migration, MigrationType

    client, _, _, database = database_client
    history = client.executor.history_manager
    history.create_schema_and_history_table(create_schema=False)
    command = RepairCommand(client.executor._make_command_context())
    stored = []
    record = history.record_migration

    def record_and_capture(migration, **kwargs):
        stored.append(migration)
        return record(migration, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("synthetic record invoked model filename inference")

    monkeypatch.setattr(history, "record_migration", record_and_capture)
    monkeypatch.setattr(Migration, "_parse_filename", forbidden)
    result = RepairResult()
    count, failed = command._execute_repair_loop(
        [
            {
                "type": "MISSING_SCRIPT",
                "script": "V1_2__missing[tag].sql",
                "version": version,
                "description": "missing",
                "original_type": MigrationType.SQL,
            }
        ],
        result,
    )
    assert not failed, result.error_message
    assert count == 1
    assert result.deleted_migrations_marked == 1
    assert stored[0].tags == ["tag"]
    assert stored[0].content == "-- Delete operation: [DELETE:SQL] missing"
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT script, version, description, type FROM dblift_schema_history"
        ).fetchall()
    assert rows == [("V1_2__missing[tag].sql", expected_version, "[DELETE:SQL] missing", "DELETE")]


@pytest.mark.parametrize("filename", ["V__.sql", "V__.py"])
@pytest.mark.parametrize("operation", ["validate", "migrate"])
def test_versionless_scripts_are_never_validated_executed_or_recorded(
    database_client, filename, operation
):
    client, _, migrations, database = database_client
    malformed = (
        "CREATE TABLE malformed_ran (id INT);"
        if filename.endswith(".sql")
        else 'def migrate(context):\n    context.execute("CREATE TABLE malformed_ran (id INT)")\n'
    )
    (migrations / filename).write_text(malformed, encoding="utf-8")
    (migrations / "V1__control.sql").write_text("CREATE TABLE control (id INT);", encoding="utf-8")

    result = getattr(client, operation)()

    assert result.success, result.error_message
    if operation == "validate":
        assert [migration.script for migration in result.validated_migrations] == [
            "V1__control.sql"
        ]
    with sqlite3.connect(database) as connection:
        user_tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('control', 'malformed_ran')"
        ).fetchall()
        recorded = connection.execute(
            "SELECT script FROM dblift_schema_history ORDER BY installed_rank"
        ).fetchall()
    assert user_tables == ([("control",)] if operation == "migrate" else [])
    assert recorded == ([("V1__control.sql",)] if operation == "migrate" else [])
