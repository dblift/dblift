from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.migration import AppliedMigration, MigrationResource, ResolvedMigration
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.migration.migration import Migration, MigrationType, dict_to_migration
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.state.migration_state_manager import MigrationStateManager


@pytest.mark.unit
def test_history_row_becomes_applied_migration_before_legacy_migration():
    row = {
        "SCRIPT": "V1__create_users.sql",
        "VERSION": "1",
        "DESCRIPTION": "create_users",
        "TYPE": "SQL",
        "CHECKSUM": 4294967295,
        "SUCCESS": True,
        "INSTALLED_RANK": 7,
    }

    applied = AppliedMigration.from_history_row(row)
    migration = applied.to_migration()

    assert applied.script_name == "V1__create_users.sql"
    assert applied.checksum == -1
    assert migration.applied_migration is applied
    assert migration.checksum == -1
    assert migration.installed_rank == 7


@pytest.mark.unit
def test_dict_to_migration_uses_applied_record_adapter():
    migration = dict_to_migration(
        {
            "script": "V1__create_users.sql",
            "version": "1",
            "description": "create_users",
            "type": "SQL",
            "success": True,
        }
    )

    assert migration.script_name == "V1__create_users.sql"
    assert migration.type == MigrationType.SQL
    assert migration.applied_migration.script_name == "V1__create_users.sql"


@pytest.mark.unit
def test_script_manager_can_expose_resources_and_resolved_migrations(tmp_path):
    script = tmp_path / "V1__create_users.sql"
    script.write_text("create table users(id int);", encoding="utf-8")
    manager = MigrationScriptManager(MagicMock())

    resources = manager.get_migration_resources(tmp_path)
    resolved = manager.get_resolved_migrations(tmp_path)

    assert resources == [
        MigrationResource(
            path=script,
            script_name="V1__create_users.sql",
            content="create table users(id int);",
        )
    ]
    assert len(resolved) == 1
    assert isinstance(resolved[0], ResolvedMigration)
    assert resolved[0].resource is not None
    assert resolved[0].to_migration().script_name == "V1__create_users.sql"


@pytest.mark.unit
def test_history_manager_can_return_applied_records():
    provider = MagicMock()
    provider.get_normalized_object_name.side_effect = lambda name: name
    provider.get_applied_migrations.return_value = [
        {
            "script": "V1__create_users.sql",
            "version": "1",
            "description": "create_users",
            "type": "SQL",
        }
    ]
    manager = MigrationHistoryManager(provider, "public", "tester", MagicMock())

    records = manager.get_applied_migration_records()
    legacy = manager.get_applied_migrations()

    assert records[0].script_name == "V1__create_users.sql"
    assert legacy[0].applied_migration.script_name == "V1__create_users.sql"


@pytest.mark.unit
def test_state_layer_marks_history_rows_distinct_from_resolved_scripts():
    manager = MigrationStateManager.__new__(MigrationStateManager)
    applied = Migration(
        script_name="V1__create_users.sql",
        content="",
        version="1",
        description="create_users",
        type=MigrationType.SQL,
    )
    pending = Migration(
        script_name="V2__create_orders.sql",
        content="",
        version="2",
        description="create_orders",
        type=MigrationType.SQL,
    )

    manager._mark_resolved_status([applied], [pending], [pending], scripts_available=True)

    assert applied.resolved is False
    assert pending.resolved is True


@pytest.mark.unit
@pytest.mark.parametrize("injected_manager", [False, True])
def test_history_materialization_uses_script_manager_metadata(monkeypatch, injected_manager):
    provider = MagicMock()
    provider.get_applied_migrations.return_value = [
        {
            "script": "V1_2__from_name[tag].sql",
            "version": None,
            "description": "",
            "type": "SQL",
            "checksum": 12,
            "success": True,
        },
        {
            "script": "V3__from_name[tag].sql",
            "version": "99",
            "description": "history description",
            "type": "DELETE",
            "tags": ["stored"],
            "installed_rank": 7,
        },
        {"script": "Base Migration", "version": "0", "description": "baseline", "type": "BASELINE"},
    ]
    manager = MigrationHistoryManager(provider, "public", "tester", MagicMock())
    if injected_manager:
        manager.script_manager = MigrationScriptManager(MagicMock())
    parse = MigrationScriptManager.parse_filename
    names = []

    def tracked_parse(script_manager, name):
        names.append(name)
        return parse(script_manager, name)

    def forbidden(*args, **kwargs):
        raise AssertionError("history model must receive resolved filename metadata")

    monkeypatch.setattr(MigrationScriptManager, "parse_filename", tracked_parse)
    monkeypatch.setattr(Migration, "_parse_filename", forbidden)
    migrations = manager.get_applied_migrations()
    assert [(m.version, m.description, m.type, m.tags) for m in migrations] == [
        ("1.2", "from_name", MigrationType.SQL, ["tag"]),
        ("99", "history description", MigrationType.DELETE, ["tag"]),
        ("0", "baseline", MigrationType.BASELINE, []),
    ]
    assert migrations[0].checksum == 12
    assert migrations[0].success is True
    assert migrations[1].installed_rank == 7
    assert names == ["V1_2__from_name[tag].sql", "V3__from_name[tag].sql", "Base Migration"]
