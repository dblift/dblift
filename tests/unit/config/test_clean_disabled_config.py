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
