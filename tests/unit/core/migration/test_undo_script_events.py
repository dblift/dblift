"""Undo must emit migration.script.* events, like migrate."""

from pathlib import Path

from sqlalchemy import create_engine

from dblift.api import DBLiftClient


def _capture(client) -> list[str]:
    seen: list[str] = []
    for ev in ("migration.script.started", "migration.script.completed", "migration.script.failed"):
        client.events.on(ev, lambda e, _ev=ev: seen.append(_ev))
    return seen


def test_undo_emits_script_events(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    (migrations / "U1_0_0__t.sql").write_text("DROP TABLE t;")

    engine = create_engine(f"sqlite:///{tmp_path/'db.sqlite'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))
    client.migrate()

    seen = _capture(client)
    client.undo()

    assert "migration.script.started" in seen
    assert "migration.script.completed" in seen
