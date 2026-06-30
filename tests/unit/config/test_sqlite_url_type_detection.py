"""Tests for SQLite URL type detection in config override paths."""

import argparse
import os

import pytest

from config.config_builder import ConfigBuilder
from config.dblift_config import load_config
from config.errors import ConfigurationError
from db.plugins.sqlite.config import SQLiteConfig
from db.plugins.sqlserver.config import SqlServerConfig


def _args(**kwargs):
    """Build a minimal argparse.Namespace for load_config."""
    defaults = {
        "database_url": None,
        "db_url": None,
        "database_username": None,
        "db_username": None,
        "database_password": None,
        "db_password": None,
        "database_schema": None,
        "db_schema": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.mark.unit
class TestSqliteUrlTypeDetection:
    """BUG-01: --db-url sqlite:///... must set config.database.type to 'sqlite'."""

    def test_sqlite_url_prefix_sets_type(self):
        """sqlite:///tmp/x.db URL → type = 'sqlite'."""
        args = _args(db_url="sqlite:///tmp/test.db")
        config = load_config(None, args)
        assert (
            config.database.type == "sqlite"
        ), f"Expected type='sqlite', got '{config.database.type}'"

    def test_sqlite_url_prefix_creates_fresh_sqlite_config(self):
        """sqlite:///tmp/x.db URL must not leave SqlServerConfig defaults like database='master'."""
        args = _args(db_url="sqlite:////tmp/test.db")
        config = load_config(None, args)

        assert isinstance(config.database, SQLiteConfig)
        assert config.database.path == "/tmp/test.db"
        assert getattr(config.database, "database", None) != "master"

    def test_sqlite3_url_prefix_sets_type(self):
        """sqlite3:///tmp/x.db URL → type = 'sqlite'."""
        args = _args(db_url="sqlite3:///tmp/test.db")
        config = load_config(None, args)
        assert (
            config.database.type == "sqlite"
        ), f"Expected type='sqlite', got '{config.database.type}'"
        assert config.database.path == "/tmp/test.db"

    def test_jdbc_sqlite_url_prefix_is_rejected(self):
        """Legacy jdbc:sqlite URLs are rejected in v2."""
        args = _args(db_url="jdbc:sqlite:/tmp/test.db")
        with pytest.raises(
            ConfigurationError, match="Legacy database URLs are no longer supported"
        ):
            load_config(None, args)

    def test_jdbc_postgresql_url_still_sets_postgresql(self):
        """postgresql+psycopg://... URL is unaffected by the new sqlite detection."""
        args = _args(
            db_url="postgresql+psycopg://localhost:5432/testdb",
            db_username="user",
            db_password="pass",
        )
        config = load_config(None, args)
        assert (
            config.database.type == "postgresql"
        ), f"Expected type='postgresql', got '{config.database.type}'"

    def test_env_sqlite_url_without_type_creates_sqlite_config(self, monkeypatch):
        """DBLIFT_DB_URL=sqlite:///... should imply sqlite without DBLIFT_DB_TYPE."""
        for key in list(os.environ):
            if key.startswith("DBLIFT_DB_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("DBLIFT_DB_URL", "sqlite:////tmp/env-only.db")

        config = load_config(None, None)

        assert isinstance(config.database, SQLiteConfig)
        assert config.database.type == "sqlite"
        assert config.database.path == "/tmp/env-only.db"

    def test_env_sqlite_url_replaces_stale_yaml_path(self, monkeypatch, tmp_path):
        """A higher-precedence SQLite URL must not keep a lower-precedence path."""
        for key in list(os.environ):
            if key.startswith("DBLIFT_DB_"):
                monkeypatch.delenv(key, raising=False)
        old_db = tmp_path / "old.db"
        new_db = tmp_path / "new.db"
        config_file = tmp_path / "dblift.yaml"
        config_file.write_text(f"""
database:
  type: sqlite
  path: {old_db}
""")
        monkeypatch.setenv("DBLIFT_DB_URL", f"sqlite:///{new_db}")

        config = load_config(str(config_file), None)

        assert isinstance(config.database, SQLiteConfig)
        assert config.database.path == str(new_db)


@pytest.mark.unit
class TestConfigBuilderMergeOverridesSqlite:
    """BUG-01: ConfigBuilder.merge_database_overrides must not reset type to 'sqlserver'
    when a sqlite:// URL is applied over a SqlServerConfig base (the default config type).
    This covers the root-cause path: __post_init__ resets type after dataclasses.replace().
    """

    def _base_sqlserver_config(self):
        """Return a SqlServerConfig (the default base_config type when no YAML config exists)."""
        return SqlServerConfig(
            type="sqlserver",
            url="mssql+pymssql://localhost:1433/master",
            username="sa",
            password="pass",
            schema="dbo",
        )

    def test_sqlite_url_override_sets_type_sqlite(self):
        """sqlite:/// URL override on SqlServerConfig base → type = 'sqlite'."""
        base = self._base_sqlserver_config()
        result = ConfigBuilder.merge_database_overrides(base, {"url": "sqlite:///tmp/x.db"})
        assert result.type == "sqlite", f"Expected 'sqlite', got '{result.type}'"

    def test_sqlite3_url_override_sets_type_sqlite(self):
        """sqlite3:/// URL override on SqlServerConfig base → type = 'sqlite'."""
        base = self._base_sqlserver_config()
        result = ConfigBuilder.merge_database_overrides(base, {"url": "sqlite3:///tmp/x.db"})
        assert result.type == "sqlite", f"Expected 'sqlite', got '{result.type}'"

    def test_sqlserver_url_override_unchanged(self):
        """SQL Server SQLAlchemy URL override does not change type away from 'sqlserver'."""
        base = self._base_sqlserver_config()
        result = ConfigBuilder.merge_database_overrides(
            base, {"url": "mssql+pymssql://localhost:1433/mydb"}
        )
        assert result.type == "sqlserver", f"Expected 'sqlserver', got '{result.type}'"
