"""Tests for the CLI module."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from cli.db_utils import (
    check_connection,
    diagnose_connection,
    list_drivers,
    validate_config,
)
from config import DbliftConfig


@pytest.mark.unit
class TestCLI:
    """Test suite for CLI functionality."""

    @pytest.fixture
    def mock_provider_registry(self):
        """Mock the ProviderRegistry for testing."""
        with patch("cli.db_utils.ProviderRegistry") as mock:
            yield mock

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        config = MagicMock()
        config.database.type = "oracle"
        config.database.host = "localhost"
        config.database.port = 1521
        return config

    def test_list_drivers(self, mock_provider_registry, capsys):
        """Test the list_drivers command."""
        # Setup mock
        mock_provider_registry.get_available_drivers.return_value = {
            "oracle": True,
            "sqlserver": False,
            "postgresql": True,
        }

        # Create mock args
        args = MagicMock()

        # Execute command
        result = list_drivers(args)

        # Capture output
        captured = capsys.readouterr()

        # Verify results
        assert result == 0
        assert "Native Driver Status:" in captured.out
        assert "oracle" in captured.out
        assert "sqlserver" in captured.out
        assert "postgresql" in captured.out
        assert "available" in captured.out
        assert "missing" in captured.out

    def test_validate_config_success(self, mock_provider_registry, mock_config):
        """Test successful configuration validation."""
        # Setup mock
        mock_provider_registry.validate_database_configuration.return_value = (True, None)

        # Create mock args
        args = MagicMock()
        args.db_url = "oracle+oracledb://localhost:1521?service_name=XE"
        args.config = None  # force load_config path with no --config file
        args.get = lambda x, default=None: getattr(args, x, default)

        # Mock the database configuration
        mock_config = MagicMock(spec=DbliftConfig)
        mock_config.database = MagicMock()
        mock_config.database.type = "oracle"
        mock_config.database.url = args.db_url
        mock_config.database.host = "localhost"
        mock_config.database.port = 1521
        mock_config.database.database = "XE"

        # Execute command
        with patch("cli.db_utils.load_config", return_value=mock_config):
            result = validate_config(args)

        # Verify results
        assert result == 0
        mock_provider_registry.validate_database_configuration.assert_called_once_with(mock_config)

    def test_validate_config_failure(self, mock_provider_registry, mock_config):
        """Test failed configuration validation."""
        # Setup mock
        mock_provider_registry.validate_database_configuration.return_value = (
            False,
            "Invalid configuration",
        )

        # Create mock args
        args = MagicMock()
        args.db_url = "invalid://localhost:1521/XE"
        args.config = None  # force load_config path with no --config file
        args.get = lambda x, default=None: getattr(args, x, default)

        # Mock the database configuration
        mock_config = MagicMock(spec=DbliftConfig)
        mock_config.database = MagicMock()
        mock_config.database.type = "invalid"
        mock_config.database.url = args.db_url
        mock_config.database.host = "localhost"
        mock_config.database.port = 1521
        mock_config.database.database = "XE"

        # Execute command
        with patch("cli.db_utils.load_config", return_value=mock_config):
            result = validate_config(args)

        # Verify results
        assert result == 1

    def test_diagnose_connection_text_format(self, capsys):
        """Test native diagnostics in text format."""
        args = MagicMock()
        args.format = "text"

        result = diagnose_connection(args)
        captured = capsys.readouterr()

        assert result == 0
        assert "NATIVE DRIVER DIAGNOSTICS" in captured.out
        assert "Drivers:" in captured.out
        assert "Plugins:" in captured.out

    def test_diagnose_connection_json_format(self, capsys):
        """Test native diagnostics in JSON format."""
        args = MagicMock()
        args.format = "json"

        result = diagnose_connection(args)
        captured = capsys.readouterr()

        assert result == 0
        json_output = json.loads(captured.out)
        assert "drivers" in json_output
        assert "plugins" in json_output

    def test_test_connection_success(self, mock_provider_registry, capsys):
        """Test successful connection test."""
        # Setup mock
        mock_provider = MagicMock()
        mock_provider.test_connection.return_value = {
            "success": True,
            "connection_time": 0.1,
            "database_version": "1.0",
        }
        mock_provider.get_database_url.return_value = (
            "oracle+oracledb://localhost:1521?service_name=XE"
        )
        mock_provider.get_database_version.return_value = "1.0"
        mock_provider.create_connection.return_value = MagicMock()
        mock_provider_registry.create_provider.return_value = mock_provider

        # Create mock args
        args = MagicMock()
        args.db_url = "oracle+oracledb://localhost:1521?service_name=XE"
        args.format = "text"
        args.config = None  # force load_config path with no --config file
        args.get = lambda x, default=None: getattr(args, x, default)

        # Mock the database configuration
        mock_config = MagicMock(spec=DbliftConfig)
        mock_config.database = MagicMock()
        mock_config.database.type = "oracle"
        mock_config.database.url = args.db_url
        mock_config.database.host = "localhost"
        mock_config.database.port = 1521
        mock_config.database.database = "XE"
        mock_config.database.username = "test"
        mock_config.database.password = "test"
        mock_config.database.build_database_url.return_value = args.db_url

        # Execute command
        with patch("cli.db_utils.load_config", return_value=mock_config):
            with patch(
                "db.plugins.oracle.provider.OracleProvider",
                return_value=mock_provider,
            ):
                result = check_connection(args)

        # Capture output
        captured = capsys.readouterr()

        # Verify results
        assert result == 0
        assert "Connection successful" in captured.out
        assert "version: 1.0" in captured.out
        assert "database_url" in captured.out
        assert "db_type" in captured.out

    def test_test_connection_failure(self, mock_provider_registry, capsys):
        """Test failed connection test."""
        # Setup mock
        mock_provider = MagicMock()
        mock_provider.test_connection.return_value = {
            "success": False,
            "error": "Connection refused",
        }
        mock_provider.get_display_url.return_value = (
            "oracle+oracledb://invalid:1521?service_name=XE"
        )
        mock_provider.create_connection.side_effect = Exception("Connection refused")
        mock_provider_registry.create_provider.return_value = mock_provider

        # Create mock args
        args = MagicMock()
        args.db_url = "oracle+oracledb://invalid:1521?service_name=XE"
        args.format = "text"
        args.log_level = "info"
        args.config = None  # force load_config path with no --config file
        args.get = lambda x, default=None: getattr(args, x, default)

        # Mock the database configuration
        mock_config = MagicMock(spec=DbliftConfig)
        mock_config.database = MagicMock()
        mock_config.database.type = "oracle"
        mock_config.database.url = args.db_url
        mock_config.database.host = "invalid"
        mock_config.database.port = 1521
        mock_config.database.service_name = "XE"
        mock_config.database.username = "test"
        mock_config.database.password = "test"
        mock_config.database.build_database_url.return_value = args.db_url

        # Execute command
        with patch("cli.db_utils.load_config", return_value=mock_config):
            with patch(
                "db.plugins.oracle.provider.OracleProvider",
                return_value=mock_provider,
            ):
                result = check_connection(args)

        # Capture output
        captured = capsys.readouterr()

        # Verify results: BUG-03/-08 map "refused" to a friendly one-liner.
        assert result == 1
        assert "Connection failed" in captured.err
        assert "host unreachable" in captured.err

    def test_validate_config_with_native_url_credentials(self, mock_provider_registry):
        """Test configuration validation with credentials in native URL."""
        # Setup mock
        mock_provider_registry.validate_database_configuration.return_value = (True, None)

        # Create mock args with native URL containing credentials
        args = MagicMock()
        args.db_url = "oracle+oracledb://testuser:testpass@localhost:1521?service_name=XE"
        args.config = None  # force load_config path with no --config file
        args.get = lambda x, default=None: getattr(args, x, default)

        # Mock the database configuration
        mock_config = MagicMock(spec=DbliftConfig)
        mock_config.database = MagicMock()
        mock_config.database.type = "oracle"
        mock_config.database.url = args.db_url
        mock_config.database.host = "localhost"
        mock_config.database.port = 1521
        mock_config.database.database = "XE"
        mock_config.database.username = "testuser"
        mock_config.database.password = "testpass"

        # Execute command
        with patch("cli.db_utils.load_config", return_value=mock_config):
            result = validate_config(args)

        # Verify results
        assert result == 0
        mock_provider_registry.validate_database_configuration.assert_called_once_with(mock_config)

    def test_validate_config_with_cli_credentials(self, mock_provider_registry):
        """Test configuration validation with credentials from CLI parameters."""
        # Setup mock
        mock_provider_registry.validate_database_configuration.return_value = (True, None)

        # Create mock args with separate credential parameters
        args = MagicMock()
        args.db_url = "oracle+oracledb://localhost:1521?service_name=XE"
        args.db_username = "testuser"
        args.db_password = "testpass"
        args.config = None  # force load_config path with no --config file
        args.get = lambda x, default=None: getattr(args, x, default)

        # Mock the database configuration
        mock_config = MagicMock(spec=DbliftConfig)
        mock_config.database = MagicMock()
        mock_config.database.type = "oracle"
        mock_config.database.url = args.db_url
        mock_config.database.host = "localhost"
        mock_config.database.port = 1521
        mock_config.database.database = "XE"
        mock_config.database.username = "testuser"
        mock_config.database.password = "testpass"

        # Execute command
        with patch("cli.db_utils.load_config", return_value=mock_config):
            result = validate_config(args)

        # Verify results
        assert result == 0
        mock_provider_registry.validate_database_configuration.assert_called_once_with(mock_config)

    def test_validate_config_with_env_credentials(self, mock_provider_registry):
        """Test configuration validation with credentials from environment variables."""
        # Setup mock
        mock_provider_registry.validate_database_configuration.return_value = (True, None)

        # Create mock args
        args = MagicMock()
        args.db_url = "oracle+oracledb://localhost:1521?service_name=XE"
        args.config = None  # force load_config path with no --config file
        args.get = lambda x, default=None: getattr(args, x, default)

        # Mock the database configuration
        mock_config = MagicMock(spec=DbliftConfig)
        mock_config.database = MagicMock()
        mock_config.database.type = "oracle"
        mock_config.database.url = args.db_url
        mock_config.database.host = "localhost"
        mock_config.database.port = 1521
        mock_config.database.database = "XE"
        mock_config.database.username = "envuser"
        mock_config.database.password = "envpass"

        # Execute command with environment variables
        with patch.dict(os.environ, {"DBLIFT_DB_USER": "envuser", "DBLIFT_DB_PASSWORD": "envpass"}):
            with patch("cli.db_utils.load_config", return_value=mock_config):
                result = validate_config(args)

        # Verify results
        assert result == 0
        mock_provider_registry.validate_database_configuration.assert_called_once_with(mock_config)

    def test_validate_config_credential_precedence(self, mock_provider_registry):
        """Test that CLI credentials take precedence over database URL and environment variables."""
        # Setup mock
        mock_provider_registry.validate_database_configuration.return_value = (True, None)

        # Create mock args with all credential sources
        args = MagicMock()
        args.db_url = "oracle+oracledb://urluser:urlpass@localhost:1521?service_name=XE"
        args.db_username = "cliuser"
        args.db_password = "clipass"
        args.config = None  # force load_config path with no --config file
        args.get = lambda x, default=None: getattr(args, x, default)

        # Mock the database configuration
        mock_config = MagicMock(spec=DbliftConfig)
        mock_config.database = MagicMock()
        mock_config.database.type = "oracle"
        mock_config.database.url = args.db_url
        mock_config.database.host = "localhost"
        mock_config.database.port = 1521
        mock_config.database.database = "XE"
        mock_config.database.username = "cliuser"  # Should use CLI username
        mock_config.database.password = "clipass"  # Should use CLI password

        # Execute command with environment variables
        with patch.dict(os.environ, {"DBLIFT_DB_USER": "envuser", "DBLIFT_DB_PASSWORD": "envpass"}):
            with patch("cli.db_utils.load_config", return_value=mock_config):
                result = validate_config(args)

        # Verify results
        assert result == 0
        mock_provider_registry.validate_database_configuration.assert_called_once_with(mock_config)
        assert mock_config.database.username == "cliuser"
        assert mock_config.database.password == "clipass"

    @pytest.mark.sqlserver
    def test_validate_config_sqlserver_integrated_security(self, mock_provider_registry):
        """Test configuration validation with SQL Server integrated security."""
        # Setup mock
        mock_provider_registry.validate_database_configuration.return_value = (True, None)

        # Create mock args for SQL Server with integrated security
        args = MagicMock()
        args.db_url = "mssql+pymssql://localhost:1433/testdb?integrated_security=true"
        args.config = None  # force load_config path with no --config file
        args.get = lambda x, default=None: getattr(args, x, default)

        # Mock the database configuration
        mock_config = MagicMock(spec=DbliftConfig)
        mock_config.database = MagicMock()
        mock_config.database.type = "sqlserver"
        mock_config.database.url = args.db_url
        mock_config.database.host = "localhost"
        mock_config.database.port = 1433
        mock_config.database.database = "testdb"
        mock_config.database.integrated_security = True
        # Explicitly set username and password to None for integrated security
        mock_config.database.username = None
        mock_config.database.password = None

        # Execute command
        with patch("cli.db_utils.load_config", return_value=mock_config):
            result = validate_config(args)

        # Verify results
        assert result == 0
        mock_provider_registry.validate_database_configuration.assert_called_once_with(mock_config)
        assert mock_config.database.integrated_security is True
        # Username and password should be None with integrated security
        assert mock_config.database.username is None
        assert mock_config.database.password is None
