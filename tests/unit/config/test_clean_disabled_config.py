"""Configuration tests for the destructive clean guardrail."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dblift.config.dblift_config import DbliftConfig, load_config


def _minimal_config(clean_disabled: bool | None = None) -> dict:
    data = {
        "database": {
            "type": "postgresql",
            "url": "postgresql+psycopg://localhost:5432/app",
            "username": "app",
            "password": "secret",
            "schema": "public",
        }
    }
    if clean_disabled is not None:
        data["clean_disabled"] = clean_disabled
    return data


@pytest.mark.unit
class TestCleanDisabledConfig:
    def test_default_is_clean_disabled(self):
        config = DbliftConfig.from_dict(_minimal_config())

        assert config.clean_disabled is True

    def test_config_file_can_enable_clean(self):
        config = DbliftConfig.from_dict(_minimal_config(clean_disabled=False))

        assert config.clean_disabled is False
        assert config.to_dict()["clean_disabled"] is False

    def test_merge_preserves_false_value(self):
        config = DbliftConfig.from_dict(_minimal_config())

        config.merge({"clean_disabled": False})

        assert config.clean_disabled is False

    def test_env_can_enable_clean(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_CLEAN_DISABLED", "false")

        assert DbliftConfig.from_env_dict()["clean_disabled"] is False

    def test_cli_clean_enabled_overrides_config(self, tmp_path):
        config_file = tmp_path / "dblift.yaml"
        config_file.write_text(
            """
database:
  type: postgresql
  url: postgresql+psycopg://localhost:5432/app
  username: app
  password: secret
  schema: public
clean_disabled: true
""",
            encoding="utf-8",
        )
        args = SimpleNamespace(clean_disabled=False)

        config = load_config(str(config_file), args)

        assert config.clean_disabled is False

    def test_cli_clean_disabled_overrides_config_enabling_clean(self, tmp_path):
        """An explicit ``--clean-disabled`` is True, which is also the registry default.

        Reading "equals the default" as "not given" let a file's ``clean_disabled: false``
        win over the flag, so ``clean`` dropped everything the flag asked it to protect.
        """
        from dblift.cli._parser_setup import create_parser

        config_file = tmp_path / "dblift.yaml"
        config_file.write_text(
            _config_yaml(clean_disabled="false"),
            encoding="utf-8",
        )
        args = create_parser().parse_args(["clean", "--clean-disabled"])

        config = load_config(str(config_file), args)

        assert config.clean_disabled is True

    def test_cli_clean_disabled_overrides_environment_enabling_clean(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DBLIFT_CLEAN_DISABLED", "false")
        config_file = tmp_path / "dblift.yaml"
        config_file.write_text(_config_yaml(), encoding="utf-8")

        config = load_config(str(config_file), SimpleNamespace(clean_disabled=True))

        assert config.clean_disabled is True

    def test_unset_flag_leaves_the_config_value(self, tmp_path):
        from dblift.cli._parser_setup import create_parser

        config_file = tmp_path / "dblift.yaml"
        config_file.write_text(_config_yaml(clean_disabled="false"), encoding="utf-8")

        config = load_config(str(config_file), create_parser().parse_args(["clean"]))

        assert config.clean_disabled is False


def _config_yaml(clean_disabled: str | None = None) -> str:
    text = """
database:
  type: postgresql
  url: postgresql+psycopg://localhost:5432/app
  username: app
  password: secret
  schema: public
"""
    return text + (f"clean_disabled: {clean_disabled}\n" if clean_disabled else "")
