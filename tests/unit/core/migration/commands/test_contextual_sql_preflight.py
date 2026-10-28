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

    def check(*, migration, statements, provider, prepared_migrations, migration_index):
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

    def check(*, migration, statements, provider, prepared_migrations, migration_index):
        assert provider is instance.provider
        assert provider.is_connected()
        seen.append(migration.script_name)
        if migration.script_name == "beforeMigrate__callback.sql":
            assert prepared_migrations == []
            assert migration_index is None
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

    def check(*, migration, statements, provider, prepared_migrations, migration_index):
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

    def check(*, migration, statements, provider, prepared_migrations, migration_index):
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

    def check(*, migration, statements, provider, prepared_migrations, migration_index):
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


def test_callback_sql_is_rechecked_after_prior_callback_changes_state(client):
    instance, db = client
    scripts = db.parent / "sql"
    (scripts / "V2__mixed.sql").unlink()
    (scripts / "beforeMigrate__callback.sql").write_text("CREATE TABLE state_changed (id INTEGER);")
    (scripts / "beforeEach__callback.sql").write_text("CREATE TABLE unsafe_callback (id INTEGER);")
    (scripts / "afterEach__callback.sql").write_text("CREATE TABLE after_each_ran (id INTEGER);")
    (scripts / "afterMigrateError__callback.sql").write_text(
        "CREATE TABLE error_callback_ran (id INTEGER);"
    )

    def check(*, migration, statements, provider, prepared_migrations, migration_index):
        if migration.script_name != "beforeEach__callback.sql":
            return
        with sqlite3.connect(db) as observer:
            changed = observer.execute(
                "SELECT name FROM sqlite_master WHERE name='state_changed'"
            ).fetchall()
        if changed:
            raise runtime_checks.SqlPreflightError("callback refused after catalog change")

    runtime_checks.register_check("migration.preflight_sql", check)
    with patch("dblift.core.migration.commands.base_command._emit_script_event") as emit:
        result = instance.migrate(placeholders={"table": "later"})
    assert not result.success
    assert "callback refused after catalog change" in result.error_message
    callback_events = [
        (call.args[0], call.args[1]["name"])
        for call in emit.call_args_list
        if call.args[0] in ("callback.started", "callback.completed", "callback.failed")
    ]
    assert callback_events == [
        ("callback.started", "beforeMigrate__callback.sql"),
        ("callback.completed", "beforeMigrate__callback.sql"),
        ("callback.started", "beforeEach__callback.sql"),
        ("callback.failed", "beforeEach__callback.sql"),
    ]
    assert [(record.phase, record.status) for record in result.callbacks] == [
        ("beforeMigrate", "OK"),
        ("beforeEach", "FAILED"),
    ]
    assert instance.executor.journal.entries == []
    with sqlite3.connect(db) as observer:
        assert observer.execute("SELECT count(*) FROM state_changed").fetchone() == (0,)
        assert (
            observer.execute(
                "SELECT name FROM sqlite_master WHERE name IN "
                "('earlier', 'unsafe_callback', 'after_each_ran', 'error_callback_ran')"
            ).fetchall()
            == []
        )
        assert observer.execute("SELECT count(*) FROM dblift_schema_history").fetchone() == (0,)


def test_check_receives_ordered_selected_batch_without_callbacks(client):
    instance, db = client
    seen = []

    def check(**context):
        seen.append(context)
        if context["migration"].script_name == "V2__mixed.sql":
            raise runtime_checks.SqlPreflightError("ordered batch checked")

    runtime_checks.register_check("migration.preflight_sql", check)
    result = instance.migrate(placeholders={"table": "later"})
    assert not result.success
    assert "ordered batch checked" in result.error_message
    assert len(seen) == 2
    for index, context in enumerate(seen):
        assert context.get("prepared_migrations") is not None, "ordered batch context missing"
        batch = context["prepared_migrations"]
        assert context["migration_index"] == index
        assert [migration.script_name for migration, _ in batch] == [
            "V1__first.sql",
            "V2__mixed.sql",
        ]
        assert batch[index][0] is context["migration"]
        assert batch[index][1] is context["statements"]
        assert batch[1][1] == ["CREATE TABLE later (id INTEGER)", "INSERT INTO later VALUES (1)"]
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_error_callback_refusal_keeps_original_failure_and_warning_only(client):
    instance, db = client
    scripts = db.parent / "sql"
    (scripts / "V1__first.sql").write_text("INSERT INTO missing_table VALUES (1);")
    (scripts / "V2__mixed.sql").unlink()
    for name in (
        "beforeMigrate__callback.sql",
        "beforeEach__callback.sql",
        "afterEach__callback.sql",
    ):
        (scripts / name).unlink()
    (scripts / "afterMigrateError__callback.sql").write_text(
        "CREATE TABLE error_callback_ran (id INTEGER);"
    )

    def check(**context):
        if context["migration"].script_name != "afterMigrateError__callback.sql":
            return
        with sqlite3.connect(db) as observer:
            history = observer.execute(
                "SELECT name FROM sqlite_master WHERE name='dblift_schema_history'"
            ).fetchall()
            failed = (
                history
                and observer.execute(
                    "SELECT count(*) FROM dblift_schema_history WHERE success=0"
                ).fetchone()[0]
            )
        if failed:
            raise runtime_checks.SqlPreflightError("error callback refused")

    runtime_checks.register_check("migration.preflight_sql", check)
    with patch.object(instance.executor.log, "warning") as warning:
        result = instance.migrate()
    assert not result.success
    assert "missing_table" in result.error_message
    assert "error callback refused" not in result.error_message
    assert any("error callback refused" in str(call) for call in warning.call_args_list)
    assert [(record.phase, record.status) for record in result.callbacks] == [
        ("afterMigrateError", "FAILED")
    ]
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute(
                "SELECT name FROM sqlite_master WHERE name='error_callback_ran'"
            ).fetchall()
            == []
        )


