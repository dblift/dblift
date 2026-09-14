"""Checksum validation reuses resolved files and scans history a bounded number of times."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.sql_validator.migration_validator import MigrationValidator, ValidationResult


class CountingList(list):
    def __init__(self, rows):
        super().__init__(rows)
        self.visits = 0

    def __iter__(self):
        for row in super().__iter__():
            self.visits += 1
            yield row

    def __reversed__(self):
        for row in super().__reversed__():
            self.visits += 1
            yield row


def validator():
    instance = MigrationValidator.__new__(MigrationValidator)
    instance.script_manager = MigrationScriptManager(NullLog())
    instance.log = NullLog()
    return instance


def history(script, *, checksum=None, success=True, type=None, rank=1, name=None):
    row = Migration(script_name=name or script.script_name, type=type or script.type)
    row.checksum = script.checksum if checksum is None else checksum
    row.success = success
    row.installed_rank = rank
    row.execution_time = 10
    return row


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize(
    "encoding,detect", [("utf-8", False), ("latin-1", False), ("utf-16", True)]
)
def test_resolved_checksums_do_not_reread_files(tmp_path, changed, encoding, detect):
    path = tmp_path / "V1__example.sql"
    path.write_text("SELECT 1; -- café\n", encoding=encoding)
    script = Migration(path, script_encoding=encoding, detect_encoding=detect)
    rows = [history(script)]
    if changed:
        path.write_text("SELECT 2; -- café\n", encoding=encoding)
        script = Migration(path, script_encoding=encoding, detect_encoding=detect)
    result, issues = ValidationResult(), []
    instance = validator()
    instance.script_manager.script_encoding = encoding
    instance.script_manager.detect_encoding = detect
    with patch("pathlib.Path.read_text", wraps=path.read_text) as reads:
        instance._validate_checksums([script], rows, result, issues)
    assert result.failed_scripts == ([script.script_name] if changed else [])
    assert any("has been modified" in issue for issue in issues) == changed
    assert reads.call_count == 0


def test_history_lookup_scales_and_preserves_supplied_order(tmp_path):
    scripts, rows = [], []
    for number in range(120):
        path = tmp_path / f"V{number + 1}__example.sql"
        path.write_text("SELECT 1;\n")
        script = Migration(path)
        scripts.append(script)
        rows.extend(
            [
                history(script, checksum=1, rank=100),
                history(script, checksum=str(script.checksum & 0xFFFFFFFF), success="1", rank=2),
                history(script, checksum=2, success="0", rank=3),
                history(script, checksum=3, type=MigrationType.UNDO_SQL, rank=4),
                history(script, checksum=4, type=MigrationType.DELETE, rank=5),
            ]
        )
    rows = CountingList(rows)
    scripts = CountingList(scripts)
    result, issues = ValidationResult(), []
    validator()._validate_checksums(scripts, rows, result, issues)
    assert issues == []
    assert result.checked_scripts == [script.script_name for script in scripts]
    assert rows.visits <= 4 * len(rows)
    assert scripts.visits <= 3 * len(scripts)


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("later_rank", [1, 20])
def test_repeatable_history_is_indexed_and_previous_run_uses_rank(tmp_path, failed, later_rank):
    scripts, rows = [], []
    for number in range(80):
        path = tmp_path / f"R__example_{number}.sql"
        path.write_text("SELECT 1;\n")
        script = Migration(path)
        scripts.append(script)
        rows.extend(
            [history(script, success=not failed, rank=20), history(script, rank=later_rank)]
        )
    rows = CountingList(rows)
    result = ValidationResult()
    validator()._check_repeatable_migrations(scripts, rows, result)
    assert result.success is not failed
    assert result.error_message.count("previously failed") == (len(scripts) if failed else 0)
    assert result.repeatable_migrations_to_reapply == []
    assert rows.visits <= 3 * len(rows)


def test_qualified_names_choose_first_match_and_filtered_deleted_missing_rows(tmp_path):
    first = tmp_path / "first" / "V1__example.sql"
    second = tmp_path / "second" / first.name
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("SELECT 1;\n")
    second.write_text("SELECT 2;\n")
    script, duplicate = Migration(first), Migration(second)
    filtered_path = tmp_path / "V2__filtered.sql"
    filtered_path.write_text("SELECT 2;\n")
    filtered = Migration(filtered_path)
    missing = Migration(script_name="V3__missing.sql")
    deleted = Migration(script_name="V4__deleted.sql")
    rows = [
        history(script, name="old/directory/V1__example.sql"),
        history(filtered, checksum=1),
        history(missing),
        history(deleted),
        history(deleted, type=MigrationType.DELETE),
    ]
    result, issues = ValidationResult(), []
    validator()._validate_checksums(
        [script, duplicate],
        rows,
        result,
        issues,
        strict_mode=True,
        all_scripts=[script, duplicate, filtered],
    )
    assert result.failed_scripts == [missing.script_name]
    assert len(issues) == 1
    assert "V3__missing.sql' is missing from the migration directory" in issues[0]


def test_validation_uses_supplied_checksum_and_standalone_observes_edits(tmp_path):
    path = tmp_path / "V1__example.sql"
    path.write_text("SELECT 1;\n")
    script = Migration(path)
    rows = [history(script)]
    path.write_text("SELECT 2;\n")
    legacy = SimpleNamespace(
        script_name=script.script_name, path=path, version="1", checksum=Migration(path).checksum
    )
    instance = validator()
    result, issues = ValidationResult(), []
    with patch(
        "pathlib.Path.read_text",
        wraps=path.read_text,
    ) as reads:
        instance._validate_checksums([legacy], rows, result, issues)
    assert result.failed_scripts == [script.script_name]
    assert "has been modified" in issues[0]
    assert reads.call_count == 0
    assert instance.script_manager.has_script_changed(script.script_name, rows, path)
    path.write_text("SELECT 1;\n")
    assert not instance.script_manager.has_script_changed(script.script_name, rows, path)
