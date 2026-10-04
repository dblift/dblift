"""Run in a fresh environment with the candidate and fixture wheels installed."""

import importlib.util
import sqlite3
import sys
from importlib import metadata
from pathlib import Path

import dblift
from dblift.api.client import DBLiftClient
from dblift.api.events import EventType
from dblift.config import DbliftConfig
from dblift.extensions.logging import NullLog
from dblift.extensions.providers import ProviderRegistry


def main() -> None:
    phase = sys.argv[1]
    plugin = ProviderRegistry.get_plugin_info("fixture_sqlite")
    if phase == "before":
        assert plugin is None, "fixture provider appeared before installation"
        assert not any(
            ep.name == "fixture_sqlite" for ep in metadata.entry_points(group="dblift.providers")
        )
        return

    assert plugin is not None, "installed fixture provider was not discovered"
    import fixture_listener
    import fixture_sqlite
    from fixture_listener import EVENTS as listener_events
    from fixture_sqlite import EVENTS as provider_events
    from fixture_sqlite import PLUGIN

    for module in (dblift, fixture_sqlite, fixture_listener):
        assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    assert all(
        importlib.util.find_spec("".join(parts)) is None
        for parts in (("dblift", "_pro"), ("dblift", "_enterprise"))
    )

    assert plugin is PLUGIN
    assert plugin.provider_class is PLUGIN.provider_class
    assert ProviderRegistry.get_plugin_info("sqlite") is not None
    assert {ep.name for ep in metadata.entry_points(group="dblift.event_listeners")} >= {
        "fixture_sqlite_events",
        "fixture_listener_events",
    }

    work = Path.cwd()
    migrations = work / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_items.sql").write_text(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT);\n"
        "INSERT INTO items (id, value) VALUES (1, 'installed');\n",
        encoding="utf-8",
    )
    (migrations / "U1__create_items.sql").write_text("DROP TABLE items;\n", encoding="utf-8")
    database = work / "extension.sqlite"
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "fixture_sqlite", "url": f"sqlite:///{database}"},
            "migrations": {"directory": str(migrations)},
        }
    )
    log = NullLog()
    first = DBLiftClient(
        ProviderRegistry.create_provider(config, log=log), migrations, config=config, logger=log
    )
    try:
        result = first.migrate()
        assert result.success, result.error_message
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT value FROM items WHERE id = 1").fetchone() == (
                "installed",
            )
        assert [event.event_type for event in provider_events] == [EventType.MIGRATION_COMPLETED]
        assert [event.event_type for event in listener_events] == [EventType.MIGRATION_COMPLETED]
        assert len(first.info().migrations_applied) == 1
        assert first.validate().success

        (migrations / "V2__invalid.sql").write_text(
            "INSERT INTO missing_table VALUES (1);\n", encoding="utf-8"
        )
        failed = first.migrate()
        assert not failed.success
        assert [event.event_type for event in provider_events] == [
            EventType.MIGRATION_COMPLETED,
            EventType.MIGRATION_FAILED,
        ]
        assert [event.event_type for event in listener_events] == [
            EventType.MIGRATION_COMPLETED,
            EventType.MIGRATION_FAILED,
        ]
        (migrations / "V2__invalid.sql").unlink()
        undone = first.undo(target_version="0.0.0")
        assert undone.success, undone.error_message
        with sqlite3.connect(database) as connection:
            assert (
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='items'"
                ).fetchone()
                is None
            )
    finally:
        first.close()
    assert not first.provider.is_connected()

    (migrations / "V2__invalid.sql").write_text(
        "INSERT INTO missing_table VALUES (1);\n", encoding="utf-8"
    )
    second = DBLiftClient(
        ProviderRegistry.create_provider(config, log=log), migrations, config=config, logger=log
    )
    try:
        # This client must receive exactly one event per registrar after the first closes.
        result = second.migrate(target_version="1")
        assert result.success, result.error_message
        failed = second.migrate()
        assert not failed.success
        assert [event.event_type for event in provider_events] == [
            EventType.MIGRATION_COMPLETED,
            EventType.MIGRATION_FAILED,
            EventType.MIGRATION_COMPLETED,
            EventType.MIGRATION_FAILED,
        ]
        assert [event.event_type for event in listener_events] == [
            EventType.MIGRATION_COMPLETED,
            EventType.MIGRATION_FAILED,
            EventType.MIGRATION_COMPLETED,
            EventType.MIGRATION_FAILED,
        ]
    finally:
        second.close()
    assert not second.provider.is_connected()


if __name__ == "__main__":
    main()
