"""StateManager owns validation inputs and read-phase freshness."""

from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(tmp_path))
    client.executor.history_manager.create_schema_and_history_table(create_schema=False)
    try:
        yield client
    finally:
        client.close()
        engine.dispose()


def test_snapshot_collects_and_scopes_once(client, tmp_path):
    for version in (1, 2):
        (tmp_path / f"V{version}__init.sql").write_text("SELECT 1;")
    assert client.migrate().success
    manager = client.executor.state_manager
    phase = manager.new_read_snapshot()
    with (
        patch.object(manager.script_manager, "load_migration_scripts", wraps=manager.script_manager.load_migration_scripts) as scripts,
        patch.object(manager.history_manager, "get_applied_migrations", wraps=manager.history_manager.get_applied_migrations) as history,
    ):
        snapshot = manager.build_validation_snapshot(tmp_path, "validate", versions=["2"], strict_mode=True, read_snapshot=phase)
        assert scripts.call_count == history.call_count == 1
        reused = manager.build_validation_snapshot(tmp_path, "migrate", resolved_migrations=list(snapshot.resolved_migrations), applied_migrations=list(snapshot.all_applied_migrations), read_snapshot=phase)
        assert scripts.call_count == history.call_count == 1
    assert [m.version for m in snapshot.resolved_migrations] == ["1", "2"]
    assert [m.version for m in snapshot.selected_migrations] == ["2"]
    assert [m.version for m in snapshot.all_applied_migrations] == ["1", "2"]
    assert [m.version for m in snapshot.scoped_applied_migrations] == ["2"]
    assert snapshot.history_table_exists and snapshot.scripts_directory_exists and snapshot.strict_mode
    assert not reused.strict_mode
    with pytest.raises(FrozenInstanceError):
        snapshot.strict_mode = False


def test_new_snapshot_sees_file_and_history_writes(client, tmp_path):
    manager = client.executor.state_manager
    before = manager.build_validation_snapshot(tmp_path, "validate")
    (tmp_path / "V1__init.sql").write_text("SELECT 1;")
    assert client.migrate().success
    after = manager.build_validation_snapshot(tmp_path, "validate")
    assert before.resolved_migrations == before.all_applied_migrations == ()
    assert len(after.resolved_migrations) == len(after.all_applied_migrations) == 1
    assert not manager.build_validation_snapshot(tmp_path / "missing", "validate").scripts_directory_exists
