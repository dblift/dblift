"""Extension checks inspect complete prepared scripts before execution starts."""

import sqlite3
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.seams import runtime_checks


@pytest.fixture(params=["execution", "full"])
def client(tmp_path, request):
    scripts = tmp_path / "sql"
    scripts.mkdir()
    (scripts / "V1__first.sql").write_text("CREATE TABLE earlier (id INTEGER);")
    (scripts / "V2__mixed.sql").write_text(
        "CREATE TABLE ${table} (id INTEGER); INSERT INTO ${table} VALUES (1);"
    )
    for event in ("beforeMigrate", "beforeEach", "afterEach", "afterMigrateError"):
        (scripts / f"{event}__callback.sql").write_text("CREATE TABLE callback_ran (id INTEGER);")
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    saved = {key: list(value) for key, value in runtime_checks._CHECKS.items()}
    runtime_checks.clear_checks()
    with DBLiftClient.from_sqlalchemy(
        engine, migrations_dir=scripts, analysis_mode=request.param
    ) as instance:
        yield instance, tmp_path / "db.sqlite"
    engine.dispose()
    runtime_checks.clear_checks()
    runtime_checks._CHECKS.update(saved)


def _register_rejection(client, *, under_lock=False):
    seen = []

    def check(*, migration, statements, provider):
        assert provider is client.provider
        assert provider.is_connected()
        seen.append((migration.script_name, statements))
        if migration.script_name == "V2__mixed.sql" and (
            not under_lock or sum(name == migration.script_name for name, _ in seen) > 1
        ):
            # Resolve the refusal type only when the seam actually invokes the check.
            raise runtime_checks.SqlPreflightError("extension rejected complete script")

    runtime_checks.register_check("migration.preflight_sql", check)
    return seen


@pytest.mark.parametrize("direct_command", [False, True])
def test_rejection_precedes_earlier_script_callbacks_and_history(client, direct_command):
    instance, db = client
    seen = _register_rejection(instance)
    with patch.object(MigrateCommand, "_fire") as fire:
        if direct_command:
            result = MigrateCommand(instance.executor._make_command_context()).execute(
                db.parent / "sql", placeholders={"table": "later"}
            )
        else:
            result = instance.migrate(placeholders={"table": "later"})
    assert not result.success
    assert "extension rejected complete script" in result.error_message
    assert seen == [
        ("V1__first.sql", ["CREATE TABLE earlier (id INTEGER)"]),
        ("V2__mixed.sql", ["CREATE TABLE later (id INTEGER)", "INSERT INTO later VALUES (1)"]),
    ]
    fire.assert_not_called()
    assert instance.executor.journal.entries == []
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_locked_plan_rechecks_unchanged_scripts_before_callbacks(client):
    instance, db = client
    seen = _register_rejection(instance, under_lock=True)
    with patch.object(MigrateCommand, "_fire") as fire:
        result = instance.migrate(placeholders={"table": "later"})
    assert not result.success
    assert "extension rejected complete script" in result.error_message
    assert [name for name, _ in seen].count("V2__mixed.sql") == 2
    fire.assert_not_called()
    assert instance.executor.journal.entries == []
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute(
                "SELECT name FROM sqlite_master WHERE name IN ('earlier', 'later', 'callback_ran')"
            ).fetchall()
            == []
        )
        assert observer.execute("SELECT count(*) FROM dblift_schema_history").fetchone() == (0,)


