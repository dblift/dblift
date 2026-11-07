"""The documented SQLite file path is available through DBLIFT_DB_PATH."""

from argparse import Namespace

import pytest

from dblift.cli.commands.config_command import build_property_table
from dblift.config.config_builder import ConfigBuilder
from dblift.config.dblift_config import load_config

pytestmark = pytest.mark.unit


def test_sqlite_path_from_environment_without_yaml(monkeypatch, tmp_path):
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("DBLIFT_DB_TYPE", "sqlite")
    monkeypatch.setenv("DBLIFT_DB_PATH", str(db_path))

    config = load_config(None)

    assert config.database.path == str(db_path)


def test_sqlite_environment_path_overrides_yaml(monkeypatch, tmp_path):
    config_file = tmp_path / "dblift.yaml"
    config_file.write_text("database:\n  type: sqlite\n  path: yaml.db\n")
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("DBLIFT_DB_PATH", str(db_path))

    config = load_config(str(config_file))

    assert config.database.path == str(db_path)


def test_sqlite_environment_path_overrides_yaml_url(monkeypatch, tmp_path):
    config_file = tmp_path / "dblift.yaml"
    config_file.write_text("database:\n  type: sqlite\n  url: sqlite:///yaml.db\n")
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("DBLIFT_DB_PATH", str(db_path))

    config = load_config(str(config_file))

    assert config.database.path == str(db_path)


def test_sqlite_environment_path_overrides_url_without_explicit_type(monkeypatch, tmp_path):
    config_file = tmp_path / "dblift.yaml"
    config_file.write_text("database:\n  url: sqlite:///yaml.db\n")
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("DBLIFT_DB_PATH", str(db_path))

    config = load_config(str(config_file))

    assert config.database.path == str(db_path)


def test_sqlite_selected_environment_path_overrides_root_url(monkeypatch, tmp_path):
    config_file = tmp_path / "dblift.yaml"
    config_file.write_text(
        "database:\n  type: sqlite\n  url: sqlite:///root.db\n"
        "environments:\n  dev:\n    database:\n      path: dev.db\n"
    )
    monkeypatch.setenv("DBLIFT_ENV", "dev")

    config = load_config(str(config_file))

    assert config.database.path == str(tmp_path / "dev.db")


def test_cli_url_overrides_environment_path(monkeypatch, tmp_path):
    monkeypatch.setenv("DBLIFT_DB_TYPE", "sqlite")
    monkeypatch.setenv("DBLIFT_DB_PATH", str(tmp_path / "env.db"))

    config = load_config(None, Namespace(db_url="sqlite:///cli.db"))

    assert config.database.path == "cli.db"


def test_same_source_url_wins_over_path(tmp_path):
    config_file = tmp_path / "dblift.yaml"
    config_file.write_text("database:\n  type: sqlite\n  path: path.db\n  url: sqlite:///url.db\n")

    config = load_config(str(config_file))

    assert config.database.path == str(tmp_path / "url.db")


def test_config_builder_environment_path_overrides_yaml_url(monkeypatch, tmp_path):
    config_file = tmp_path / "dblift.yaml"
    config_file.write_text("database:\n  type: sqlite\n  url: sqlite:///yaml.db\n")
    db_path = tmp_path / "env.db"
    monkeypatch.setenv("DBLIFT_DB_PATH", str(db_path))

    config = ConfigBuilder.build(file_path=str(config_file), env_overrides=True)

    assert config.database.path == str(db_path)


def test_config_listing_advertises_sqlite_path():
    path = next(row for row in build_property_table() if row["name"] == "database.path")

    assert path["env"] == "DBLIFT_DB_PATH"
    assert path["cli"] == "(none)"
