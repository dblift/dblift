"""A log file requested through the Python API is written, and never to a surprise place."""

from pathlib import Path

import pytest

from dblift.api.client import DBLiftClient
from dblift.config.dblift_config import DbliftConfig

pytestmark = [pytest.mark.unit]


def _project(tmp_path: Path, extra: str) -> Path:
    project = tmp_path / "project"
    (project / "migrations").mkdir(parents=True)
    (project / "migrations" / "V1_0_0__create_a.sql").write_text(
        "CREATE TABLE a (id INTEGER PRIMARY KEY);\n"
    )
    config = project / "dblift.yaml"
    config.write_text(
        "database:\n  type: sqlite\n  path: ./app.db\n"
        "migrations:\n  directory: ./migrations\n" + extra
    )
    return config


def _logs(root: Path):
    return sorted(root.glob("*.log"))


@pytest.mark.parametrize(
    "extra", ["log_file: nx.log\n", "logging:\n  file: nx.log\n"], ids=["flat", "nested"]
)
def test_relative_log_file_in_a_config_file_is_written_next_to_the_file(
    tmp_path, monkeypatch, extra
):
    config = _project(tmp_path, extra)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
        client.migrate()
    assert len(_logs(config.parent)) == 1
    assert list(elsewhere.iterdir()) == []


def test_log_file_argument_without_a_directory_is_written_to_the_working_directory(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    (tmp_path / "m").mkdir()
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "path": str(tmp_path / "app.db")},
            "migrations": {"directory": str(tmp_path / "m")},
        }
    )
    with DBLiftClient.from_config(config, log_file="x.log"):
        pass
    assert len(_logs(work)) == 1
    assert not (work / "logs").exists()
