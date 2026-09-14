"""Public undo generation resolves source resources through ScriptManager."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.api._client_operations import (
    generate_undo_script_operation,
    generate_undo_scripts_operation,
)
from dblift.core.logger import NullLog
from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting import migration_script_manager as manager_module

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("batch", [False, True])
def test_undo_api_reads_and_parses_each_resource_once_without_model_services(
    tmp_path, monkeypatch, batch
):
    source = tmp_path / "V1_2__example[tag].sql"
    source.write_text("CREATE TABLE example (id INT);", encoding="utf-8")
    client = SimpleNamespace(dialect="sqlite", logger=NullLog(), config=None, events=MagicMock())
    reads, parses = [], []
    read = manager_module.read_migration_text
    parse = manager_module.MigrationScriptManager.parse_filename

    def count_read(path, **kwargs):
        reads.append(path)
        return read(path, **kwargs)

    def count_parse(manager, name):
        parses.append(name)
        return parse(manager, name)

    def forbidden(*args, **kwargs):
        raise AssertionError("model must receive resolved data")

    monkeypatch.setattr(manager_module, "read_migration_text", count_read)
    monkeypatch.setattr(manager_module.MigrationScriptManager, "parse_filename", count_parse)
    monkeypatch.setattr("dblift.core.migration.migration.read_migration_text", forbidden)
    monkeypatch.setattr(Migration, "_parse_filename", forbidden)
    if batch:
        results = generate_undo_scripts_operation(client, migration_paths=[source])
        assert len(results) == 1
        result = results[0]
    else:
        result = generate_undo_script_operation(client, migration_path=source)
    assert result.success, result.error_message
    assert result.migration_path == str(source)
    output = Path(result.undo_script_path)
    assert output.name == "U1_2__example.sql"
    assert "DROP TABLE" in output.read_text()
    assert reads == [source]
    assert parses == [source.name]
