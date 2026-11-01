"""A configured scripts directory that does not exist fails every command, in any position."""

import json
import os
import subprocess
import sys

import pytest
import yaml

from dblift.api import DBLiftClient

pytestmark = pytest.mark.unit

OPERATIONS = ["info", "validate", "migrate", "migrate_dry_run", "undo", "repair"]


@pytest.fixture
def project(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("DBLIFT_"):
            monkeypatch.delenv(key)
    good = tmp_path / "good"
    good.mkdir()
    (good / "V1__a.sql").write_text("CREATE TABLE a_table (id INTEGER);")
    return tmp_path


def _write_config(project, directories):
    config = project / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(project / "t.db")},
                "migrations": {"directories": directories},
            }
        )
    )
    return config


def _layouts(project):
    good, missing = str(project / "good"), str(project / "missing")
    return {
        "dict-good-first": [{"path": good}, {"path": missing, "recursive": True}],
        "dict-missing-first": [{"path": missing, "recursive": True}, {"path": good}],
        "list-good-first": [good, missing],
        "list-missing-first": [missing, good],
    }


LAYOUTS = ["dict-good-first", "dict-missing-first", "list-good-first", "list-missing-first"]


def _call(client, operation):
    if operation == "migrate_dry_run":
        return client.migrate(dry_run=True)
    return getattr(client, operation)()


def _tables(project):
    import sqlite3

    path = project / "t.db"
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        return [r[0] for r in conn.execute("select name from sqlite_master where type='table'")]


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("operation", OPERATIONS)
def test_api_fails_on_any_missing_configured_directory(project, layout, operation):
    missing = project / "missing"
    if operation == "undo":  # with no history there is nothing to undo, so nothing is read
        with DBLiftClient.from_config_file(
            str(_write_config(project, [str(project / "good")]))
        ) as c:
            assert c.migrate().success
    config = _write_config(project, _layouts(project)[layout])

    with DBLiftClient.from_config_file(str(config)) as client:
        result = _call(client, operation)

    assert not result.success
    kind = "Migration" if layout.endswith("missing-first") else "Additional"
    assert f"{kind} scripts directory not found: {missing}" in result.error_message
    assert ("a_table" in _tables(project)) == (operation == "undo")


def test_api_explicit_additional_dirs_are_checked(project):
    config = _write_config(project, [str(project / "good")])
    with DBLiftClient.from_config_file(str(config)) as client:
        result = client.migrate(additional_dirs=[project / "good", project / "typo"])

    assert not result.success
    assert f"Additional scripts directory not found: {project / 'typo'}" in result.error_message
    assert "a_table" not in _tables(project)


def test_api_all_directories_present_still_works(project):
    (project / "second").mkdir()
    (project / "second" / "V2__b.sql").write_text("CREATE TABLE b_table (id INTEGER);")
    config = _write_config(project, [str(project / "good"), {"path": str(project / "second")}])

    with DBLiftClient.from_config_file(str(config)) as client:
        assert client.validate().success
        assert client.migrate().success

    assert {"a_table", "b_table"} <= set(_tables(project))


def _cli(project, config, *args):
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", "--config", str(config), *args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=project,
    )


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize(
    "command",
    [
        ["info", "--format", "json"],
        ["validate", "--format", "json"],
        ["migrate", "--dry-run", "--format", "json"],
        ["migrate", "--format", "json"],
    ],
    ids=["info", "validate", "migrate-dry-run", "migrate"],
)
def test_cli_exits_one_whichever_directory_is_missing(project, layout, command):
    config = _write_config(project, _layouts(project)[layout])

    proc = _cli(project, config, *command)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    kind = "Migration" if layout.endswith("missing-first") else "Additional"
    assert f"{kind} scripts directory not found: {project / 'missing'}" in proc.stdout + proc.stderr
    payload, _ = json.JSONDecoder().raw_decode(proc.stdout[proc.stdout.index("{") :])
    assert payload["success"] is False
    assert "a_table" not in _tables(project)


def test_cli_scripts_flag_with_missing_second_directory_is_unchanged(project):
    config = _write_config(project, [str(project / "good")])

    proc = _cli(
        project,
        config,
        "--scripts",
        str(project / "good"),
        "--scripts",
        str(project / "missing"),
        "migrate",
    )

    assert proc.returncode == 2
    assert "Additional scripts directory not found" in proc.stderr
    assert "a_table" not in _tables(project)
