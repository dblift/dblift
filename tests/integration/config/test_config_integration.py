"""Integration tests for configuration system."""

import os
from pathlib import Path

import pytest
import yaml

from dblift.config import DbliftConfig


@pytest.mark.integration
class TestConfigDatabaseIntegration:
    """Test configuration system: loading, merging, precedence, validation, and parsing."""

    @pytest.fixture(scope="class")
    def test_config_dir(self):
        config_dir = Path("tests/integration/config/test_migrations")
        config_dir.mkdir(parents=True, exist_ok=True)
        yield config_dir

    @pytest.fixture(scope="class")
    def test_config_file(self, test_config_dir):
        config_path = test_config_dir / "test_config.yaml"
        config_data = {
            "database": {
                "type": "oracle",
                "url": "oracle+oracledb://localhost:1521?service_name=XE",
                "username": "system",
                "password": "oracle",
            },
            "migrations": {"directory": "./migrations", "table": "schema_version"},
            "logging": {"level": "INFO", "file": "dblift.log"},
        }
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)
        return config_path

    @pytest.fixture(scope="class")
    def test_env_vars(self):
        env_vars = {
            "DBLIFT_DB_URL": "oracle+oracledb://localhost:1521?service_name=XE",
            "DBLIFT_DB_USER": "system",
            "DBLIFT_DB_PASSWORD": "oracle",
        }
        original_env = dict(os.environ)
        os.environ.update(env_vars)
        yield env_vars
        os.environ.clear()
        os.environ.update(original_env)

    def test_load_from_file(self, test_config_file):
        config = DbliftConfig.from_file(test_config_file)
        assert config.database.type == "oracle"
        assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert config.database.username == "system"
        assert config.database.password == "oracle"
        assert config.migrations.directory == "./migrations"
        assert config.logging.level == "INFO"

    def test_load_from_env(self, test_env_vars):
        config = DbliftConfig.from_dict(DbliftConfig.from_env_dict())
        assert config.database.type == "oracle"
        assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert config.database.username == "system"
        assert config.database.password == "oracle"

    def test_precedence_env_over_file(self, test_config_file, test_env_vars):
        # Now, only URL, username, and password can be set via env
        # To test precedence, set a different URL in env and file, env should win
        os.environ["DBLIFT_DB_URL"] = "oracle+oracledb://envhost:1521?service_name=XE"
        config = DbliftConfig.from_all_sources({"config_file": str(test_config_file)})
        assert config.database.host == "envhost"
        del os.environ["DBLIFT_DB_URL"]

    def test_native_url_parsing(self):
        url = "mssql+pymssql://myhost:1433/mydb"
        config = DbliftConfig.from_dict(
            {"database": {"type": "sqlserver", "url": url, "username": "sa", "password": "pw"}}
        )
        assert config.database.host == "myhost"
        assert config.database.port == 1433
        assert config.database.database == "mydb"
        assert config.database.url == url

    def test_invalid_config_missing_url(self):
        with pytest.raises(ValueError):
            DbliftConfig.from_dict({"database": {"type": "oracle", "username": "system"}})

    def test_extra_params(self):
        url = "postgresql+psycopg://localhost:5432/testdb?sslmode=require&applicationName=myapp"
        config = DbliftConfig.from_dict(
            {
                "database": {
                    "type": "postgresql",
                    "url": url,
                    "username": "postgres",
                    "password": "pw",
                }
            }
        )
        assert config.database.host == "localhost"
        assert config.database.port == 5432
        assert config.database.database == "testdb"
        assert isinstance(config.database.extra_params, dict)
        keys = {k.lower() for k in config.database.extra_params.keys()}
        assert "sslmode" in keys
        assert "applicationname" in keys
        assert config.database.extra_params.get("sslmode") == "require"
        assert (
            config.database.extra_params.get("applicationName") == "myapp"
            or config.database.extra_params.get("applicationname") == "myapp"
        )

    def test_to_dict_and_roundtrip(self, test_config_file):
        config = DbliftConfig.from_file(test_config_file)
        d = config.database.to_dict()
        # Should be able to create a config from this dict
        config2 = DbliftConfig.from_dict({"database": d})
        assert config2.database.type == config.database.type
        assert config2.database.url == config.database.url
        assert config2.database.username == config.database.username
        assert config2.database.password == config.database.password

    def test_schema_and_service_name_parsing(self):
        url = "oracle+oracledb://localhost:1521?service_name=XE"
        config = DbliftConfig.from_dict(
            {"database": {"type": "oracle", "url": url, "username": "system", "password": "pw"}}
        )
        assert config.database.host == "localhost"
        assert config.database.port == 1521
        assert config.database.database == "XE"
        # Service name for Oracle should be set as database
        assert config.database.database == "XE"

    def test_config_validation(self):
        # Valid config
        url = "postgresql+psycopg://localhost:5432/testdb"
        config = DbliftConfig.from_dict(
            {
                "database": {
                    "type": "postgresql",
                    "url": url,
                    "username": "postgres",
                    "password": "pw",
                }
            }
        )
        assert config.database.host == "localhost"
        # Invalid config: missing url
        with pytest.raises(ValueError):
            DbliftConfig.from_dict(
                {"database": {"type": "postgresql", "username": "postgres", "password": "pw"}}
            )
        # Invalid config: missing username
        with pytest.raises(ValueError):
            DbliftConfig.from_dict(
                {"database": {"type": "postgresql", "url": url, "password": "pw"}}
            )
        # Invalid config: missing password
        with pytest.raises(ValueError):
            DbliftConfig.from_dict(
                {"database": {"type": "postgresql", "url": url, "username": "postgres"}}
            )
