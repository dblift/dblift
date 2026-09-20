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


@pytest.mark.parametrize("recursive", [False, True])
def test_batch_discovery_is_manager_owned_and_keeps_loose_candidates(
    tmp_path, monkeypatch, recursive
):
    import inspect

    sql = tmp_path / "V2__table.sql"
    sql.write_text("CREATE TABLE example (id INT);", encoding="utf-8")
    python = tmp_path / "V1__python.py"
    python.write_text("pass", encoding="utf-8")
    invalid = tmp_path / "Vbad.sql"
    invalid.write_text("not SQL", encoding="utf-8")
    (tmp_path / "V9__notes.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "R__repeat.sql").write_text("ignored", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    child = nested / "V3__child.sql"
    child.write_text("CREATE TABLE child (id INT);", encoding="utf-8")
    client = SimpleNamespace(dialect="sqlite", logger=NullLog(), config=None, events=MagicMock())
    real_glob = Path.glob
    discovery = []

    def manager_glob(path, pattern):
        assert inspect.currentframe().f_back.f_globals["__name__"] == manager_module.__name__
        discovery.append(pattern)
        # Deliberately non-version order: the API preserves discovery order.
        return iter(
            [sql, python, invalid, tmp_path / "V9__notes.txt"] + ([child] if recursive else [])
        )

    monkeypatch.setattr(Path, "glob", manager_glob)
    results = generate_undo_scripts_operation(client, migrations_dir=tmp_path, recursive=recursive)
    monkeypatch.setattr(Path, "glob", real_glob)
    assert discovery == ["**/V*" if recursive else "V*"]
    assert [result.migration_path for result in results] == [
        str(sql),
        str(python),
        str(invalid),
    ] + ([str(child)] if recursive else [])
    assert [result.success for result in results] == [True, False, False] + (
        [True] if recursive else []
    )
    assert "supports SQL migrations" in results[1].error_message
    assert "File is not a versioned migration: Vbad.sql." in results[2].error_message


def test_undo_api_reuses_configured_manager_for_encoding(tmp_path):
    source = tmp_path / "V1__café.sql"
    source.write_bytes("CREATE TABLE example (value TEXT DEFAULT 'café');".encode("latin-1"))
    manager = manager_module.MigrationScriptManager(NullLog(), script_encoding="latin-1")
    client = SimpleNamespace(
        dialect="sqlite",
        logger=NullLog(),
        config=None,
        events=MagicMock(),
        executor=SimpleNamespace(script_manager=manager),
    )
    result = generate_undo_script_operation(client, migration_path=source)
    assert result.success, result.error_message
    assert Path(result.undo_script_path).name == "U1__café.sql"


@pytest.mark.parametrize("entrypoint", ["api", "generator"])
def test_missing_file_check_is_manager_owned_with_legacy_message(tmp_path, monkeypatch, entrypoint):
    import inspect

    from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator

    source = tmp_path / "not_a_migration.sql"
    real_exists = Path.exists

    def manager_exists(path):
        if path == source:
            assert inspect.currentframe().f_back.f_globals["__name__"] == manager_module.__name__
        return real_exists(path)

    monkeypatch.setattr(Path, "exists", manager_exists)
    with pytest.raises(FileNotFoundError, match=f"^Migration file not found: {source}$"):
        if entrypoint == "api":
            client = SimpleNamespace(
                dialect="sqlite", logger=NullLog(), config=None, events=MagicMock()
            )
            generate_undo_script_operation(client, migration_path=source)
        else:
            UndoScriptGenerator("sqlite", logger=NullLog()).generate_undo_script(source)


def test_invalid_undo_candidate_is_rejected_before_reading(tmp_path):
    source = tmp_path / "Vbad.sql"
    source.write_bytes(b"\xff")
    manager = manager_module.MigrationScriptManager(NullLog())
    with pytest.raises(ValueError, match="File is not a versioned migration: Vbad.sql"):
        manager.load_migration_script(source, require_versioned=True)
