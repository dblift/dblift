"""Filesystem discovery work is reused within one load without changing routing."""

from collections import Counter
from pathlib import Path
from unittest.mock import Mock

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.encoding import MigrationEncodingError
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("file_count", [10, 100])
@pytest.mark.parametrize("recursive", [False, True])
def test_load_checks_and_resolves_each_file_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, file_count: int, recursive: bool
) -> None:
    scripts = [tmp_path / f"V{version}__step.sql" for version in range(1, file_count + 1)]
    for version, script in enumerate(scripts, 1):
        script.write_text(f"SELECT {version};", encoding="utf-8")
    script_set = set(scripts)
    calls: Counter[tuple[str, Path]] = Counter()

    def count_method(name, original):
        def counted(path, *args, **kwargs):
            if path in script_set:
                calls[name, path] += 1
            return original(path, *args, **kwargs)

        return counted

    for name in ("is_file", "is_symlink", "resolve"):
        monkeypatch.setattr(Path, name, count_method(name, getattr(Path, name)))
    manager = MigrationScriptManager(NullLog())
    parse_filename = Mock(wraps=manager.parse_filename)
    monkeypatch.setattr(manager, "parse_filename", parse_filename)

    migrations = manager.load_migration_scripts(tmp_path, recursive=recursive)

    assert [migration.path for migration in migrations[MigrationType.SQL]] == scripts
    assert [migration.content for migration in migrations[MigrationType.SQL]] == [
        f"SELECT {version};" for version in range(1, file_count + 1)
    ]
    assert sum(map(len, migrations.values())) == file_count
    assert parse_filename.call_count == file_count
    for name in ("is_file", "is_symlink", "resolve"):
        assert [calls[name, script] for script in scripts] == [1] * file_count


@pytest.mark.parametrize("recursive", [False, True])
@pytest.mark.parametrize("reverse_additional", [False, True])
def test_relative_overlapping_directories_keep_discovery_references_and_loaded_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recursive: bool, reverse_additional: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    primary = Path("primary")
    extra = Path("extra")
    nested = extra / "nested"
    primary.mkdir()
    nested.mkdir(parents=True)
    scripts = [primary / "V1__primary.sql", extra / "V2__extra.sql", nested / "V3__nested.sql"]
    for version, script in enumerate(scripts, 1):
        script.write_text(f"SELECT {version};", encoding="utf-8")
    additional = [nested, extra] if reverse_additional else [extra, nested]
    # Repeat a configured root with a different representation; it must only scan once.
    additional.append(extra.absolute())
    manager = MigrationScriptManager(NullLog())

    references = manager.get_all_scripts(primary, recursive=recursive, additional_dirs=additional)
    expected = ["V1__primary.sql", "extra/V2__extra.sql", "extra/nested/V3__nested.sql"]
    if recursive:
        expected.append("extra/nested/V3__nested.sql")
    assert Counter(references) == Counter(expected)

    migrations = manager.load_migration_scripts(
        primary, recursive=recursive, additional_dirs=additional
    )

    assert [migration.path for migration in migrations[MigrationType.SQL]] == scripts
    assert [migration.content for migration in migrations[MigrationType.SQL]] == [
        "SELECT 1;",
        "SELECT 2;",
        "SELECT 3;",
    ]
    assert sum(map(len, migrations.values())) == 3


