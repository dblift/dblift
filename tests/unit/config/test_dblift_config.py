import os
import tempfile

import pytest
import yaml

pytestmark = [pytest.mark.unit]

from config.dblift_config import (
    KNOWN_TOP_LEVEL_CONFIG_KEYS,
    DbliftConfig,
    DirectoryConfig,
    LoggingConfig,
    MigrationsConfig,
    unrecognized_top_level_keys,
)


class TestDbliftConfig:
    def test_from_dict_and_to_dict(self):
        d = {
            "database": {
                "url": "postgresql+psycopg://localhost:5432/testdb",
                "username": "postgres",
                "password": "pw",
            },
            "migrations": {"directory": "./migrations", "table": "schema_version"},
            "logging": {"level": "INFO", "file": "dblift.log"},
            "baseline_version": "1",
            "target_version": "2",
            "dry_run": True,
            "undo": True,
            "installed_by": "me",
            "extra_params": {"foo": "bar"},
            "tags": "t1",
            "exclude_tags": "t2",
            "versions": "v1",
            "exclude_versions": "v2",
            "mark_as_executed": True,
            "placeholders": {"x": "y"},
        }
        config = DbliftConfig.from_dict(d)
        d2 = config.to_dict()
        assert d2["database"]["type"] == "postgresql"
        assert d2["migrations"]["directory"] == "./migrations"
        assert d2["logging"]["level"] == "INFO"
        assert d2["baseline_version"] == "1"
        assert d2["target_version"] == "2"
        assert d2["dry_run"] is True
        assert d2["undo"] is True
        assert d2["installed_by"] == "me"
        assert d2["extra_params"]["foo"] == "bar"
        assert d2["tags"] == "t1"
        assert d2["exclude_tags"] == "t2"
        assert d2["versions"] == "v1"
        assert d2["exclude_versions"] == "v2"
        assert d2["mark_as_executed"] is True
        assert d2["placeholders"]["x"] == "y"

    def test_from_file(self):
        d = {
            "database": {
                "url": "postgresql+psycopg://localhost:5432/testdb",
                "username": "postgres",
                "password": "pw",
            },
            "migrations": {"directory": "./migrations", "table": "schema_version"},
            "logging": {"level": "INFO", "file": "dblift.log"},
        }
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            yaml.dump(d, f)
            fname = f.name
        config = DbliftConfig.from_file(fname)
        assert config.database.type == "postgresql"
        assert config.migrations.directory == "./migrations"
        assert config.logging.level == "INFO"
        os.remove(fname)

    def test_from_env_dict(self, monkeypatch):
        monkeypatch.setenv("DBLIFT_DB_URL", "postgresql+psycopg://localhost:5432/testdb")
        monkeypatch.setenv("DBLIFT_DB_USER", "postgres")
        monkeypatch.setenv("DBLIFT_DB_PASSWORD", "pw")
        env_dict = DbliftConfig.from_env_dict()
        assert env_dict["database"]["url"] == "postgresql+psycopg://localhost:5432/testdb"
        assert env_dict["database"]["username"] == "postgres"
        assert env_dict["database"]["password"] == "pw"

    def test_from_env_dict_cosmosdb_account_endpoint_and_key(self, monkeypatch):
        """BUG-D: CosmosDB env-only config requires ACCOUNT_ENDPOINT and ACCOUNT_KEY.

        Without these suffixes in the ``_ALLOWED`` allowlist, the env vars
        are silently discarded and CosmosDB can only be configured via a
        file — forcing users to create a ``dblift.yaml`` even when every
        other setting comes from the environment.
        """
        monkeypatch.setenv("DBLIFT_DB_TYPE", "cosmosdb")
        monkeypatch.setenv("DBLIFT_DB_ACCOUNT_ENDPOINT", "https://myacc.documents.azure.com")
        monkeypatch.setenv("DBLIFT_DB_ACCOUNT_KEY", "secret-key==")
        env_dict = DbliftConfig.from_env_dict()
        assert env_dict["database"]["type"] == "cosmosdb"
        assert env_dict["database"]["account_endpoint"] == "https://myacc.documents.azure.com"
        assert env_dict["database"]["account_key"] == "secret-key=="

    def test_merge(self):
        base = DbliftConfig.from_dict(
            {
                "database": {
                    "url": "postgresql+psycopg://localhost:5432/testdb",
                    "username": "postgres",
                    "password": "pw",
                },
                "migrations": {"directory": "m1", "table": "t1"},
                "logging": {"level": "INFO"},
            }
        )
        other = {
            "database": {
                "url": "postgresql+psycopg://otherhost:5432/otherdb",
                "username": "other",
                "password": "pw2",
            },
            "migrations": {"directory": "m2"},
            "logging": {"level": "DEBUG"},
            "dry_run": True,
        }
        base.merge(other)
        assert base.database.host == "otherhost"
        assert base.migrations.directory == "m2"
        assert base.logging.level == "DEBUG"
        assert base.dry_run is True

    def test_merge_applies_strict_mode_and_scalar_fields(self):
        base = DbliftConfig.from_dict(
            {
                "database": {
                    "url": "postgresql+psycopg://localhost:5432/testdb",
                    "username": "postgres",
                    "password": "pw",
                },
            }
        )
        assert base.strict_mode is False
        base.merge(
            {
                "strict_mode": True,
                "log_format": "json",
            }
        )
        assert base.strict_mode is True
        assert base.log_format == "json"

    def test_invalid_log_level(self):
        d = {
            "database": {
                "url": "postgresql+psycopg://localhost:5432/testdb",
                "username": "postgres",
                "password": "pw",
            },
            "logging": {"level": "NOTALEVEL"},
        }
        with pytest.raises(ValueError):
            DbliftConfig.from_dict(d)

    def test_from_all_sources_precedence(self, monkeypatch):
        # File has host=filehost, env has url with host=envhost
        d = {
            "database": {
                "url": "postgresql+psycopg://filehost:5432/testdb",
                "username": "postgres",
                "password": "pw",
            }
        }
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            yaml.dump(d, f)
            fname = f.name
        monkeypatch.setenv("DBLIFT_DB_URL", "postgresql+psycopg://envhost:5432/testdb")
        monkeypatch.setenv("DBLIFT_DB_USER", "postgres")
        monkeypatch.setenv("DBLIFT_DB_PASSWORD", "pw")
        args = {"config_file": fname}
        config = DbliftConfig.from_all_sources(args)
        assert config.database.host == "envhost"
        os.remove(fname)

    def test_migrations_and_logging_config(self):
        m = MigrationsConfig(directory="mydir", table="mytable")
        l = LoggingConfig(level="DEBUG", file="mylog.log")
        assert m.directory == "mydir"
        assert m.table == "mytable"
        assert l.level == "DEBUG"
        assert l.file == "mylog.log"

    def test_directory_config_from_string(self):
        """Test DirectoryConfig creation from string (backward compatibility)."""
        config = DirectoryConfig.from_dict("./migrations")
        assert config.path == "./migrations"
        assert config.recursive is True  # Default

    def test_directory_config_from_dict(self):
        """Test DirectoryConfig creation from dict with recursive setting."""
        config = DirectoryConfig.from_dict({"path": "./migrations", "recursive": False})
        assert config.path == "./migrations"
        assert config.recursive is False

    def test_directory_config_from_dict_default_recursive(self):
        """Test DirectoryConfig creation from dict without recursive (defaults to True)."""
        config = DirectoryConfig.from_dict({"path": "./migrations"})
        assert config.path == "./migrations"
        assert config.recursive is True

    def test_directory_config_from_dict_with_directory_alias(self):
        """Test DirectoryConfig accepts 'directory' as an alias for 'path'."""
        config = DirectoryConfig.from_dict({"directory": "./migrations"})
        assert config.path == "./migrations"

    def test_directory_config_from_dict_path_wins_over_directory_alias(self):
        """Test 'path' takes precedence when both 'path' and 'directory' are given."""
        config = DirectoryConfig.from_dict({"path": "./a", "directory": "./b"})
        assert config.path == "./a"

    def test_migrations_config_with_directories_list_strings(self):
        """Test MigrationsConfig with directories as list of strings (old format)."""
        config = MigrationsConfig(
            directories=["./migrations/core", "./migrations/features"], recursive=True
        )
        dir_configs = config.get_directory_configs()
        assert len(dir_configs) == 2
        assert dir_configs[0].path == "./migrations/core"
        assert dir_configs[0].recursive is True
        assert dir_configs[1].path == "./migrations/features"
        assert dir_configs[1].recursive is True

    def test_migrations_config_with_directories_list_dicts(self):
        """Test MigrationsConfig with directories as list of dicts (new format with per-directory recursive)."""
        config = MigrationsConfig(
            directories=[
                {"path": "./migrations/core", "recursive": True},
                {"path": "./migrations/features", "recursive": False},
            ],
            recursive=True,  # Global default
        )
        dir_configs = config.get_directory_configs()
        assert len(dir_configs) == 2
        assert dir_configs[0].path == "./migrations/core"
        assert dir_configs[0].recursive is True
        assert dir_configs[1].path == "./migrations/features"
        assert dir_configs[1].recursive is False

    def test_migrations_config_with_legacy_directory(self):
        """Test MigrationsConfig with legacy 'directory' field."""
        config = MigrationsConfig(directory="./migrations/core", recursive=False)
        dir_configs = config.get_directory_configs()
        assert len(dir_configs) == 1
        assert dir_configs[0].path == "./migrations/core"
        assert dir_configs[0].recursive is False

    def test_migrations_config_directories_override_directory(self):
        """Test that 'directories' field takes precedence over 'directory' field."""
        config = MigrationsConfig(
            directory="./old",
            directories=["./migrations/core", "./migrations/features"],
            recursive=True,
        )
        dir_configs = config.get_directory_configs()
        # When 'directories' is provided, 'directory' is ignored
        assert len(dir_configs) == 2
        assert dir_configs[0].path == "./migrations/core"
        assert dir_configs[1].path == "./migrations/features"

    def test_migrations_config_default(self):
        """Test MigrationsConfig with no directories configured (uses default)."""
        config = MigrationsConfig(recursive=True)
        dir_configs = config.get_directory_configs()
        assert len(dir_configs) == 1
        assert dir_configs[0].path == "migrations"
        assert dir_configs[0].recursive is True

    def test_config_loading_with_per_directory_recursive(self):
        """Test loading config file with per-directory recursive settings."""
        d = {
            "database": {
                "url": "postgresql+psycopg://localhost:5432/testdb",
                "username": "postgres",
                "password": "pw",
            },
            "migrations": {
                "directories": [
                    {"path": "./migrations/core", "recursive": True},
                    {"path": "./migrations/features", "recursive": False},
                ],
                "recursive": True,  # Global default
            },
        }
        config = DbliftConfig.from_dict(d)
        dir_configs = config.migrations.get_directory_configs()
        assert len(dir_configs) == 2
        assert dir_configs[0].path == "./migrations/core"
        assert dir_configs[0].recursive is True
        assert dir_configs[1].path == "./migrations/features"
        assert dir_configs[1].recursive is False

    def test_config_loading_mixed_format(self):
        """Test loading config with mixed string and dict directory formats."""
        d = {
            "database": {
                "url": "postgresql+psycopg://localhost:5432/testdb",
                "username": "postgres",
                "password": "pw",
            },
            "migrations": {
                "directories": [
                    "./migrations/core",  # String format
                    {"path": "./migrations/features", "recursive": False},  # Dict format
                ],
                "recursive": True,
            },
        }
        config = DbliftConfig.from_dict(d)
        dir_configs = config.migrations.get_directory_configs()
        assert len(dir_configs) == 2
        assert dir_configs[0].path == "./migrations/core"
        assert dir_configs[0].recursive is True  # Uses global default
        assert dir_configs[1].path == "./migrations/features"
        assert dir_configs[1].recursive is False


class TestUnrecognizedTopLevelKeys:
    def test_no_unrecognized_keys_for_known_config(self):
        d = {"database": {}, "migrations": {}, "logging": {}}
        assert unrecognized_top_level_keys(d) == []

    def test_flags_a_single_typo(self):
        d = {"database": {}, "migratoins_dir": "./migrations"}
        assert unrecognized_top_level_keys(d) == ["migratoins_dir"]

    def test_flags_multiple_unknown_keys_sorted(self):
        d = {"zzz_unknown": 1, "database": {}, "aaa_unknown": 2}
        assert unrecognized_top_level_keys(d) == ["aaa_unknown", "zzz_unknown"]

    def test_environment_section_keys_not_flagged(self):
        d = {"environments": {}, "resolve": {}}
        assert unrecognized_top_level_keys(d) == []

    def test_deprecated_migrations_dir_alias_not_flagged(self):
        d = {"migrations_dir": "./migrations"}
        assert unrecognized_top_level_keys(d) == []

    def test_non_dict_input_returns_no_keys(self):
        assert unrecognized_top_level_keys(None) == []
        assert unrecognized_top_level_keys([]) == []
