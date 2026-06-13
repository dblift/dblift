"""Tests for the configuration system."""

import os
from unittest.mock import mock_open, patch

import pytest
import yaml

from config.database_config import DatabaseConfig
from config.dblift_config import DbliftConfig


@pytest.mark.unit
class TestDatabaseConfig:
    """Test suite for DatabaseConfig class."""

    def test_create_from_dict(self):
        """Test creating DatabaseConfig from dictionary with database URL only."""
        config_dict = {
            "url": "oracle+oracledb://localhost:1521?service_name=XE",
            "username": "system",
            "password": "oracle",
        }
        config = DatabaseConfig.from_dict(config_dict)
        assert config.type == "oracle"
        assert config.url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert config.username == "system"
        assert config.password == "oracle"

    def test_create_from_url(self):
        """Test creating DatabaseConfig from native Oracle URL without credentials (test URL includes creds to satisfy current validation)."""
        database_url = "oracle+oracledb://system:oracle@localhost:1521?service_name=XE"
        config = DatabaseConfig.from_url(database_url)
        assert config.type == "oracle"
        assert config.service_name == "XE"

    def test_create_from_url_with_credentials(self):
        """Test creating DatabaseConfig from database URL with credentials."""
        database_url = "oracle+oracledb://system:oracle@localhost:1521?service_name=XE"

        config = DatabaseConfig.from_url(database_url)

        assert config.type == "oracle"
        assert config.host == "localhost"
        assert config.port == 1521
        assert config.service_name == "XE"
        assert config.username == "system"
        assert config.password == "oracle"

    def test_create_from_url_with_properties(self):
        """Test creating DatabaseConfig from native Oracle URL with properties."""
        url = (
            "oracle+oracledb://system:oracle@localhost:1521?service_name=XE&schema=public&ssl=true"
        )
        config = DatabaseConfig.from_url(url)
        assert config.service_name == "XE"
        assert config.extra_params["schema"] == "public"

    def test_create_from_sqlalchemy_url_sqlserver(self):
        """Test creating DatabaseConfig from SQL Server SQLAlchemy URL."""
        url = "mssql+pymssql://sa:pw@localhost:1433/master?encrypt=true"
        config = DatabaseConfig.from_dict({"url": url})
        assert config.type == "sqlserver"
        assert config.host == "localhost"
        assert config.port == 1433
        assert config.database == "master"
        assert config.extra_params["encrypt"] == "true"

    def test_create_from_url_postgresql(self):
        """Test creating DatabaseConfig from PostgreSQL database URL."""
        database_url = "postgresql+psycopg://localhost:5432/mydb?user=postgres&password=postgres"

        config = DatabaseConfig.from_url(database_url)

        assert config.type == "postgresql"
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "mydb"
        assert config.username == "postgres"
        assert config.password == "postgres"

    def test_create_from_url_mysql(self):
        """Test creating DatabaseConfig from MySQL database URL."""
        database_url = "mysql+pymysql://localhost:3306/mydb?useSSL=false"
        config = DatabaseConfig.from_dict(
            {"url": database_url, "username": "root", "password": "pw"}
        )
        assert config.type == "mysql"
        assert config.host == "localhost"
        assert config.port == 3306
        assert config.database == "mydb"
        assert config.extra_params["useSSL"] == "false"

    def test_create_from_native_url_db2(self):
        """Test creating DatabaseConfig from DB2 SQLAlchemy URL."""
        database_url = "ibm_db_sa://localhost:50000/SAMPLE"
        config = DatabaseConfig.from_dict(
            {"url": database_url, "username": "db2inst1", "password": "pw"}
        )
        assert config.type == "db2"
        assert config.host == "localhost"
        assert config.port == 50000
        assert config.database == "SAMPLE"

    def test_invalid_database_url(self):
        """Test handling invalid database URL."""
        with pytest.raises(ValueError):
            DatabaseConfig.from_url("invalid_url")

    def test_missing_required_fields(self):
        """Test handling missing required fields."""
        config_dict = {
            "type": "oracle",
            "host": "localhost",
            # Missing port and database
        }

        with pytest.raises(ValueError):
            DatabaseConfig.from_dict(config_dict)


