"""The MCP runner writes no log file unless a log directory is requested."""

from pathlib import Path

import pytest
import yaml

from dblift.cli.mcp.runner import run_command

pytestmark = [pytest.mark.unit]


def _files(root: Path, suffixes=(".log", ".json", ".html")):
    return sorted(p for p in root.rglob("*") if p.suffix in suffixes)


@pytest.fixture
def mcp_project(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(tmp_path / "t.sqlite")},
                "migrations": {"directory": str(migrations)},
            }
        )
    )
    return config, work


def test_mcp_call_without_log_dir_writes_no_file(mcp_project):
    config, work = mcp_project
    run_command(["--config", str(config)], "info", [])
    run_command(["--config", str(config)], "info", [])
    assert list(work.iterdir()) == []
    assert _files(config.parent) == []


def test_mcp_calls_with_log_dir_share_one_file(mcp_project, tmp_path):
    config, work = mcp_project
    target = tmp_path / "mcplogs"
    argv = ["--config", str(config), "--log-dir", str(target)]
    run_command(argv, "info", [])
    run_command(argv, "info", [])
    assert len(_files(target)) == 1
    assert list(work.iterdir()) == []
