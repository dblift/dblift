"""Canonical filename inference and resource ownership regressions."""

import importlib
import subprocess
import sys
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.migration import Migration, MigrationType, dict_to_migration
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "name,kind,version,description,tags",
    [
        ("V1_2__create[a, b].sql", "SQL", "1.2", "create", ["a", "b"]),
        ("V1_2A__create.py", "SQL", "1_2A", "create", []),
        ("U2__undo.sql", "UNDO_SQL", "2", "undo", []),
        ("R__refresh.sql", "REPEATABLE", None, "refresh", []),
        (
            "afterMigrate[prod]Error__notify.sql",
            "CALLBACK",
            None,
            "afterMigrateError__notify",
            ["prod"],
        ),
        ("AFTERMIGRATE__notify.SQL", "CALLBACK", None, "AFTERMIGRATE__notify.SQL", []),
        ("V__.sql", "SQL", None, "", []),
        ("B1__baseline.sql", "UNKNOWN", None, "B1__baseline", []),
        ("v1__create.sql", "UNKNOWN", None, "v1__create", []),
        ("u1__undo.sql", "UNKNOWN", None, "u1__undo", []),
        ("r__refresh.sql", "UNKNOWN", None, "r__refresh", []),
        ("V1_create.sql", "UNKNOWN", None, "V1_create", []),
        ("V1__create.SQL", "UNKNOWN", None, "V1__create.SQL", []),
        ("V1__create.txt", "UNKNOWN", None, "V1__create.txt", []),
        ("afterMigrate__notify.txt", "UNKNOWN", None, "afterMigrate__notify.txt", []),
        ("afterMigrateError_notify.sql", "UNKNOWN", None, "afterMigrateError_notify", []),
        ("VA__create.sql", "UNKNOWN", None, "VA__create", []),
    ],
)
def test_implicit_model_and_manager_share_the_discovery_grammar(
    name, kind, version, description, tags
):
    expected = (MigrationType[kind], version, description, tags)
    assert MigrationScriptManager(NullLog()).parse_filename(name) == expected
    migration = Migration(script_name=name)
    assert (migration.type, migration.version, migration.description, migration.tags) == expected


def test_parser_result_is_immutable_and_compatibility_tags_are_fresh():
    parser = importlib.import_module("dblift.core.migration.scripting.filename_parser")
    metadata = parser.parse_migration_filename("afterMigrate[prod]Error__notify.sql")
    assert metadata.callback_event == "afterMigrateError"
    assert metadata.tags == ("prod",)
    with pytest.raises(FrozenInstanceError):
        metadata.version = "2"
    manager = MigrationScriptManager(NullLog())
    manager.parse_filename("V1__x[tag].sql")[3].append("other")
    assert manager.parse_filename("V1__x[tag].sql")[3] == ["tag"]


def test_type_reexports_have_identical_identity_in_fresh_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from dblift.core.migration import MigrationType as a, VERSIONED_SCRIPT_TYPES as x; "
            "from dblift.core.migration.migration import MigrationType as b, VERSIONED_SCRIPT_TYPES as y; "
            "from dblift.core.migration.migration_types import MigrationType as c, VERSIONED_SCRIPT_TYPES as z; "
            "assert a is b is c; assert x is y is z",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_discovery_reads_and_parses_once_without_model_services(tmp_path, monkeypatch):
    script = tmp_path / "V1__café[tag].sql"
    script.write_bytes("SELECT 'café';".encode("latin-1"))
    manager = MigrationScriptManager(NullLog(), script_encoding="latin-1")
    from dblift.core.migration.scripting import migration_script_manager as module

    reads, parses = [], []
    read, parse = module.read_migration_text, manager.parse_filename

    def count_read(path, **kwargs):
        reads.append(path)
        return read(path, **kwargs)

    def count_parse(name):
        parses.append(name)
        return parse(name)

    def forbidden(*args, **kwargs):
        raise AssertionError("Migration must only receive resolved data")

    monkeypatch.setattr(module, "read_migration_text", count_read)
    monkeypatch.setattr(manager, "parse_filename", count_parse)
    monkeypatch.setattr(Migration, "_parse_filename", forbidden)
    monkeypatch.setattr(MigrationScriptManager, "__init__", forbidden)
    monkeypatch.setattr("dblift.core.migration.migration.read_migration_text", forbidden)
    migrations = manager.get_migration_scripts(tmp_path)
    assert len(migrations) == 1
    assert migrations[0].content == "SELECT 'café';"
    assert migrations[0].tags == ["tag"]
    assert migrations[0].path == script
    assert reads == [script]
    assert parses == [script.name]


def test_data_and_history_construction_never_construct_a_manager(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("model constructed a manager")

    monkeypatch.setattr(MigrationScriptManager, "__init__", forbidden)
    assert Migration(script_name="V1__x[tag].sql").tags == ["tag"]
    assert dict_to_migration({"script": "V1__x[tag].sql", "type": "SQL"}).tags == ["tag"]


def test_undo_resource_input_uses_script_manager(tmp_path, monkeypatch):
    script = tmp_path / "V1__create.sql"
    script.write_text("CREATE TABLE example (id INT);", encoding="utf-8")
    generator = UndoScriptGenerator("sqlite", logger=NullLog())
    monkeypatch.setattr(
        "dblift.core.migration.migration.read_migration_text",
        MagicMock(side_effect=AssertionError("model read")),
    )
    output = generator.generate_undo_script(script)
    assert "DROP TABLE" in output.read_text()
