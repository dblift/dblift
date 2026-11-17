"""The Python API and the MCP runner write no log file unless one is requested."""

from pathlib import Path

import pytest

from dblift.api.client import DBLiftClient
from dblift.config.dblift_config import DbliftConfig
from dblift.config.path_anchoring import anchor_config_paths
from dblift.core.logger import DbliftLogger, NullLog

pytestmark = [pytest.mark.unit]


def _project(tmp_path: Path, extra: str = "") -> Path:
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


def _files(root: Path, suffixes=(".log", ".json", ".html")):
    return sorted(p for p in root.rglob("*") if p.suffix in suffixes)


def test_logger_without_directory_is_console_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = DbliftLogger()
    logger.info("hello")
    assert logger.current_log_file is None
    assert list(tmp_path.iterdir()) == []


def test_logger_with_directory_writes_a_file(tmp_path):
    logger = DbliftLogger(logfile_dir=tmp_path / "out")
    logger.info("hello")
    logger.cleanup()
    assert len(_files(tmp_path / "out")) == 1


def test_anchoring_does_not_invent_a_log_directory(tmp_path):
    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": "app.db"}, "migrations": {"directory": "m"}}
    )
    anchor_config_paths(config, tmp_path)
    assert config.log_dir is None
    assert config.logging.directory is None


def test_log_level_alone_logs_to_console_without_a_file(tmp_path, monkeypatch):
    config = _project(tmp_path, "logging:\n  level: DEBUG\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
        assert isinstance(client.logger, DbliftLogger)
        client.migrate()
    assert _files(tmp_path) == []
    assert not (config.parent / "logs").exists()
    assert list(elsewhere.iterdir()) == []


def test_log_level_argument_without_config_file_writes_no_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "path": str(tmp_path / "app.db")},
            "migrations": {"directory": str(tmp_path / "m")},
        }
    )
    (tmp_path / "m").mkdir()
    with DBLiftClient.from_config(config, log_level="DEBUG") as client:
        assert isinstance(client.logger, DbliftLogger)
    assert not (tmp_path / "logs").exists()


@pytest.mark.parametrize(
    "extra", ["log_dir: ./mylogs\n", "logging:\n  directory: ./mylogs\n"], ids=["flat", "nested"]
)
def test_configured_directory_still_receives_the_file(tmp_path, extra):
    config = _project(tmp_path, extra)
    with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
        client.migrate()
    assert len(_files(config.parent / "mylogs")) == 1


def test_no_logging_keys_stays_silent(tmp_path):
    config = _project(tmp_path)
    with DBLiftClient.from_config_file(str(config)) as client:
        assert isinstance(client.logger, NullLog)
