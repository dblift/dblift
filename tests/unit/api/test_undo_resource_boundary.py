"""Migration script resources are resolved by ScriptManager."""

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting import migration_script_manager as manager_module

pytestmark = pytest.mark.unit


def test_manager_reads_and_parses_tagged_resource_once_without_model_services(
    tmp_path, monkeypatch
):
    source = tmp_path / "V1_2__example[tag].sql"
    source.write_text("CREATE TABLE example (id INT);", encoding="utf-8")
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

    manager = manager_module.MigrationScriptManager(NullLog())
    migration = manager.load_migration_script(source)
    assert migration.path == source
    assert migration.content == "CREATE TABLE example (id INT);"
    assert migration.version == "1.2"
    assert migration.tags == ["tag"]
    assert reads == [source]
    assert parses == [source.name]


def test_manager_uses_configured_encoding(tmp_path):
    source = tmp_path / "V1__café.sql"
    sql = "CREATE TABLE example (value TEXT DEFAULT 'café');"
    source.write_bytes(sql.encode("latin-1"))
    manager = manager_module.MigrationScriptManager(NullLog(), script_encoding="latin-1")
    migration = manager.load_migration_script(source)
    assert migration.path == source
    assert migration.content == sql
