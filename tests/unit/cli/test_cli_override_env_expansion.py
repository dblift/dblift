"""CLI database overrides resolve ${VAR} placeholders like a config-file value does."""

from types import SimpleNamespace

from dblift.cli._config_helpers import _load_and_merge_config
from dblift.config.dblift_config import DbliftConfig


def _args(**kwargs):
    base = {
        "config": None,
        "command": "info",
        "commands_list": ["info"],
        "database_url": None,
        "database_username": None,
        "database_password": None,
        "database_schema": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_cli_password_placeholder_is_expanded(monkeypatch):
    monkeypatch.setenv("B1_DB_PASSWORD", "s3cret")
    args = _args(
        database_url="postgresql+psycopg://u:p@localhost:5432/app",
        database_password="${B1_DB_PASSWORD}",
    )
    config = _load_and_merge_config(args, None)
    assert config.database.password == "s3cret"


def test_cli_username_and_url_placeholders_are_expanded(monkeypatch):
    monkeypatch.setenv("B1_HOST", "dbhost")
    monkeypatch.setenv("B1_USER", "alice")
    args = _args(
        database_url="postgresql+psycopg://u:p@${B1_HOST}:5432/app",
        database_username="${B1_USER}",
    )
    config = _load_and_merge_config(args, None)
    assert config.database.username == "alice"
    assert "dbhost" in config.database.url


def test_config_file_password_placeholder_is_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("B1_DB_PASSWORD", "s3cret")
    cfg = tmp_path / "dblift.yaml"
    cfg.write_text(
        "database:\n  url: postgresql+psycopg://u@localhost:5432/app\n"
        "  password: ${B1_DB_PASSWORD}\n"
    )
    assert DbliftConfig.load_config_data_from_yaml(cfg)["database"]["password"] == "s3cret"


def test_cli_oracle_url_database_name_follows_override():
    args = _args(database_url="oracle+oracledb://u:p@dbhost:1521/?service_name=SVC_ONE")
    config = _load_and_merge_config(args, None)
    assert config.database.type == "oracle"
    assert config.database.service_name == "SVC_ONE"
    assert "SVC_ONE" in config.database.url
