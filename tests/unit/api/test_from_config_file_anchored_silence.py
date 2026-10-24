"""A log directory derived by path anchoring is not an opt-in to logging."""

import pytest

from dblift.api.client import DBLiftClient
from dblift.core.logger import DbliftLogger, NullLog


def _project(tmp_path, extra=""):
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


@pytest.mark.unit
class TestAnchoredClientIsSilent:
    def test_no_logging_keys_is_silent_and_writes_no_logs(self, tmp_path, capfd, monkeypatch):
        config = _project(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
            assert client.migrate().success

        captured = capfd.readouterr()
        assert captured.err == ""
        assert captured.out == ""
        assert not (config.parent / "logs").exists()
        assert list(elsewhere.iterdir()) == []

    def test_user_set_log_dir_still_opts_in(self, tmp_path):
        config = _project(tmp_path, "log_dir: ./mylogs\n")
        with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
            assert isinstance(client.logger, DbliftLogger)

    def test_log_level_keeps_logs_next_to_config(self, tmp_path):
        config = _project(tmp_path, "logging:\n  level: DEBUG\n")
        with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
            assert isinstance(client.logger, DbliftLogger)
            client.migrate()
        assert list((config.parent / "logs").glob("Dblift_*.log"))

    def test_without_flag_unchanged(self, tmp_path):
        config = _project(tmp_path)
        with DBLiftClient.from_config_file(str(config)) as client:
            assert isinstance(client.logger, NullLog)