@pytest.mark.parametrize("additional_file_exists", [False, True])
def test_ambiguous_primary_reference_preserves_additional_directory_routing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, additional_file_exists: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    primary = Path("primary")
    extra = Path("extra")
    (primary / extra).mkdir(parents=True)
    extra.mkdir()
    filename = "V1__step.sql"
    (primary / extra / filename).write_text("SELECT 1;", encoding="utf-8")
    if additional_file_exists:
        (extra / filename).write_text("SELECT 2;", encoding="utf-8")
    manager = MigrationScriptManager(NullLog())
    references = manager.get_all_scripts(primary, additional_dirs=[extra])
    assert references == [f"extra/{filename}"] * (2 if additional_file_exists else 1)

    parse_filename = Mock(wraps=manager.parse_filename)
    monkeypatch.setattr(manager, "parse_filename", parse_filename)
    # Existing string references route this primary nested name through the additional root.
    if not additional_file_exists:
        with pytest.raises(MigrationEncodingError, match="Could not read migration script"):
            manager.load_migration_scripts(primary, additional_dirs=[extra])
    else:
        migrations = manager.load_migration_scripts(primary, additional_dirs=[extra])
        assert sum(map(len, migrations.values())) == 1
        migration = migrations[MigrationType.SQL][0]
        assert migration.path == extra / filename
        assert migration.content == "SELECT 2;"
    assert parse_filename.call_count == len(references)


def test_load_keeps_symlink_and_resolved_path_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    safe = primary / "V1__safe.sql"
    safe.write_text("SELECT 1;", encoding="utf-8")
    outside = tmp_path / "V2__outside.sql"
    outside.write_text("SELECT 2;", encoding="utf-8")
    symlink = primary / "V3__symlink.sql"
    symlink.symlink_to(safe)
    inaccessible = primary / "V4__inaccessible.sql"
    inaccessible.write_text("SELECT 4;", encoding="utf-8")
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == inaccessible:
            raise OSError("unreachable")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(Path, "glob", lambda *_args: iter([safe, outside, symlink, inaccessible]))
    logger = Mock()
    migrations = MigrationScriptManager(logger).load_migration_scripts(primary, recursive=False)

    assert [migration.path for migration in migrations[MigrationType.SQL]] == [safe]
    assert sum(map(len, migrations.values())) == 1
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert any("outside configured migrations directory" in warning for warning in warnings)
    assert any("path inaccessible or invalid: unreachable" in warning for warning in warnings)


@pytest.mark.parametrize("failure", ["missing", "unreadable", "encoding"])
def test_read_errors_after_discovery_still_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    script = tmp_path / "V1__step.sql"
    script.write_text("SELECT 1;", encoding="utf-8")
    manager = MigrationScriptManager(NullLog())
    discover = manager.get_all_scripts

    def discover_then_fail(*args, **kwargs):
        references = discover(*args, **kwargs)
        if failure == "missing":
            script.unlink()
        elif failure == "encoding":
            script.write_bytes(b"SELECT '\xff';")
        else:
            original_read = Path.read_text

            def read(path, *args, **kwargs):
                if path == script:
                    raise PermissionError("permission denied")
                return original_read(path, *args, **kwargs)

            monkeypatch.setattr(Path, "read_text", read)
        return references

    monkeypatch.setattr(manager, "get_all_scripts", discover_then_fail)

    with pytest.raises(MigrationEncodingError, match="Could not (read|decode) migration script"):
        manager.load_migration_scripts(tmp_path)


def test_load_does_not_retain_discovery_between_calls(tmp_path: Path) -> None:
    first = tmp_path / "V1__first.sql"
    first.write_text("SELECT 1;", encoding="utf-8")
    manager = MigrationScriptManager(NullLog())
    assert manager.load_migration_scripts(tmp_path)[MigrationType.SQL][0].content == "SELECT 1;"
    first.unlink()
    second = tmp_path / "V2__second.sql"
    second.write_text("SELECT 2;", encoding="utf-8")

    migrations = manager.load_migration_scripts(tmp_path)

    assert [migration.path for migration in migrations[MigrationType.SQL]] == [second]
    assert migrations[MigrationType.SQL][0].content == "SELECT 2;"


def test_legacy_discovery_override_can_return_references_without_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "V1__step.sql"
    script.write_text("SELECT 1;", encoding="utf-8")
    manager = MigrationScriptManager(NullLog())
    monkeypatch.setattr(manager, "get_all_scripts", lambda *args, **kwargs: [script.name])

    migrations = manager.load_migration_scripts(tmp_path)

    assert [migration.path for migration in migrations[MigrationType.SQL]] == [script]
    assert migrations[MigrationType.SQL][0].content == "SELECT 1;"