def test_batch_is_rechecked_under_lock_and_execution_uses_local_context(client):
    instance, db = client
    for path in (db.parent / "sql").glob("*__callback.sql"):
        path.unlink()
    seen = []

    def check(**context):
        batch = context["prepared_migrations"]
        index = context["migration_index"]
        assert batch[index] == (context["migration"], context["statements"])
        seen.append(([migration.script_name for migration, _ in batch], index))

    runtime_checks.register_check("migration.preflight_sql", check)
    result = instance.migrate(placeholders={"table": "later"})
    assert result.success, result.error_message
    assert seen == [
        (["V1__first.sql", "V2__mixed.sql"], 0),
        (["V1__first.sql", "V2__mixed.sql"], 1),
        (["V1__first.sql", "V2__mixed.sql"], 0),
        (["V1__first.sql", "V2__mixed.sql"], 1),
        (["V1__first.sql"], 0),
        (["V1__first.sql"], 0),
        (["V2__mixed.sql"], 0),
        (["V2__mixed.sql"], 0),
    ]


def test_batch_preserves_non_sql_migrations_as_explicit_opaque_entries(client):
    instance, db = client
    (db.parent / "sql" / "V3__opaque.py").write_text('raise AssertionError("must not execute")')
    seen = []

    def check(**context):
        seen.extend(context["prepared_migrations"])
        raise runtime_checks.SqlPreflightError("inspect ordered formats")

    runtime_checks.register_check("migration.preflight_sql", check)
    result = instance.migrate(placeholders={"table": "later"})
    assert not result.success
    assert "inspect ordered formats" in result.error_message
    assert [migration.script_name for migration, _ in seen] == [
        "V1__first.sql",
        "V2__mixed.sql",
        "V3__opaque.py",
    ]
    assert seen[-1][0].format.value == "python"
    assert seen[-1][1] == []


def _prepare_undo(instance, db):
    scripts = db.parent / "sql"
    for path in scripts.glob("*__callback.sql"):
        path.unlink()
    (scripts / "V2__mixed.sql").unlink()
    assert instance.migrate().success
    (scripts / "U1__first.sql").write_text(
        "DROP TABLE earlier; CREATE TABLE undone_marker (id INTEGER);"
    )
    (scripts / "afterUndoError__callback.sql").write_text(
        "CREATE TABLE undo_error_ran (id INTEGER);"
    )
    with sqlite3.connect(db) as observer:
        return observer.execute("SELECT script, success FROM dblift_schema_history").fetchall()


@pytest.mark.parametrize(
    "target", ["U1__first.sql", "beforeUndo__check.sql", "afterUndo__check.sql"]
)
def test_undo_batch_refusal_preserves_schema_history_and_skips_error_callbacks(client, target):
    instance, db = client
    before_history = _prepare_undo(instance, db)
    if target != "U1__first.sql":
        (db.parent / "sql" / target).write_text("CREATE TABLE undo_callback_ran (id INTEGER);")

    def check(**context):
        if context["migration"].script_name == target:
            raise runtime_checks.SqlPreflightError("undo batch refused")

    runtime_checks.register_check("migration.preflight_sql", check)
    result = instance.undo()
    assert not result.success
    assert "undo batch refused" in result.error_message
    assert result.callbacks == []
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute("SELECT script, success FROM dblift_schema_history").fetchall()
            == before_history
        )
        assert observer.execute("SELECT count(*) FROM earlier").fetchone() == (0,)
        assert (
            observer.execute(
                "SELECT name FROM sqlite_master WHERE name IN "
                "('undone_marker', 'undo_error_ran', 'undo_callback_ran')"
            ).fetchall()
            == []
        )


@pytest.mark.parametrize("event", ["beforeUndo", "afterUndo", "beforeEach"])
def test_undo_callback_execution_refusal_does_not_run_error_callbacks(client, event):
    instance, db = client
    before_history = _prepare_undo(instance, db)
    target = f"{event}__check.sql"
    (db.parent / "sql" / target).write_text("CREATE TABLE undo_callback_ran (id INTEGER);")
    started = False

    def check(**context):
        if context["migration"].script_name == target and started:
            raise runtime_checks.SqlPreflightError("undo callback refused during execution")

    def emit(name, data):
        nonlocal started
        if name == "callback.started" and data["name"] == target:
            started = True

    runtime_checks.register_check("migration.preflight_sql", check)
    with patch(
        "dblift.core.migration.commands.base_command._emit_script_event", side_effect=emit
    ) as events:
        result = instance.undo()
    assert not result.success
    assert "undo callback refused during execution" in result.error_message
    assert [(record.phase, record.status) for record in result.callbacks] == [(event, "FAILED")]
    assert [
        call.args[0]
        for call in events.call_args_list
        if call.args[0] in ("callback.started", "callback.completed", "callback.failed")
    ] == ["callback.started", "callback.failed"]
    with sqlite3.connect(db) as observer:
        assert (
            observer.execute(
                "SELECT name FROM sqlite_master WHERE name IN ('undo_error_ran', 'undo_callback_ran')"
            ).fetchall()
            == []
        )
        history = observer.execute("SELECT script, success FROM dblift_schema_history").fetchall()
        if event == "afterUndo":
            assert history == before_history + [("U1__first.sql", 1)]
            assert observer.execute("SELECT count(*) FROM undone_marker").fetchone() == (0,)
        else:
            assert history == before_history
            assert observer.execute("SELECT count(*) FROM earlier").fetchone() == (0,)