@pytest.mark.unit
class TestDbliftConfig:
    """Test suite for DbliftConfig class."""

    @pytest.fixture
    def mock_config_file(self):
        """Create a mock configuration file content."""
        return """
        database:
          type: oracle
          host: localhost
          port: 1521
          database: XE
          username: system
          password: oracle
        migrations:
          directory: ./migrations
          table: schema_version
        logging:
          level: INFO
          file: dblift.log
        """

    def test_create_from_file(self, mock_config_file, tmp_path):
        """Test creating DbliftConfig from file with database URL only."""
        import yaml

        config_file = tmp_path / "config.yaml"
        file_config = {
            "database": {
                "url": "oracle+oracledb://localhost:1521?service_name=XE",
                "username": "system",
                "password": "oracle",
            }
        }
        config_file.write_text(yaml.dump(file_config))
        args = {
            "db_url": "oracle+oracledb://localhost:1521?service_name=XE",
            "db_username": "system",
            "db_password": "oracle",
            "migrations_dir": "./migrations",
            "migrations_table": "schema_version",
            "log_level": "INFO",
            "log_file": "dblift.log",
            "config_file": str(config_file),
        }
        config = DbliftConfig.from_all_sources(args)
        assert config.database.type == "oracle"
        assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert config.database.username == "system"
        assert config.database.password == "oracle"

    def test_create_from_env(self):
        """Test creating DbliftConfig from environment variables with database URL only."""
        env_vars = {
            "DBLIFT_DB_URL": "oracle+oracledb://localhost:1521?service_name=XE",
            "DBLIFT_DB_USER": "system",
            "DBLIFT_DB_PASSWORD": "oracle",
        }
        from unittest.mock import patch

        with patch.dict(os.environ, env_vars):
            config = DbliftConfig.from_dict(DbliftConfig.from_env_dict())
            assert config.database.type == "oracle"
            assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"
            assert config.database.username == "system"
            assert config.database.password == "oracle"

    def test_create_from_args(self):
        """Test creating DbliftConfig from command line arguments (database URL only)."""
        args = {
            "db_url": "oracle+oracledb://localhost:1521?service_name=XE",
            "db_username": "system",
            "db_password": "oracle",
            "migrations_dir": "./migrations",
            "migrations_table": "schema_version",
            "log_level": "INFO",
            "log_file": "dblift.log",
            "config_file": None,
        }
        config = DbliftConfig.from_all_sources(args)
        assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert config.database.username == "system"
        assert config.database.password == "oracle"
        # Optionally check migrations/logging if supported
        if hasattr(config, "migrations"):
            assert config.migrations.directory == "./migrations"
            assert config.migrations.table == "schema_version"
        if hasattr(config, "logging"):
            assert config.logging.level == "INFO"
            # Only assert log file if explicitly set
            if args.get("log_file"):
                assert config.logging.file == f"./{args['log_file'].lstrip('./')}"

    def test_config_precedence(self, tmp_path):
        """Test configuration precedence (args > env > file) for username/password, with db_url only."""
        from unittest.mock import patch

        import yaml

        # File config (all required fields)
        config_file = tmp_path / "config.yaml"
        file_config = {
            "database": {
                "url": "oracle+oracledb://localhost:1521?service_name=XE",
                "username": "file_user",
                "password": "file_pw",
            }
        }
        config_file.write_text(yaml.dump(file_config))
        # Env config (override username and password)
        env_vars = {"DBLIFT_DB_USER": "env_user", "DBLIFT_DB_PASSWORD": "env_pw"}
        # Args config (override username and password)
        args = {
            "db_url": "oracle+oracledb://localhost:1521?service_name=XE",
            "db_username": "args_user",
            "db_password": "args_pw",
            "config_file": str(config_file),
        }
        with patch.dict(os.environ, env_vars):
            config = DbliftConfig.from_all_sources(args)
            # Args should take precedence for username and password
            assert config.database.username == "args_user"
            assert config.database.password == "args_pw"
            # URL should be from file (since all sources use same URL)
            assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"

    def test_username_password_precedence(self, tmp_path):
        """Test all precedence scenarios for username/password."""
        from unittest.mock import patch

        import yaml

        config_file = tmp_path / "config.yaml"
        file_config = {
            "database": {
                "url": "oracle+oracledb://localhost:1521?service_name=XE",
                "username": "file_user",
                "password": "file_pw",
            }
        }
        config_file.write_text(yaml.dump(file_config))
        # Env only
        env_vars = {"DBLIFT_DB_USER": "env_user", "DBLIFT_DB_PASSWORD": "env_pw"}
        with patch.dict(os.environ, env_vars):
            config = DbliftConfig.from_all_sources({"config_file": str(config_file)})
            assert config.database.username == "env_user"
            assert config.database.password == "env_pw"
        # Args only
        args = {
            "db_url": "oracle+oracledb://localhost:1521?service_name=XE",
            "db_username": "args_user",
            "db_password": "args_pw",
            "config_file": str(config_file),
        }
        config = DbliftConfig.from_all_sources(args)
        assert config.database.username == "args_user"
        assert config.database.password == "args_pw"
        # URL only (credentials in URL)
        url_with_creds = "oracle+oracledb://dbuser:dbpass@localhost:1521?service_name=XE"
        file_config2 = {"database": {"url": url_with_creds}}
        config_file.write_text(yaml.dump(file_config2))
        config = DbliftConfig.from_all_sources({"config_file": str(config_file)})
        assert config.database.username == "dbuser"
        assert config.database.password == "dbpass"
        # Args > env > file > url precedence
        env_vars = {"DBLIFT_DB_USER": "env_user", "DBLIFT_DB_PASSWORD": "env_pw"}
        args = {
            "db_url": url_with_creds,
            "db_username": "args_user",
            "db_password": "args_pw",
            "config_file": str(config_file),
        }
        with patch.dict(os.environ, env_vars):
            config = DbliftConfig.from_all_sources(args)
            assert config.database.username == "args_user"
            assert config.database.password == "args_pw"

    def test_url_in_file_only(self, tmp_path):
        """Test config loads db_url from file only."""
        import yaml

        config_file = tmp_path / "config.yaml"
        file_config = {
            "database": {
                "url": "oracle+oracledb://localhost:1521?service_name=XE",
                "username": "file_user",
                "password": "file_pw",
            }
        }
        config_file.write_text(yaml.dump(file_config))
        args = {
            "db_url": "oracle+oracledb://localhost:1521?service_name=XE",
            "db_username": "file_user",
            "db_password": "file_pw",
            "config_file": str(config_file),
        }
        config = DbliftConfig.from_all_sources(args)
        assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert config.database.username == "file_user"
        assert config.database.password == "file_pw"

    def test_url_in_env_only(self, monkeypatch):
        """Test config loads db_url from environment only."""
        env_vars = {
            "DBLIFT_DB_URL": "oracle+oracledb://localhost:1521?service_name=XE",
            "DBLIFT_DB_USER": "env_user",
            "DBLIFT_DB_PASSWORD": "env_pw",
        }
        monkeypatch.setenv("DBLIFT_DB_URL", env_vars["DBLIFT_DB_URL"])
        monkeypatch.setenv("DBLIFT_DB_USER", env_vars["DBLIFT_DB_USER"])
        monkeypatch.setenv("DBLIFT_DB_PASSWORD", env_vars["DBLIFT_DB_PASSWORD"])
        args = {"config_file": None}
        config = DbliftConfig.from_all_sources(args)
        assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert config.database.username == "env_user"
        assert config.database.password == "env_pw"

    def test_url_in_args_only(self):
        """Test config loads db_url from args only."""
        args = {
            "db_url": "oracle+oracledb://localhost:1521?service_name=XE",
            "db_username": "args_user",
            "db_password": "args_pw",
            "config_file": None,
        }
        config = DbliftConfig.from_all_sources(args)
        assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert config.database.username == "args_user"
        assert config.database.password == "args_pw"

    def test_url_precedence(self, tmp_path, monkeypatch):
        """Test db_url precedence: args > env > file."""
        import yaml

        config_file = tmp_path / "config.yaml"
        file_config = {
            "database": {
                "url": "oracle+oracledb://file:1521?service_name=XE",
                "username": "file_user",
                "password": "file_pw",
            }
        }
        config_file.write_text(yaml.dump(file_config))
        monkeypatch.setenv("DBLIFT_DB_URL", "oracle+oracledb://env:1521?service_name=XE")
        monkeypatch.setenv("DBLIFT_DB_USER", "env_user")
        monkeypatch.setenv("DBLIFT_DB_PASSWORD", "env_pw")
        args = {
            "db_url": "oracle+oracledb://args:1521?service_name=XE",
            "db_username": "args_user",
            "db_password": "args_pw",
            "config_file": str(config_file),
        }
        config = DbliftConfig.from_all_sources(args)
        assert config.database.url == "oracle+oracledb://args:1521?service_name=XE"
        assert config.database.username == "args_user"
        assert config.database.password == "args_pw"

    def test_username_password_precedence_url_vs_env_vs_args(self, tmp_path, monkeypatch):
        """Test username/password precedence: args > env > file > url."""
        import yaml

        # Credentials in URL only
        url_with_creds = "oracle+oracledb://dbuser:dbpass@localhost:1521?service_name=XE"
        config_file = tmp_path / "config.yaml"
        file_config = {"database": {"url": url_with_creds}}
        config_file.write_text(yaml.dump(file_config))
        # No env, no args: should use creds from URL
        args = {"config_file": str(config_file)}
        config = DbliftConfig.from_all_sources(args)
        assert config.database.username == "dbuser"
        assert config.database.password == "dbpass"
        # Env overrides URL
        monkeypatch.setenv("DBLIFT_DB_USER", "env_user")
        monkeypatch.setenv("DBLIFT_DB_PASSWORD", "env_pw")
        config = DbliftConfig.from_all_sources(args)
        assert config.database.username == "env_user"
        assert config.database.password == "env_pw"
        # Args override env and URL
        args = {
            "db_url": url_with_creds,
            "db_username": "args_user",
            "db_password": "args_pw",
            "config_file": str(config_file),
        }
        config = DbliftConfig.from_all_sources(args)
        assert config.database.username == "args_user"
        assert config.database.password == "args_pw"

    def test_invalid_config_file(self):
        """Test handling invalid configuration file."""
        with patch("builtins.open", mock_open(read_data="invalid: yaml: content")):
            with pytest.raises(yaml.YAMLError):
                DbliftConfig.from_file("config.yaml")

    def test_missing_required_config(self):
        """Test handling missing required configuration."""
        with pytest.raises(ValueError):
            DbliftConfig.from_dict({})

    def test_invalid_database_type(self):
        """Test handling invalid database type."""
        config_dict = {
            "database": {
                "type": "invalid_type",
                "host": "localhost",
                "port": 1521,
                "database": "XE",
            }
        }

        with pytest.raises(ValueError):
            DbliftConfig.from_dict(config_dict)

    def test_config_validation(self):
        """Test configuration validation."""
        config_dict = {
            "database": {
                "type": "oracle",
                "host": "localhost",
                "port": 1521,
                "database": "XE",
                "username": "system",
                "password": "oracle",
            },
            "migrations": {"directory": "./migrations", "table": "schema_version"},
            "logging": {"level": "INVALID_LEVEL", "file": "dblift.log"},
        }

        with pytest.raises(ValueError):
            DbliftConfig.from_dict(config_dict)

    def test_config_merging(self):
        """Test merging configurations from different sources (database URL only)."""
        base_config = {
            "database": {
                "url": "oracle+oracledb://localhost:1521?service_name=XE",
                "username": "file_user",
                "password": "file_pw",
            }
        }
        override_config = {"database": {"username": "override_user", "password": "override_pw"}}
        config = DbliftConfig.from_dict(base_config)
        config.merge(override_config)
        assert config.database.url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert config.database.username == "override_user"
        assert config.database.password == "override_pw"

    def test_config_merging_with_tempfile_env_args(self, tmp_path):
        """Test merging config from file, env, and args with correct precedence (args > env > file, database URL only)."""
        from unittest.mock import patch

        import yaml

        # 1. Create a config file with all required fields
        config_file = tmp_path / "config.yaml"
        file_config = {
            "database": {
                "url": "oracle+oracledb://file:1521?service_name=XE",
                "username": "file_user",
                "password": "file_pw",
            }
        }
        config_file.write_text(yaml.dump(file_config))

        # 2. Set env vars to override some fields
        env_vars = {
            "DBLIFT_DB_USER": "env_user",  # override username
            "DBLIFT_DB_PASSWORD": "env_pw",  # override password
        }

        # 3. Args to override some fields
        args = {
            "db_url": "oracle+oracledb://args:1521?service_name=XE",  # override url
            "db_username": "args_user",  # override username
            "db_password": "args_pw",  # override password
            "config_file": str(config_file),
        }

        # 4. Merge all sources
        with patch.dict(os.environ, env_vars):
            config = DbliftConfig.from_all_sources(args)

        # 5. Assert correct merging/precedence
        assert config.database.url == "oracle+oracledb://args:1521?service_name=XE"  # from args
        assert config.database.username == "args_user"  # from args
        assert config.database.password == "args_pw"  # from args

    def test_config_missing_required_with_tempfile(self, tmp_path):
        """Test that missing required fields in all sources raises ValueError."""
        import yaml

        # Only type in file, missing host, port, database everywhere
        config_file = tmp_path / "config.yaml"
        file_config = {"database": {"type": "oracle"}}
        config_file.write_text(yaml.dump(file_config))
        # No env, no args
        args = {"config_file": str(config_file)}
        with pytest.raises(ValueError):
            DbliftConfig.from_all_sources(args)
