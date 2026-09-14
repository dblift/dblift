"""Repeatable state lookup indexes preserve behavior while scaling linearly."""

from pathlib import Path

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.rules.migration_rules import MigrationRules
from dblift.core.migration.state.migration_state_manager import MigrationStateManager

pytestmark = [pytest.mark.unit]


class CountingSet(set[str]):
    """Set that records values visited through iteration."""

    def __init__(self, values):
        super().__init__(values)
        self.visits = 0

    def __iter__(self):
        for value in super().__iter__():
            self.visits += 1
            yield value


class CountingDict(dict[str, str]):
    """Dictionary that records key/value pairs visited through ``items``."""

    def __init__(self, values):
        super().__init__(values)
        self.visits = 0

    def items(self):
        for item in super().items():
            self.visits += 1
            yield item


class StubHistoryManager:
    def get_applied_migrations(self):
        return []


class StubScriptManager:
    def __init__(self, scripts):
        self.scripts = scripts

    def load_migration_scripts(self, *_args, **_kwargs):
        return {MigrationType.REPEATABLE: list(self.scripts)}

    @staticmethod
    def calculate_checksum(content):
        return content


def make_repeatable(name: str, checksum: str) -> Migration:
    migration = Migration(script_name=name, content="SELECT 1;", type=MigrationType.REPEATABLE)
    migration.checksum = checksum
    return migration


def make_versioned(name: str, version: str) -> Migration:
    return Migration(
        script_name=name,
        content="SELECT 1;",
        version=version,
        type=MigrationType.SQL,
    )


def make_manager(scripts) -> MigrationStateManager:
    logger = NullLog()
    return MigrationStateManager(
        logger,
        history_manager=StubHistoryManager(),
        script_manager=StubScriptManager(scripts),
        migration_rules=MigrationRules(logger),
    )


def compute_pending(
    manager: MigrationStateManager,
    executed_scripts,
    repeatable_checksums,
):
    return manager._compute_pending_migrations(
        Path("unused"),
        executed_scripts=executed_scripts,
        applied_migrations=[],
        undone_versions=set(),
        repeatable_checksums=repeatable_checksums,
    )


def test_pending_repeatables_visit_executed_names_once():
    scripts = [make_repeatable(f"R__new_{number}.sql", f"new-{number}") for number in range(500)]
    executed_scripts = CountingSet(f"legacy/R__executed_{number}.sql" for number in range(500))

    pending = compute_pending(make_manager(scripts), executed_scripts, {})

    assert [migration.script_name for migration in pending] == [
        f"R__new_{number}.sql" for number in range(500)
    ]
    assert executed_scripts.visits == len(executed_scripts)


def test_checksum_changes_visit_qualified_history_once():
    scripts = [make_repeatable(f"R__view_{number}.sql", f"new-{number}") for number in range(500)]
    previous_checksums = CountingDict(
        {
            f"legacy/{migration.script_name}": (
                migration.checksum if number % 2 == 0 else f"old-{number}"
            )
            for number, migration in enumerate(scripts)
        }
    )

    changes = make_manager(scripts)._determine_checksum_changes(scripts, previous_checksums)

    assert [change.script_name for change in changes] == [
        f"R__view_{number}.sql" for number in range(1, 500, 2)
    ]
    assert [change.previous_checksum for change in changes] == [
        f"old-{number}" for number in range(1, 500, 2)
    ]
    assert previous_checksums.visits == len(previous_checksums)


def test_versioned_only_aggregations_do_not_scan_repeatable_inputs():
    migration = make_versioned("V1__create_table.sql", "1")
    executed_scripts = CountingSet(f"legacy/V{number}__executed.sql" for number in range(500))
    previous_checksums = CountingDict(
        {f"legacy/R__view_{number}.sql": f"old-{number}" for number in range(500)}
    )
    manager = make_manager([migration])

    pending = compute_pending(manager, executed_scripts, previous_checksums)
    changes = manager._determine_checksum_changes([migration], previous_checksums)

    assert pending == [migration]
    assert changes == []
    assert executed_scripts.visits == 0
    assert previous_checksums.visits == 0


@pytest.mark.parametrize(
    ("checksums", "script_name", "expected"),
    [
        (
            {
                "legacy/R__view.sql": "qualified",
                "R__view.sql": "bare",
                "current/R__view.sql": None,
            },
            "current/R__view.sql",
            None,
        ),
        (
            {"legacy/R__view.sql": "qualified", "R__view.sql": 0},
            "current/R__view.sql",
            0,
        ),
        (
            {"first/R__view.sql": "first", "second/R__view.sql": "second"},
            "current/R__view.sql",
            "first",
        ),
        ({"legacy/R__other.sql": "other"}, "R__view.sql", None),
    ],
    ids=("full-key", "bare-key", "first-qualified-key", "missing"),
)
def test_indexed_checksum_lookup_precedence(checksums, script_name, expected):
    basename_checksums = {}
    for name, checksum in checksums.items():
        basename_checksums.setdefault(Path(name).name, checksum)

    assert (
        MigrationStateManager._lookup_checksum(
            checksums,
            script_name,
            basename_checksums=basename_checksums,
        )
        == expected
    )


def test_repeatable_indexes_are_fresh_for_each_aggregation_call():
    migration = make_repeatable("R__view.sql", "current")
    manager = make_manager([migration])

    unchanged = compute_pending(
        manager,
        {"old-directory/R__view.sql"},
        {"old-directory/R__view.sql": "current"},
    )
    changed = compute_pending(
        manager,
        {"new-directory/R__view.sql"},
        {"new-directory/R__view.sql": "previous"},
    )
    checksum_changes = manager._determine_checksum_changes(
        changed,
        {"new-directory/R__view.sql": "previous"},
    )

    assert unchanged == []
    assert changed == [migration]
    assert [
        (change.script_name, change.previous_checksum, change.current_checksum)
        for change in checksum_changes
    ] == [("R__view.sql", "previous", "current")]
