"""Operation-count regressions for migration filename resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.formats import MigrationFormat
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    (
        "filename",
        "expected_bucket",
        "expected_type",
        "expected_version",
        "expected_description",
        "expected_tags",
        "expected_format",
    ),
    [
        (
            "V1_2__create_users[core,ddl].sql",
            MigrationType.SQL,
            MigrationType.SQL,
            "1.2",
            "create_users",
            ["core", "ddl"],
            MigrationFormat.SQL,
        ),
        (
            "V2__python_step.py",
            MigrationType.SQL,
            MigrationType.PYTHON,
            "2",
            "python_step",
            [],
            MigrationFormat.PYTHON,
        ),
        (
            "R__refresh[reporting].sql",
            MigrationType.REPEATABLE,
            MigrationType.REPEATABLE,
            None,
            "refresh",
            ["reporting"],
            MigrationFormat.SQL,
        ),
        (
            "U2__rollback.sql",
            MigrationType.UNDO_SQL,
            MigrationType.UNDO_SQL,
            "2",
            "rollback",
            [],
            MigrationFormat.SQL,
        ),
        (
            "beforeMigrate__check[prod].py",
            MigrationType.CALLBACK,
            MigrationType.CALLBACK,
            None,
            "beforeMigrate__check",
            ["prod"],
            MigrationFormat.PYTHON,
        ),
        (
            "V__.sql",
            MigrationType.SQL,
            MigrationType.SQL,
            None,
            "",
            [],
            MigrationFormat.SQL,
        ),
        (
            "V__.py",
            MigrationType.SQL,
            MigrationType.PYTHON,
            None,
            "",
            [],
            MigrationFormat.PYTHON,
        ),
    ],
)
def test_load_parses_each_filename_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    expected_bucket: MigrationType,
    expected_type: MigrationType,
    expected_version: str | None,
    expected_description: str,
    expected_tags: list[str],
    expected_format: MigrationFormat,
) -> None:
    script = tmp_path / filename
    script.write_text("SELECT 1;", encoding="utf-8")
    manager = MigrationScriptManager(NullLog())
    parse_calls: list[str] = []
    original_parse = MigrationScriptManager.parse_filename

    def counting_parse(
        parser: MigrationScriptManager, script_name: str
    ) -> tuple[MigrationType, str | None, str, list[str]]:
        parse_calls.append(script_name)
        return original_parse(parser, script_name)

    monkeypatch.setattr(MigrationScriptManager, "parse_filename", counting_parse)

    migrations = manager.load_migration_scripts(tmp_path, recursive=False)

    assert parse_calls == [filename]
    assert sum(len(bucket) for bucket in migrations.values()) == 1
    migration = migrations[expected_bucket][0]
    assert migration.path == script
    assert migration.script_name == filename
    assert migration.content == "SELECT 1;"
    assert migration.type is expected_type
    assert migration.version == expected_version
    assert migration.description == expected_description
    assert migration.tags == expected_tags
    assert migration.format is expected_format


@pytest.mark.parametrize(
    ("filename", "use_path", "expected_type"),
    [
        ("B1__baseline.sql", False, MigrationType.UNKNOWN),
        ("V__.sql", True, MigrationType.SQL),
        ("V1__python.py", False, MigrationType.SQL),
        ("V1__python.py", True, MigrationType.PYTHON),
    ],
)
def test_direct_construction_parses_once_with_canonical_type_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    use_path: bool,
    expected_type: MigrationType,
) -> None:
    script = tmp_path / filename
    script.write_text("SELECT 1;", encoding="utf-8")
    from dblift.core.migration.scripting import filename_parser

    parse_calls: list[str] = []
    original_parse = filename_parser.parse_migration_filename

    def counting_parse(script_name: str):
        parse_calls.append(script_name)
        return original_parse(script_name)

    monkeypatch.setattr(filename_parser, "parse_migration_filename", counting_parse)

    migration = (
        Migration(script_path=script)
        if use_path
        else Migration(script_name=filename, content="SELECT 1;")
    )

    assert parse_calls == [filename]
    assert migration.type is expected_type
    assert migration.path == (script if use_path else None)


def test_direct_construction_preserves_truthy_metadata_overrides() -> None:
    migration = Migration(
        script_name="V1__from_name[source].py",
        content="pass",
        version="9",
        description="explicit",
        type=MigrationType.REPEATABLE,
        tags=["manual"],
    )

    assert migration.version == "9"
    assert migration.description == "explicit"
    assert migration.type is MigrationType.REPEATABLE
    assert migration.tags == ["manual"]
    assert migration.format is MigrationFormat.PYTHON
    assert migration.path is None


def test_direct_construction_preserves_falsey_metadata_fallbacks() -> None:
    migration = Migration(
        script_name="V1__from_name[source].sql",
        content="SELECT 1;",
        version="",
        description="",
        tags=[],
    )

    assert migration.version == "1"
    assert migration.description == "from_name"
    assert migration.type is MigrationType.SQL
    assert migration.tags == ["source"]


def test_script_path_preserves_file_metadata_precedence(tmp_path: Path) -> None:
    script = tmp_path / "V1__from_path[source].sql"
    script.write_text("SELECT 1;", encoding="utf-8")

    migration = Migration(
        script_path=script,
        script_name="R__ignored.py",
        content="ignored",
        version="99",
        description="ignored",
        type=MigrationType.REPEATABLE,
        sql_statements=["ignored"],
        tags=["ignored"],
    )

    assert migration.path == script
    assert migration.script_name == "V1__from_path[source].sql"
    assert migration.content == "SELECT 1;"
    assert migration.version == "1"
    assert migration.description == "from_path"
    assert migration.type is MigrationType.SQL
    assert migration.tags == ["source"]
    assert migration._sql_statements is None


def test_get_migration_scripts_does_not_resort_versioned_migrations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MigrationScriptManager(NullLog())
    migrations = {
        MigrationType.SQL: [
            SimpleNamespace(script_name="V1__first.sql", version="1"),
            SimpleNamespace(script_name="V2__second.sql", version="2"),
            SimpleNamespace(script_name="V10__last.sql", version="10"),
        ],
        MigrationType.REPEATABLE: [SimpleNamespace(script_name="R__repeat.sql")],
        MigrationType.UNDO_SQL: [SimpleNamespace(script_name="U10__undo.sql")],
        MigrationType.BASELINE: [SimpleNamespace(script_name="Base Migration")],
        MigrationType.CALLBACK: [SimpleNamespace(script_name="afterMigrate__done.sql")],
    }
    comparisons = 0
    original_compare = manager.compare_versions

    def counting_compare(version1: str | None, version2: str | None) -> int:
        nonlocal comparisons
        comparisons += 1
        return original_compare(version1, version2)

    monkeypatch.setattr(manager, "load_migration_scripts", lambda *args, **kwargs: migrations)
    monkeypatch.setattr(manager, "compare_versions", counting_compare)

    result = manager.get_migration_scripts(Path("unused"))

    assert comparisons == 0
    assert [migration.script_name for migration in result] == [
        "V1__first.sql",
        "V2__second.sql",
        "V10__last.sql",
        "R__repeat.sql",
        "U10__undo.sql",
        "Base Migration",
        "afterMigrate__done.sql",
    ]
