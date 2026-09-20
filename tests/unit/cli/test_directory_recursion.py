"""Configured recursion must select the same files through CLI and API."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest
import yaml

from dblift.api import DBLiftClient

pytestmark = pytest.mark.unit


def _project(tmp_path, reverse=False, global_recursive=True):
    for folder in ("a", "b"):
        (tmp_path / folder / "nested").mkdir(parents=True)
    for path, table in (
        ("a/V1__root.sql", "root_table"),
        ("a/nested/V3__excluded.sql", "excluded_table"),
        ("b/nested/V2__included.sql", "included_table"),
    ):
        (tmp_path / path).write_text(f"CREATE TABLE {table}(id INTEGER);")
    directories = [
        {"path": str(tmp_path / "a"), "recursive": False},
        {"path": str(tmp_path / "b"), "recursive": True},
    ]
    if reverse:
        directories.reverse()
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite")},
                "migrations": {"directories": directories, "recursive": global_recursive},
            }
        )
    )
    return config


def _tables(tmp_path):
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        return {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0].endswith("_table")
        }


@pytest.mark.parametrize("surface", ["cli", "api"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("recursive", [None, True, False])
def test_migrate_respects_directory_flags_and_explicit_override(
    tmp_path, monkeypatch, surface, reverse, recursive
):
    config = _project(tmp_path, reverse)
    for key in list(os.environ):
        if key.startswith("DBLIFT_"):
            monkeypatch.delenv(key)
    if surface == "cli":
        flags = [] if recursive is None else ["--recursive" if recursive else "--no-recursive"]
        result = subprocess.run(
            [sys.executable, "-m", "dblift.cli.main", "--config", str(config), *flags, "migrate"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        with DBLiftClient.from_config_file(str(config)) as client:
            options = {} if recursive is None else {"recursive": recursive}
            result = client.migrate(**options)
            assert result.success, result.error_message
    expected = {"root_table", "included_table"}
    if recursive is True:
        expected.add("excluded_table")
    elif recursive is False:
        expected = {"root_table"}
    assert _tables(tmp_path) == expected


def test_api_explicit_directory_map_overrides_config_without_mutating_it(tmp_path):
    config = _project(tmp_path, global_recursive=False)
    overrides = {tmp_path / "a": True, tmp_path / "b": False}
    with DBLiftClient.from_config_file(str(config)) as client:
        result = client.migrate(dir_recursive_map=overrides)
        assert result.success, result.error_message
        assert _tables(tmp_path) == {"root_table", "excluded_table"}
        # Next call must use the original config, not the previous call's overrides.
        result = client.migrate()
        assert result.success, result.error_message
    assert _tables(tmp_path) == {"root_table", "excluded_table", "included_table"}
    assert overrides == {tmp_path / "a": True, tmp_path / "b": False}


def test_api_default_honors_global_nonrecursive_setting(tmp_path):
    config = _project(tmp_path)
    data = yaml.safe_load(config.read_text())
    data["migrations"] = {"directory": str(tmp_path / "a"), "recursive": False}
    config.write_text(yaml.safe_dump(data))
    with DBLiftClient.from_config_file(str(config)) as client:
        preview = client.migrate(dry_run=True)
        assert preview.success, preview.error_message
        assert _tables(tmp_path) == set()
        result = client.migrate()
        assert result.success, result.error_message
    assert _tables(tmp_path) == {"root_table"}


@pytest.mark.parametrize("surface", ["cli", "api"])
@pytest.mark.parametrize("command", ["info", "validate", "preview", "validate-only"])
def test_read_commands_ignore_duplicate_version_in_excluded_subdirectory(
    tmp_path, surface, command
):
    config = _project(tmp_path)
    (tmp_path / "a/nested/V1__duplicate.sql").write_text(
        "CREATE TABLE duplicate_table(id INTEGER);"
    )
    if surface == "cli":
        args = {
            "preview": ["--dry-run", "migrate"],
            "validate-only": ["migrate", "--validate-only"],
        }.get(command, [command])
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "dblift.cli.main",
                "--config",
                str(config),
                "--format",
                "json",
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        if command in ("info", "preview"):
            payload = json.loads(result.stdout)
            assert {m["version"] for m in payload["migrations"]} == {"1", "2"}
    else:
        with DBLiftClient.from_config_file(str(config)) as client:
            if command == "preview":
                result = client.migrate(dry_run=True)
            elif command == "validate-only":
                result = client.validate()
            else:
                result = getattr(client, command)()
            assert result.success, result.error_message
            if command in ("info", "preview"):
                assert {str(m.version) for m in result.migrations} == {"1", "2"}
    assert _tables(tmp_path) == set()


@pytest.mark.parametrize("surface", ["cli", "api"])
@pytest.mark.parametrize("command", ["undo", "clean", "repair"])
def test_maintenance_ignores_callbacks_in_excluded_subdirectory(tmp_path, surface, command):
    config = _project(tmp_path, reverse=True)
    with DBLiftClient.from_config_file(str(config)) as client:
        result = client.migrate(dir_recursive_map={tmp_path / "a": False, tmp_path / "b": True})
        assert result.success, result.error_message
    (tmp_path / "b/nested/U2__included.sql").write_text("DROP TABLE included_table;")
    (tmp_path / f"a/nested/before{command.title()}__excluded.sql").write_text("INVALID SQL;")
    if surface == "cli":
        flags = ["--clean-enabled"] if command == "clean" else []
        result = subprocess.run(
            [sys.executable, "-m", "dblift.cli.main", "--config", str(config), command, *flags],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        with DBLiftClient.from_config_file(str(config)) as client:
            flags = {"clean_enabled": True} if command == "clean" else {}
            result = getattr(client, command)(**flags)
            assert result.success, result.error_message
    expected = {"root_table", "included_table"}
    if command == "clean":
        expected = set()
    elif command == "undo":
        expected = {"root_table"}
    assert _tables(tmp_path) == expected