def test_dry_run_keeps_application_checks_disabled(client):
    instance, db = client
    seen = _register_rejection(instance)
    result = instance.migrate(dry_run=True, placeholders={"table": "later"})
    assert result.success, result.error_message
    assert seen == []
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_callback_sql_is_checked_before_any_script_or_history(client):
    instance, db = client
    seen = []

    def check(*, migration, statements, provider):
        assert provider is instance.provider
        assert provider.is_connected()
        seen.append(migration.script_name)
        if migration.script_name == "beforeMigrate__callback.sql":
            assert statements == ["CREATE TABLE callback_ran (id INTEGER)"]
            raise runtime_checks.SqlPreflightError("extension rejected callback")

    runtime_checks.register_check("migration.preflight_sql", check)
    with patch.object(MigrateCommand, "_fire") as fire:
        result = instance.migrate(placeholders={"table": "later"})
    assert not result.success
    assert "extension rejected callback" in result.error_message
    assert seen == ["V1__first.sql", "V2__mixed.sql", "beforeMigrate__callback.sql"]
    fire.assert_not_called()
    assert instance.executor.journal.entries == []
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_callback_state_change_is_rechecked_before_script_journal_or_sql(client):
    instance, db = client
    (db.parent / "sql" / "beforeEach__callback.sql").write_text(
        "CREATE TABLE changed_by_callback (id INTEGER);"
    )
    # Other callback scripts would all create the same table; isolate beforeEach.
    for path in (db.parent / "sql").glob("*__callback.sql"):
        if not path.name.startswith("beforeEach__"):
            path.unlink()

    def check(*, migration, statements, provider):
        if migration.script_name != "V1__first.sql":
            return
        with sqlite3.connect(db) as observer:
            changed = observer.execute(
                "SELECT name FROM sqlite_master WHERE name='changed_by_callback'"
            ).fetchall()
        if changed:
            raise runtime_checks.SqlPreflightError("catalog changed after callback")

    runtime_checks.register_check("migration.preflight_sql", check)
    real_fire = MigrateCommand._fire
    with patch("dblift.core.migration.commands._script_runner.emit_script_event") as emit:
        with patch.object(MigrateCommand, "_fire", autospec=True, wraps=real_fire) as fire:
            # Keep actual callback execution, while observing error/after callbacks.
            fire.side_effect = real_fire
            result = instance.migrate(placeholders={"table": "later"})
    assert not result.success
    assert "catalog changed after callback" in result.error_message
    assert "afterMigrateError" not in [call.args[1] for call in fire.call_args_list]
    assert "afterEach" not in [call.args[1] for call in fire.call_args_list]
    assert not [e for e in instance.executor.journal.entries if e.migration_id == "V1__first.sql"]
    emit.assert_not_called()
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute("SELECT name FROM sqlite_master WHERE name='earlier'").fetchall() == []
        )
        assert observer.execute("SELECT count(*) FROM changed_by_callback").fetchone() == (0,)
        assert observer.execute("SELECT count(*) FROM dblift_schema_history").fetchone() == (0,)


def test_recheck_after_started_event_closes_attempt_without_sql_or_history(client):
    instance, db = client
    started = False
    events = []

    def check(*, migration, statements, provider):
        if started:
            raise runtime_checks.SqlPreflightError("catalog changed after started event")

    def emit(event, data):
        nonlocal started
        events.append(event)
        if event == "migration.script.started":
            started = True

    runtime_checks.register_check("migration.preflight_sql", check)
    with patch("dblift.core.migration.commands._script_runner.emit_script_event", side_effect=emit):
        with patch.object(MigrateCommand, "_fire") as fire:
            result = instance.migrate(placeholders={"table": "later"})
    assert not result.success
    assert "catalog changed after started event" in result.error_message
    assert "afterMigrateError" not in [call.args[0] for call in fire.call_args_list]
    assert events == ["migration.script.started", "migration.script.failed"]
    assert [entry.entry_type.value for entry in instance.executor.journal.entries] == [
        "MIGRATION_START",
        "MIGRATION_FAILED",
    ]
    assert instance.executor.journal.current_migration_id is None
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute("SELECT name FROM sqlite_master WHERE name='earlier'").fetchall() == []
        )
        assert observer.execute("SELECT count(*) FROM dblift_schema_history").fetchone() == (0,)


def test_check_receives_configured_schema_without_switching_connection(client):
    instance, db = client
    instance.config.database.schema = "configured_target"
    seen = []

    def check(*, migration, statements, provider):
        with sqlite3.connect(db) as observer:
            assert observer.execute("PRAGMA database_list").fetchone()[1] == "main"
        seen.append(provider.config.database.schema)
        raise runtime_checks.SqlPreflightError("target schema is available to extension")

    runtime_checks.register_check("migration.preflight_sql", check)
    with patch.object(instance.provider, "set_current_schema", create=True) as switch:
        result = instance.migrate(placeholders={"table": "later"})
    assert not result.success
    assert "target schema is available to extension" in result.error_message
    assert seen == ["configured_target"]
    switch.assert_not_called()
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )
