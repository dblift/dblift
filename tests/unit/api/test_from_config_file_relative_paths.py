"""``from_config_file(relative_to_config=True)`` resolves relative paths from the config folder."""

from pathlib import Path

import pytest

from dblift.api.client import DBLiftClient


def _project(root: Path) -> Path:
    project = root / "project"
    (project / "migrations").mkdir(parents=True)
    (project / "migrations" / "V1_0_0__create_a.sql").write_text(
        "CREATE TABLE a (id INTEGER PRIMARY KEY);\n"
    )
    config = project / "dblift.yaml"
    config.write_text(
        "database:\n"
        "  type: sqlite\n"
        "  path: ./app.db\n"
        "migrations:\n"
        "  directory: ./migrations\n"
    )
    return config


@pytest.mark.unit
class TestRelativeToConfig:
    def test_paths_resolve_from_config_folder(self, tmp_path, monkeypatch):
        config = _project(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
            pending = [m.script for m in client.info().migrations]
            result = client.migrate()

        assert pending == ["V1_0_0__create_a.sql"]
        assert result.success
        assert (config.parent / "app.db").exists()
        assert (config.parent / "logs").is_dir()
        assert list(elsewhere.iterdir()) == []

    def test_default_still_resolves_from_working_directory(self, tmp_path, monkeypatch):
        config = _project(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        with DBLiftClient.from_config_file(str(config)) as client:
            pending = [m.script for m in client.info().migrations]

        assert pending == []

    def test_absolute_paths_are_left_alone(self, tmp_path, monkeypatch):
        config = _project(tmp_path)
        absolute_db = tmp_path / "absolute.db"
        config.write_text(config.read_text().replace("./app.db", str(absolute_db)))
        monkeypatch.chdir(tmp_path)

        with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
            client.migrate()

        assert absolute_db.exists()

    def test_directories_list_is_anchored(self, tmp_path, monkeypatch):
        config = _project(tmp_path)
        config.write_text(
            "database:\n"
            "  type: sqlite\n"
            "  path: ./app.db\n"
            "migrations:\n"
            "  directories:\n"
            "    - ./migrations\n"
        )
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
            pending = [m.script for m in client.info().migrations]

        assert pending == ["V1_0_0__create_a.sql"]
