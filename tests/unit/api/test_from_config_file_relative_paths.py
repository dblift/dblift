"""``from_config_file(relative_to_config=True)`` resolves relative paths from the config folder."""

from pathlib import Path

import pytest

from dblift.api.client import DBLiftClient
from dblift.config.dblift_config import DbliftConfig, DirectoryConfig
from dblift.config.path_anchoring import anchor_config_paths


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

    def test_dict_directory_entry_is_anchored_and_keeps_recursive(self, tmp_path, monkeypatch):
        config = _project(tmp_path)
        (config.parent / "migrations" / "sub").mkdir()
        (config.parent / "migrations" / "sub" / "V2_0_0__create_b.sql").write_text(
            "CREATE TABLE b (id INTEGER PRIMARY KEY);\n"
        )
        config.write_text(
            "database:\n"
            "  type: sqlite\n"
            "  path: ./app.db\n"
            "migrations:\n"
            "  directories:\n"
            "    - path: ./migrations\n"
            "      recursive: false\n"
        )
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        with DBLiftClient.from_config_file(str(config), relative_to_config=True) as client:
            pending = [m.script for m in client.info().migrations]

        assert pending == ["V1_0_0__create_a.sql"]


@pytest.mark.unit
def test_anchor_converts_raw_dict_entry(tmp_path):
    config = DbliftConfig.from_dict(
        {
            "database": {"type": "sqlite", "path": "./app.db"},
            "migrations": {"directories": [{"directory": "./migrations", "recursive": False}]},
        }
    )

    anchor_config_paths(config, tmp_path)

    expected = DirectoryConfig(path=str((tmp_path / "migrations").resolve()), recursive=False)
    assert config.migrations.directories == [expected]
    assert config.migrations.get_directory_configs() == [expected]
