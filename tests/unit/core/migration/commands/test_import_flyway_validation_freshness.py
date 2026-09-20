"""Flyway compatibility snapshots refresh at import's existing write boundaries."""

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.migration.commands.base_command import BaseCommand


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(tmp_path))
    client.provider.connect()
    client.provider.execute_query("""
        CREATE TABLE flyway_schema_history (
            installed_rank INTEGER, version TEXT, description TEXT, type TEXT,
            script TEXT, installed_by TEXT, installed_on TEXT,
            checksum INTEGER, execution_time INTEGER, success INTEGER
        )
    """)
    try:
        yield client
    finally:
        client.close()
        engine.dispose()


def _seed_row(client):
    client.provider.execute_query("""
        INSERT INTO flyway_schema_history VALUES
        (1, '1', 'init', 'SQL', 'V1__init.sql', 'tester',
         '2026-01-01 00:00:00', 123, 0, 1)
    """)
    client.provider.commit_transaction()


@pytest.mark.parametrize("rows", [0, 1])
@pytest.mark.parametrize("target_exists", [False, True])
def test_check_import_check_refreshes_history_creation_and_rows(client, rows, target_exists):
    if rows:
        _seed_row(client)
    if target_exists:
        client.executor.history_manager.create_schema_and_history_table(create_schema=False)
    validator = client.executor.validator
    manager = client.executor.state_manager
    before = manager.get_flyway_compatibility_snapshot()
    assert validator.validate_flyway_compatibility()["Dblift_exists"] is target_exists

    result = client.import_flyway()

    assert result.success, result.error_message
    after = validator.validate_flyway_compatibility()
    assert after["Dblift_exists"] is True
    assert after["compatible"] is True
    assert after["flyway_count"] == after["Dblift_count"] == rows
    assert manager.get_flyway_compatibility_snapshot() is not before


def test_import_write_refreshes_a_snapshot_collected_after_table_creation(client):
    _seed_row(client)
    manager = client.executor.state_manager
    snapshots = []
    original_header = BaseCommand._log_command_header_update

    def inspect_before_import(command, *args, **kwargs):
        original_header(command, *args, **kwargs)
        snapshots.append(manager.get_flyway_compatibility_snapshot())

    with patch.object(BaseCommand, "_log_command_header_update", inspect_before_import):
        result = client.import_flyway()

    assert result.success, result.error_message
    assert snapshots[0].dblift_migrations == ()
    after = client.executor.validator.validate_flyway_compatibility()
    assert after["compatible"] is True
    assert after["Dblift_count"] == 1
    assert manager.get_flyway_compatibility_snapshot() is not snapshots[0]
