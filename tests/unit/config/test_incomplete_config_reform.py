"""Regression tests for A-1/A-2/A-3 config reform.

A-1: BaseDatabaseConfig.create() returns _IncompleteDatabaseConfig stub when
     _allow_incomplete=True and no registered db_type is found — no crash.

A-2: ConfigBuilder.build() raises FileNotFoundError for missing config files
     (matches CLI behaviour via load_config()).

A-3: load_config() merges env-var overrides directly into the typed config
     so a lone DBLIFT_DB_SCHEMA without DBLIFT_DB_TYPE no longer crashes.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from config.config_builder import ConfigBuilder
from config.database_config import BaseDatabaseConfig
from config.dblift_config import DbliftConfig
from config.errors import ConfigurationError


class TestAllowIncompleteEarlyExit:
    """A-1: _allow_incomplete returns a stub before the type-registry crash."""

    def test_no_type_with_allow_incomplete_returns_stub(self):
        result = BaseDatabaseConfig.create({"_allow_incomplete": True, "schema": "env_schema"})
        assert result.schema == "env_schema"
        assert type(result).__name__ == "_IncompleteDatabaseConfig"

    def test_stub_carries_all_provided_fields(self):
        result = BaseDatabaseConfig.create(
            {"_allow_incomplete": True, "schema": "s1", "username": "u1"}
        )
        assert result.schema == "s1"
        assert result.username == "u1"

    def test_no_type_without_allow_incomplete_raises(self):
        with pytest.raises(ValueError, match="Database URL is required"):
            BaseDatabaseConfig.create({"schema": "x"})

    def test_unknown_type_without_allow_incomplete_raises(self):
        with pytest.raises(ValueError):
            BaseDatabaseConfig.create({"type": "nonexistent_db", "url": "jdbc:nonexistent://x"})

    def test_unknown_type_with_allow_incomplete_returns_stub(self):
        result = BaseDatabaseConfig.create(
            {"type": "no_such_db", "_allow_incomplete": True, "schema": "s"}
        )
        assert type(result).__name__ == "_IncompleteDatabaseConfig"
        assert result.schema == "s"

    def test_known_type_still_creates_correct_class(self):
        result = BaseDatabaseConfig.create(
            {
                "type": "postgresql",
                "_allow_incomplete": True,
                "url": "postgresql+psycopg://localhost/db",
            }
        )
        assert type(result).__name__ == "PostgreSqlConfig"

    def test_stub_build_connection_string_raises(self):
        stub = BaseDatabaseConfig.create({"_allow_incomplete": True})
        with pytest.raises(NotImplementedError):
            stub.build_connection_string()


class TestConfigBuilderFileExistence:
    """A-2: ConfigBuilder.build() must raise on missing files — same as CLI."""

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            ConfigBuilder.build(file_path=str(tmp_path / "nonexistent.yaml"))

    def test_existing_file_loads_normally(self, tmp_path):
        cfg_file = tmp_path / "dblift.yaml"
        cfg_file.write_text(
            "database:\n  type: postgresql\n  url: postgresql+psycopg://localhost/db\n"
            "  username: u\n  password: p\n"
        )
        config = ConfigBuilder.build(file_path=str(cfg_file))
        assert config.database.type == "postgresql"

    def test_no_file_path_uses_defaults(self):
        with pytest.raises(ConfigurationError, match="No configuration source provided"):
            ConfigBuilder.build()


class TestEnvVarMergeModel:
    """A-3: Partial env-var overrides merge into an existing typed config without crash."""

    def _pg_config(self) -> DbliftConfig:
        from config.database_config import BaseDatabaseConfig

        return DbliftConfig.from_dict(
            {
                "database": {
                    "type": "postgresql",
                    "url": "postgresql+psycopg://localhost:5432/mydb",
                    "username": "user",
                    "password": "pass",
                    "schema": "public",
                }
            }
        )

    def test_schema_only_env_var_does_not_crash(self):
        config = self._pg_config()
        config.merge({"database": {"schema": "env_schema"}})
        assert config.database.schema == "env_schema"
        assert config.database.type == "postgresql"

    def test_env_schema_preserves_url_and_credentials(self):
        config = self._pg_config()
        config.merge({"database": {"schema": "new_schema"}})
        assert config.database.url == "postgresql+psycopg://localhost:5432/mydb"
        assert config.database.username == "user"

    def test_env_url_overrides_correctly(self):
        config = self._pg_config()
        new_url = "postgresql+psycopg://prod:5432/proddb"
        config.merge({"database": {"url": new_url}})
        assert config.database.url == new_url

    def test_load_config_with_env_schema_no_type_no_crash(self, tmp_path):
        cfg_file = tmp_path / "dblift.yaml"
        cfg_file.write_text(
            "database:\n  type: postgresql\n"
            "  url: postgresql+psycopg://localhost:5432/mydb\n"
            "  username: user\n  password: pass\n"
        )
        env_patch = {"DBLIFT_DB_SCHEMA": "override_schema"}
        with patch.dict(os.environ, env_patch, clear=False):
            from config.dblift_config import load_config

            config = load_config(str(cfg_file))
        assert config.database.schema == "override_schema"
        assert config.database.type == "postgresql"


class TestTopLevelEnvVarsNotDropped:
    """Regression: top-level env vars must be merged even when no DBLIFT_DB_* vars set.

    The narrow guard `if env_dict.get("database"):` silently dropped
    DBLIFT_HISTORY_TABLE, DBLIFT_SNAPSHOT_TABLE, and DBLIFT_MAX_SNAPSHOTS
    overrides whenever no database env vars were present. The systemic fix
    delegates the merge decision to `DbliftConfig.merge()` itself instead of
    pre-filtering on a single key.
    """

    def _clear_dblift_env(self):
        return {k: "" for k in os.environ if k.startswith("DBLIFT_")}

    def test_history_table_env_applied_without_db_env_vars(self, tmp_path):
        cfg_file = tmp_path / "dblift.yaml"
        cfg_file.write_text(
            "database:\n  type: postgresql\n"
            "  url: postgresql+psycopg://localhost:5432/mydb\n"
            "  username: u\n  password: p\n"
        )
        from config.dblift_config import load_config

        env_patch = {**self._clear_dblift_env(), "DBLIFT_HISTORY_TABLE": "custom_history"}
        with patch.dict(os.environ, env_patch, clear=False):
            config = load_config(str(cfg_file))
        assert config.history_table == "custom_history"

    def test_snapshot_table_env_applied_without_db_env_vars(self, tmp_path):
        cfg_file = tmp_path / "dblift.yaml"
        cfg_file.write_text(
            "database:\n  type: postgresql\n"
            "  url: postgresql+psycopg://localhost:5432/mydb\n"
            "  username: u\n  password: p\n"
        )
        from config.dblift_config import load_config

        env_patch = {**self._clear_dblift_env(), "DBLIFT_SNAPSHOT_TABLE": "custom_snapshots"}
        with patch.dict(os.environ, env_patch, clear=False):
            config = load_config(str(cfg_file))
        assert config.snapshot_table == "custom_snapshots"

    def test_max_snapshots_env_applied_without_db_env_vars(self, tmp_path):
        cfg_file = tmp_path / "dblift.yaml"
        cfg_file.write_text(
            "database:\n  type: postgresql\n"
            "  url: postgresql+psycopg://localhost:5432/mydb\n"
            "  username: u\n  password: p\n"
        )
        from config.dblift_config import load_config

        env_patch = {**self._clear_dblift_env(), "DBLIFT_MAX_SNAPSHOTS": "42"}
        with patch.dict(os.environ, env_patch, clear=False):
            config = load_config(str(cfg_file))
        assert config.max_snapshots == 42

    def test_config_builder_history_table_env_applied_without_db_env_vars(self, tmp_path):
        cfg_file = tmp_path / "dblift.yaml"
        cfg_file.write_text(
            "database:\n  type: postgresql\n"
            "  url: postgresql+psycopg://localhost:5432/mydb\n"
            "  username: u\n  password: p\n"
        )
        env_patch = {**self._clear_dblift_env(), "DBLIFT_HISTORY_TABLE": "cb_history"}
        with patch.dict(os.environ, env_patch, clear=False):
            config = ConfigBuilder.build(file_path=str(cfg_file), env_overrides=True)
        assert config.history_table == "cb_history"
