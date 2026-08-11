"""Regression coverage for the emit sites wired up alongside the previously
dead CLEAN_OBJECT_REMOVED, UNDO_SCRIPT_ROLLED_BACK and CALLBACK_* events."""

from pathlib import Path

from sqlalchemy import create_engine

from api import DBLiftClient


def _client(tmp_path: Path, migrations_dir: Path) -> DBLiftClient:
    engine = create_engine(f"sqlite:///{tmp_path/'db.sqlite'}")
    return DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations_dir))


def _capture(client, *events) -> list:
    seen = []
    for ev in events:
        client.events.on(ev, lambda e, _ev=ev: seen.append((_ev, e)))
    return seen


def test_clean_emits_object_removed_per_dropped_object(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")

    client = _client(tmp_path, migrations)
    client.migrate()

    seen = _capture(client, "clean.object.removed")
    client.clean(clean_enabled=True)

    assert seen, "clean.object.removed never fired"
    names = {e.name for _, e in seen}
    assert "dblift_schema_history" in names
    types = {e.type for _, e in seen}
    assert types == {"table"}


def test_undo_emits_rolled_back_with_script_name(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    (migrations / "U1_0_0__t.sql").write_text("DROP TABLE t;")

    client = _client(tmp_path, migrations)
    client.migrate()

    seen = _capture(client, "undo.script.rolled_back")
    client.undo()

    assert len(seen) == 1
    _, event = seen[0]
    assert event.script == "U1_0_0__t.sql"
    assert event.version == "1.0.0"


def test_migrate_callbacks_emit_lifecycle_and_per_script_events(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    (migrations / "beforeMigrate__setup.sql").write_text("SELECT 1;")

    client = _client(tmp_path, migrations)
    seen = _capture(
        client, "callback.before_migrate", "callback.started", "callback.completed"
    )
    client.migrate()

    fired = [ev for ev, _ in seen]
    assert "callback.before_migrate" in fired
    assert "callback.started" in fired
    assert "callback.completed" in fired
    started = next(e for ev, e in seen if ev == "callback.started")
    assert started.name == "beforeMigrate__setup.sql"


def test_validate_callbacks_emit_before_and_after(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    (migrations / "beforeValidate__check.sql").write_text("SELECT 1;")
    (migrations / "afterValidate__check.sql").write_text("SELECT 1;")

    client = _client(tmp_path, migrations)
    client.migrate()

    seen = _capture(client, "callback.before_validate", "callback.after_validate")
    client.validate()

    fired = [ev for ev, _ in seen]
    assert "callback.before_validate" in fired
    assert "callback.after_validate" in fired
