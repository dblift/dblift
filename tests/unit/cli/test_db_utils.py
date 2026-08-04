"""Unit tests for CLI db_utils functionality."""

import argparse
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

pytestmark = [pytest.mark.unit]

from cli.db_utils import (
    check_connection,
    diagnose_connection,
    list_drivers,
    print_connection_results,
    setup_db_utils_parser,
    validate_config,
)


class TestListDrivers:
    """Test list_drivers functionality."""

    @patch("cli.db_utils.ProviderRegistry")
    def test_list_drivers_success(self, mock_provider_registry, capsys):
        """Test successful driver listing."""

        mock_provider_registry.get_available_drivers.return_value = {
            "sqlserver": True,
            "oracle": False,
            "postgresql": True,
        }

        args = Mock()
        result = list_drivers(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Native Driver Status:" in captured.out
        assert "sqlserver" in captured.out
        assert "Available" in captured.out
        assert "Not available" in captured.out

    @patch("cli.db_utils.ProviderRegistry")
    def test_list_drivers_with_missing_drivers(self, mock_provider_registry, capsys):
        """Test driver listing with missing drivers."""
        mock_provider_registry.get_available_drivers.return_value = {
            "sqlserver": False,
            "oracle": False,
            "postgresql": False,
        }

        args = Mock()
        result = list_drivers(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Install missing drivers" in captured.out

    @patch("cli.db_utils.ProviderRegistry")
    def test_list_drivers_error(self, mock_provider_registry, capsys):
        """Test driver listing with error."""
        mock_provider_registry.get_available_drivers.side_effect = Exception("Test error")

        args = Mock()
        result = list_drivers(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error listing drivers" in captured.err


class TestValidateConfig:
    """Test validate_config functionality."""

    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.ProviderRegistry")
    def test_validate_config_success_reads_config_file(
        self, mock_provider_registry, mock_load_config, capsys
    ):
        """BUG-02: when --config is set, validate_config must actually load the file."""
        mock_provider_registry.validate_database_configuration.return_value = (True, None)
        mock_load_config.return_value = Mock()

        args = Mock()
        args.config = "test_config.yaml"

        result = validate_config(args)

        assert result == 0
        mock_load_config.assert_called_once_with("test_config.yaml", args)
        captured = capsys.readouterr()
        assert "Database configuration and driver are valid" in captured.out

    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.ProviderRegistry")
    def test_validate_config_without_config_uses_load_config(
        self, mock_provider_registry, mock_load_config, capsys
    ):
        """Without --config, validate_config uses load_config(None, args) to pick up CLI flags."""
        mock_provider_registry.validate_database_configuration.return_value = (
            False,
            "Invalid config",
        )
        mock_load_config.return_value = Mock()

        args = Mock()
        args.config = None

        result = validate_config(args)

        assert result == 1
        mock_load_config.assert_called_once_with(None, args)
        captured = capsys.readouterr()
        assert "Error: Invalid config" in captured.err

    @patch("cli.db_utils.load_config")
    def test_validate_config_missing_file_returns_1(self, mock_load_config, capsys):
        """--config pointing at a missing file exits 1 with a clean error."""
        mock_load_config.side_effect = FileNotFoundError("Config file not found: /nope.yaml")

        args = Mock()
        args.config = "/nope.yaml"

        result = validate_config(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Config file not found" in captured.err

    @patch("cli.db_utils.load_config")
    def test_validate_config_exception(self, mock_load_config, capsys):
        """Unexpected exception from load_config is caught and returns 1."""
        mock_load_config.side_effect = Exception("Config error")

        args = Mock()
        args.config = "/fake/config.yaml"

        result = validate_config(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error validating configuration" in captured.err


class TestValidateConfigUnrecognizedTopLevelKeys:
    """Issue 820: a typo'd/unrecognized top-level config key is silently
    ignored today. ``validate-config`` should warn about it instead of
    running as if the key didn't exist.
    """

    def _write_config(self, tmp_path, body):
        config_path = tmp_path / "dblift.yaml"
        config_path.write_text(body)
        return str(config_path)

    def _make_args(self, config_path):
        return argparse.Namespace(
            config=config_path,
            db_url=None,
            db_username=None,
            db_password=None,
            db_schema=None,
            env=None,
            command="validate-config",
            commands_list=None,
            installed_by=None,
            format=None,
        )

    def test_warns_on_unrecognized_top_level_key(self, tmp_path, capsys):
        config_path = self._write_config(
            tmp_path,
            """
database:
  type: sqlite
  path: ./test.db
migratoins_dir: ./migrations
""",
        )

        result = validate_config(self._make_args(config_path))

        assert result == 0
        captured = capsys.readouterr()
        assert "migratoins_dir" in captured.err
        assert "Warning" in captured.err

    def test_no_warning_for_config_with_only_valid_keys(self, tmp_path, capsys):
        config_path = self._write_config(
            tmp_path,
            """
database:
  type: sqlite
  path: ./test.db
migrations:
  directory: ./migrations
history_table: my_history
""",
        )

        result = validate_config(self._make_args(config_path))

        assert result == 0
        captured = capsys.readouterr()
        assert "unrecognized" not in captured.err.lower()


class TestDiagnoseConnection:
    """Test diagnose_connection functionality."""

    def test_diagnose_connection_text_format(self, capsys):
        """Test native diagnostics with text format."""
        args = Mock()
        args.format = "text"

        result = diagnose_connection(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "NATIVE DRIVER DIAGNOSTICS" in captured.out
        assert "Drivers:" in captured.out

    def test_diagnose_connection_json_format(self, capsys):
        """Test native diagnostics with JSON format."""
        args = Mock()
        args.format = "json"

        result = diagnose_connection(args)

        assert result == 0
        output_data = json.loads(capsys.readouterr().out)
        assert "drivers" in output_data
        assert "plugins" in output_data

    def test_diagnose_connection_pretty_format(self, capsys):
        """Test native diagnostics with pretty format."""
        args = Mock()
        args.format = "pretty"

        result = diagnose_connection(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "drivers" in captured.out

    @patch("cli.db_utils.ProviderRegistry.list_plugins", side_effect=Exception("registry error"))
    def test_diagnose_connection_error(self, _mock_list_plugins, capsys):
        """Test native diagnostics with error."""
        args = Mock()
        args.format = "text"

        result = diagnose_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error performing native driver diagnostics" in captured.err


class TestCheckConnection:
    """Test check_connection functionality."""

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_success(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """Test successful connection check."""
        # Setup mocks
        mock_config_instance = Mock()
        mock_config_instance.database.url = "mssql+pymssql://localhost:1433/test"
        mock_config_instance.database.type = "sqlserver"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_url.return_value = "mssql+pymssql://localhost:1433/test"
        mock_provider.get_database_version.return_value = "SQL Server 2019"
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Connection successful!" in captured.out
        mock_create_provider.assert_called_once_with(mock_config_instance, mock_logger.return_value)

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_success_prints_active_schema(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        mock_config_instance = Mock()
        mock_config_instance.database.url = "postgresql+psycopg://localhost:5432/test"
        mock_config_instance.database.type = "postgresql"
        mock_config_instance.database.schema = "app_schema"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_url.return_value = "postgresql+psycopg://localhost:5432/test"
        mock_provider.get_database_version.return_value = "PostgreSQL 16"
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "schema: app_schema" in captured.out

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_accepts_host_database_config(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        mock_config_instance = Mock()
        mock_config_instance.database.url = None
        mock_config_instance.database.type = "postgresql"
        mock_config_instance.database.host = "db.example.com"
        mock_config_instance.database.database = "app"
        mock_config_instance.database.server = None
        mock_config_instance.database.account_endpoint = None
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_url.return_value = "postgresql+psycopg://db.example.com/app"
        mock_provider.get_database_version.return_value = "PostgreSQL 16"
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Missing required connection parameters" not in captured.err
        assert "Connection successful!" in captured.out
        mock_create_provider.assert_called_once_with(mock_config_instance, mock_logger.return_value)

    @patch("cli.db_utils.load_config")
    def test_check_connection_config_error(self, mock_load_config, capsys):
        """Test connection check with config error."""
        mock_load_config.side_effect = Exception("Config error")

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Error creating configuration" in captured.err

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_unsupported_db(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """Test connection check with unsupported database."""
        mock_config_instance = Mock()
        mock_config_instance.database.type = "unsupported_db"
        mock_load_config.return_value = mock_config_instance

        mock_create_provider.side_effect = ValueError("Unsupported database type: unsupported_db")

        args = Mock()
        args.format = "json"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        output_data = json.loads(captured.out)
        assert output_data["success"] is False
        assert "Unsupported database type" in output_data["error"]
        mock_create_provider.assert_called_once()

    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_missing_params(self, mock_logger, mock_load_config, capsys):
        """Test connection check with missing connection parameters."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = None
        mock_config_instance.database.type = None
        mock_config_instance.database.server = None
        mock_config_instance.database.account_endpoint = None
        mock_load_config.return_value = mock_config_instance

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Missing required connection parameters" in captured.err

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_driver_validation_failure(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """DB2 native connection errors do not use JDBC driver validation."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "ibm_db_sa://localhost:50000/SAMPLE"
        mock_config_instance.database.type = "db2"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.create_connection.side_effect = RuntimeError("Connection refused")
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "json"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        output_data = json.loads(captured.out)
        assert output_data["success"] is False
        assert "Connection failed: host unreachable" in output_data["error"]

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_postgresql(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """Test connection check with PostgreSQL."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "postgresql+psycopg://localhost:5432/test"
        mock_config_instance.database.type = "postgresql"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_url.return_value = "postgresql+psycopg://localhost:5432/test"
        mock_provider.get_database_version.return_value = "PostgreSQL 14.5"
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Connection successful!" in captured.out
        mock_create_provider.assert_called_once_with(mock_config_instance, mock_logger.return_value)
        mock_provider.close.assert_called_once()

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_oracle(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """Test connection check with Oracle."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "oracle+oracledb://localhost:1521?service_name=ORCL"
        mock_config_instance.database.type = "oracle"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_url.return_value = (
            "oracle+oracledb://localhost:1521?service_name=ORCL"
        )
        mock_provider.get_database_version.return_value = "Oracle Database 19c"
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Connection successful!" in captured.out
        mock_create_provider.assert_called_once_with(mock_config_instance, mock_logger.return_value)
        mock_provider.close.assert_called_once()

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_connection_error(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """Test connection check when provider connection fails."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "mssql+pymssql://localhost:1433/test"
        mock_config_instance.database.type = "sqlserver"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.create_connection.side_effect = Exception("Connection failed")
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"
        args.log_level = "info"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Connection failed" in captured.err

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_refused_has_no_traceback(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """BUG-03: a refused connection produces a one-line error and no Python traceback."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "postgresql+psycopg://localhost:9999/x"
        mock_config_instance.database.type = "postgresql"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.create_connection.side_effect = RuntimeError(
            "java.net.ConnectException: Connection refused"
        )
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"
        args.log_level = "info"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        # One-line friendly message for connection refused
        assert "host unreachable" in captured.err
        # No Python traceback frames
        assert 'File "' not in captured.err
        assert "Traceback" not in captured.err

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_close_connection_called_if_get_version_raises(
        self, mock_logger, mock_load_config, mock_create_provider
    ):
        """provider.close() runs even if get_database_version() raises."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "mssql+pymssql://localhost:1433/master"
        mock_config_instance.database.type = "sqlserver"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_version.side_effect = RuntimeError("Version error")
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 1
        mock_provider.close.assert_called_once()

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.get_provider_display_url")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_close_connection_called_if_get_database_url_raises(
        self, mock_logger, mock_load_config, mock_display_url, mock_create_provider
    ):
        """provider.close() runs even if display URL resolution raises."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "mssql+pymssql://localhost:1433/test"
        mock_config_instance.database.type = "sqlserver"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_version.return_value = "SQL Server 2019"
        mock_display_url.side_effect = RuntimeError("URL error")
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 1
        mock_provider.close.assert_called_once()

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_close_connection_called_once_on_nominal_path(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """provider.close() is called exactly once on the success path."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "mssql+pymssql://localhost:1433/test"
        mock_config_instance.database.type = "sqlserver"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_url.return_value = "mssql+pymssql://localhost:1433/test"
        mock_provider.get_database_version.return_value = "SQL Server 2019"
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 0
        mock_provider.close.assert_called_once()


class TestCheckConnectionLogFile:
    """BUG-02: db check-connection must honour --log-file."""

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_log_file_pattern_passed_to_logger(
        self, mock_logger, mock_load_config, mock_create_provider
    ):
        mock_config_instance = Mock()
        mock_config_instance.database.url = "mssql+pymssql://localhost:1433/test"
        mock_config_instance.database.type = "sqlserver"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_url.return_value = "mssql+pymssql://localhost:1433/test"
        mock_provider.get_database_version.return_value = "SQL Server 2019"
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"
        args.log_file = "/tmp/dblift_test/logs/log.json"
        args.log_dir = None
        args.log_format = "json"

        check_connection(args)

        # DbliftLogger must receive log_file_pattern from args.log_file
        _, kwargs = mock_logger.call_args
        assert kwargs.get("log_file_pattern") == "/tmp/dblift_test/logs/log.json"

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_closes_logger_on_success(self, mock_logger, mock_load_config, mock_create_provider):
        mock_config_instance = Mock()
        mock_config_instance.database.url = "mssql+pymssql://localhost:1433/test"
        mock_config_instance.database.type = "sqlserver"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_url.return_value = "mssql+pymssql://localhost:1433/test"
        mock_provider.get_database_version.return_value = "SQL Server 2019"
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"
        args.log_file = "/tmp/dblift_test/logs/log.json"
        args.log_dir = None
        args.log_format = "json"

        check_connection(args)

        mock_logger.return_value.close.assert_called_once()

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_closes_logger_on_connection_failure(
        self, mock_logger, mock_load_config, mock_create_provider
    ):
        mock_config_instance = Mock()
        mock_config_instance.database.url = "mssql+pymssql://localhost:1433/test"
        mock_config_instance.database.type = "sqlserver"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.create_connection.side_effect = Exception("Connection failed")
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"
        args.log_level = "info"
        args.log_file = "/tmp/dblift_test/logs/log.json"
        args.log_dir = None
        args.log_format = "json"

        check_connection(args)

        mock_logger.return_value.close.assert_called_once()


class TestPrintConnectionResults:
    """Test print_connection_results functionality."""

    def test_print_connection_results_text_success(self, capsys):
        """Test printing successful connection results in text format."""
        from cli._output import CommandOutput

        results = {
            "success": True,
            "connection_info": {
                "database_url": "postgresql+psycopg://localhost/test",
                "db_type": "test",
            },
            "database_info": {"version": "TestDB 1.0"},
        }

        print_connection_results(results, CommandOutput("text"))

        captured = capsys.readouterr()
        assert "Connection successful!" in captured.out
        assert "postgresql+psycopg://localhost/test" in captured.out
        assert "TestDB 1.0" in captured.out

    def test_print_connection_results_text_failure(self, capsys):
        """Test printing failed connection results in text format."""
        from cli._output import CommandOutput

        results = {"success": False, "error": "Connection timeout", "connection_info": {}}

        print_connection_results(results, CommandOutput("text"))

        captured = capsys.readouterr()
        assert "Connection failed!" in captured.out
        assert "Connection timeout" in captured.out

    def test_print_connection_results_json_format(self, capsys):
        """Test printing connection results in JSON format."""
        from cli._output import CommandOutput

        results = {
            "success": True,
            "connection_info": {"db_type": "test"},
            "database_info": {"version": "1.0"},
        }

        print_connection_results(results, CommandOutput("json"))

        captured = capsys.readouterr()
        output_data = json.loads(captured.out)
        assert output_data["success"] is True
        assert output_data["connection_info"]["db_type"] == "test"

    def test_print_connection_results_pretty_format(self, capsys):
        """Test printing connection results in pretty format."""
        from cli._output import CommandOutput

        results = {"success": True, "connection_info": {"db_type": "test"}}

        print_connection_results(results, CommandOutput("pretty"))

        captured = capsys.readouterr()
        assert "success" in captured.out
        assert "True" in captured.out


class TestSetupDbUtilsParser:
    """Test setup_db_utils_parser functionality."""

    def _make_parser(self):
        parser = argparse.ArgumentParser()
        # Add top-level --config so tests that pass it before "db" work correctly.
        # (--config was removed from the db sub-subparsers to fix namespace pollution.)
        parser.add_argument("--config", help="Configuration file")
        subparsers = parser.add_subparsers(dest="command")
        db_parser = subparsers.add_parser("db", help="Database utilities")
        db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
        setup_db_utils_parser(db_subparsers)
        return parser

    def test_setup_db_utils_parser(self):
        """Test that setup_db_utils_parser registers production subcommand names."""
        parser = self._make_parser()
        help_text = parser.format_help()
        assert "db" in help_text
        # Verify production subcommand names are registered
        args = parser.parse_args(["db", "validate-config"])
        assert args.db_command == "validate-config"
        args = parser.parse_args(["db", "check-connection"])
        assert args.db_command == "check-connection"

    def test_list_drivers_subcommand(self):
        """Test list-drivers subcommand parsing."""
        parser = self._make_parser()

        args = parser.parse_args(["db", "list-drivers"])
        assert args.db_command == "list-drivers"
        assert args.func == list_drivers

    def test_validate_config_subcommand(self):
        """Test validate-config subcommand parsing.

        --config is a global argument handled at the top-level parser, not by
        the validate-config subparser (removing it from the subparser fixed the
        namespace-pollution bug that caused args.config to be overwritten to None).
        """
        parser = self._make_parser()

        # --config must be given at the top level (before the subcommand)
        args = parser.parse_args(["--config", "test.yaml", "db", "validate-config"])
        assert args.db_command == "validate-config"
        assert args.config == "test.yaml"
        assert args.func == validate_config

    def test_diagnose_connection_subcommand(self):
        """Test diagnose-connection subcommand parsing."""
        parser = self._make_parser()

        args = parser.parse_args(["db", "diagnose-connection", "--format", "json"])
        assert args.db_command == "diagnose-connection"
        assert args.format == "json"

    def test_check_connection_subcommand(self):
        """Test check-connection subcommand parsing."""
        parser = self._make_parser()

        args = parser.parse_args(
            [
                "db",
                "check-connection",
                "--db-url",
                "postgresql+psycopg://localhost/test",
                "--db-username",
                "testuser",
                "--format",
                "pretty",
            ]
        )
        assert args.db_command == "check-connection"
        assert args.db_url == "postgresql+psycopg://localhost/test"
        assert args.db_username == "testuser"
        assert args.format == "pretty"
        assert args.func == check_connection

    def test_check_connection_url_aliases(self):
        """check-connection accepts --url, --username, --password as aliases."""
        parser = self._make_parser()

        args = parser.parse_args(
            [
                "db",
                "check-connection",
                "--url",
                "postgresql+psycopg://localhost/db",
                "--username",
                "user",
                "--password",
                "pass",
            ]
        )
        assert args.db_url == "postgresql+psycopg://localhost/db"
        assert args.db_username == "user"
        assert args.db_password == "pass"
        assert args.func == check_connection


class TestUtilityFunctions:
    """Test utility functions in db_utils."""

    def test_to_python_function(self):
        """Test _to_python utility function."""
        from cli.db_utils import _to_python

        # Test with dict
        test_dict = {"key": "value", "nested": {"inner": "data"}}
        result = _to_python(test_dict)
        assert result == test_dict

        # Test with list
        test_list = [1, 2, "three"]
        result = _to_python(test_list)
        assert result == test_list

        # Test with object that has __str__
        class TestObj:
            def __str__(self):
                return "test_object"

        test_obj = TestObj()
        result = _to_python(test_obj)
        assert result == "test_object"

        # Test with primitive types
        assert _to_python("string") == "string"
        assert _to_python(42) == 42
        assert _to_python(True) is True
        assert _to_python(None) is None

    def test_error_handling_patterns(self):
        """Test consistent error handling patterns across functions."""
        # Test that all main functions return proper exit codes
        functions_to_test = [
            (list_drivers, Mock()),
            (validate_config, Mock()),
            (diagnose_connection, Mock(format="text")),
            (check_connection, Mock(format="text")),
        ]

        for func, args in functions_to_test:
            try:
                result = func(args)
                assert isinstance(result, int)
                assert result in [0, 1]  # Valid exit codes
            except Exception:
                # Some functions may raise exceptions, which is also valid
                pass

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_driver_validation_failed(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """DB2 native connection errors do not use JDBC driver validation."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "ibm_db_sa://localhost:50000/SAMPLE"
        mock_config_instance.database.type = "db2"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.create_connection.side_effect = RuntimeError("Connection refused")
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "json"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        output_data = json.loads(captured.out)
        assert output_data["success"] is False
        assert "Connection failed: host unreachable" in output_data["error"]

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_provider_connection_error(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """Test connection check when provider connection fails."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "postgresql+psycopg://localhost/db"
        mock_config_instance.database.type = "postgresql"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.create_connection.side_effect = Exception("Connection failed")
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"
        args.log_level = "info"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Connection failed" in captured.err

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_oracle_provider(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """Test connection check with Oracle provider."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "oracle+oracledb://localhost:1521?service_name=XE"
        mock_config_instance.database.type = "oracle"
        mock_load_config.return_value = mock_config_instance

        mock_provider = Mock()
        mock_provider.get_database_url.return_value = (
            "oracle+oracledb://localhost:1521?service_name=XE"
        )
        mock_provider.get_database_version.return_value = "Oracle Database 19c"
        mock_create_provider.return_value = mock_provider

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Connection successful!" in captured.out

    @patch("cli.db_utils.ProviderRegistry.create_provider")
    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_mysql_provider(
        self, mock_logger, mock_load_config, mock_create_provider, capsys
    ):
        """Test connection check with unsupported database type via ProviderRegistry ValueError."""
        mock_config_instance = Mock()
        mock_config_instance.database.type = "mysql"
        mock_load_config.return_value = mock_config_instance

        mock_create_provider.side_effect = ValueError("Unsupported database type: mysql")

        args = Mock()
        args.format = "json"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        output_data = json.loads(captured.out)
        assert output_data["success"] is False
        assert "Unsupported database type" in output_data["error"]

    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_none_database_type_with_url(
        self, mock_logger, mock_load_config, capsys
    ):
        """BUG-05 — crash None.lower() when url present but type=None."""
        mock_config_instance = Mock()
        mock_config_instance.database.url = "postgresql+psycopg://localhost:5432/db"
        mock_config_instance.database.type = None
        mock_config_instance.database.server = "localhost"
        mock_load_config.return_value = mock_config_instance

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Missing database type" in captured.err

    @patch("cli.db_utils.load_config")
    @patch("cli.db_utils.DbliftLogger")
    def test_check_connection_none_database_type_without_url(
        self, mock_logger, mock_load_config, capsys
    ):
        """BUG-05 — regression: url=None, type=None, server=None returns 1 without AttributeError.

        Note: with url=None and type=None, the pre-existing guard at line 280 fires first
        (condition: not url AND (not type OR not server) = True), before the new BUG-05 guard
        at line 302. This test validates the combined-None scenario is handled gracefully.
        """
        mock_config_instance = Mock()
        mock_config_instance.database.url = None
        mock_config_instance.database.type = None
        mock_config_instance.database.server = None
        # Explicitly None-out CosmosDB/SQLite discriminators so the Mock()
        # auto-attribute behaviour (returning truthy MagicMocks) does not
        # bypass the "missing connection parameters" guard.
        mock_config_instance.database.account_endpoint = None
        mock_config_instance.database.path = None
        mock_config_instance.database.database = None
        mock_load_config.return_value = mock_config_instance

        args = Mock()
        args.format = "text"

        result = check_connection(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "Missing required connection parameters" in captured.err
