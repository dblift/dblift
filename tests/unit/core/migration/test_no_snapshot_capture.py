"""OSS migration core must not own snapshot capture wiring."""

from __future__ import annotations

import inspect

import pytest

from dblift.api.events import EventEmitter, EventType
from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.migration.executor.migration_executor import MigrationExecutor

pytestmark = [pytest.mark.unit]


def test_executor_and_migrate_command_do_not_wire_snapshot_capture() -> None:
    assert not hasattr(MigrationExecutor, "_capture_snapshot")
    assert "snapshot_service" not in inspect.signature(MigrateCommand).parameters


def test_events_keep_migration_lifecycle_without_snapshot_emits() -> None:
    seen: list[str] = []
    emitter = EventEmitter()

    emitter.on("migration.completed", lambda event: seen.append(event.event_type.value))
    emitter.emit(EventType.MIGRATION_COMPLETED, {"operation": "migrate"})

    assert seen == ["migration.completed"]
    assert EventType.SNAPSHOT_COMPLETED.value == "snapshot.completed"
