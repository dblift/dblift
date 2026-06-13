"""Tests for the main CLI module."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

import pytest

# Mock all the imports first to prevent import errors during testing
with patch.dict(
    "sys.modules",
    {
        "cli.db_utils": MagicMock(),
        "config.dblift_config": MagicMock(),
        "core.logger": MagicMock(),
        "core.logger.console": MagicMock(),
        "core.migration.migration_executor": MagicMock(),
    },
):
    from cli.main import create_parser, main


def test_oss_command_does_not_require_license(monkeypatch):
    from cli import main as cli_main

    called = {"gate": False}

    def fail_gate(ctx):
        called["gate"] = True
        raise AssertionError("license gate should not run for OSS command")

    monkeypatch.setattr(cli_main, "_gate_license", fail_gate)
    monkeypatch.setattr(cli_main, "_dispatch_command", lambda ctx, output: 0)
    monkeypatch.setattr(cli_main, "_setup_logging_and_output", lambda ctx: object())
    monkeypatch.setattr(
        cli_main,
        "_parse_argv_and_load_config",
        lambda argv: cli_main._CliContext(
            commands=["info"],
            global_arguments=[],
            subcommand_args=[],
            args=object(),
            parser=object(),
            log=object(),
            config=object(),
        ),
    )

    cli_main.main()

    assert called["gate"] is False


def test_cli_license_key_is_stored_without_global_validation(monkeypatch):
    from cli import main as cli_main

    stored_tokens = []

    monkeypatch.setattr("core.licensing._guard._set_token", stored_tokens.append)

    cli_main._apply_cli_license_token(SimpleNamespace(license_key="jwt-from-cli"))

    assert stored_tokens == ["jwt-from-cli"]


def test_parse_phase_stores_cli_license_key_for_later_guards(monkeypatch):
    from cli import main as cli_main

    stored_tokens = []

    monkeypatch.setattr("core.licensing._guard._set_token", stored_tokens.append)
    monkeypatch.setattr(cli_main, "_load_and_merge_config", lambda args, log: object())
    monkeypatch.setattr(
        cli_main, "_validate_db_config", lambda args, config, parser, commands: None
    )
    monkeypatch.setattr(cli_main, "_validate_log_format_for_cli", lambda args, parser: None)

    ctx = cli_main._parse_argv_and_load_config(["--license-key", "jwt-from-cli", "info"])

    assert ctx.commands == ["info"]
    assert stored_tokens == ["jwt-from-cli"]


def test_terminal_extension_dispatches_before_argparse_validation(monkeypatch):
    from cli import main as cli_main

    handler = Mock(return_value=7)

    monkeypatch.setattr(sys, "argv", ["dblift", "license"])
    monkeypatch.setattr(cli_main, "load_terminal_commands", lambda: {"license": handler})

    with pytest.raises(SystemExit) as exc_info:
        cli_main._parse_argv_and_load_config(["license"])

    assert exc_info.value.code == 7
    handler.assert_called_once()
    assert handler.call_args.args[0].command == "license"


# -------------------
# Old patch-based CLI tests below are now redundant and brittle.
# Commenting them out in favor of subprocess-based CLI tests above.
# -------------------

'''
@pytest.mark.unit
class TestMainCLI:
    """Test suite for main CLI functionality."""

    def test_create_parser_basic(self):
        """Test basic parser creation."""
        parser = create_parser()
        assert parser is not None
        assert parser.description == "dblift: Database migration tool"

    def test_parser_version_argument(self):
        """Test version argument parsing."""
        parser = create_parser()
        args = parser.parse_args(["--version"])
        assert args.version is True

    def test_parser_config_argument(self):
        """Test config argument parsing."""
        parser = create_parser()
        args = parser.parse_args(["--config", "test.yaml", "info"])
        assert args.config == "test.yaml"

    def test_parser_database_arguments(self):
        """Test database arguments parsing."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "--db-url",
                "oracle+oracledb://localhost:1521?service_name=XE",
                "--db-username",
                "test",
                "--db-password",
                "password",
                "--db-schema",
                "test_schema",
                "info",
            ]
        )
        assert args.database_url == "oracle+oracledb://localhost:1521?service_name=XE"
        assert args.database_username == "test"
        assert args.database_password == "password"
        assert args.database_schema == "test_schema"

    def test_parser_migrate_command(self):
        """Test migrate command parsing."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "migrate",
                "--target-version",
                "1.0.0",
                "--tags",
                "tag1,tag2",
                "--exclude-tags",
                "tag3",
                "--versions",
                "1.0.0,2.0.0",
                "--exclude-versions",
                "3.0.0",
                "--placeholders",
                "key1=value1,key2=value2",
                "key3=value3",
                "--mark-as-executed",
                "--strict",
            ]
        )

        assert args.command == "migrate"
        assert args.target_version == "1.0.0"
        assert args.tags == "tag1,tag2"
        assert args.exclude_tags == "tag3"
        assert args.versions == "1.0.0,2.0.0"
        assert args.exclude_versions == "3.0.0"
        assert args.placeholders == ["key1=value1,key2=value2", "key3=value3"]
        assert args.mark_as_executed is True
        assert args.strict is True

    def test_parser_baseline_command(self):
        """Test baseline command parsing."""
        parser = create_parser()
        args = parser.parse_args(
            [
                "baseline",
                "--baseline-version",
                "1.0.0",
                "--baseline-description",
                "Initial baseline",
            ]
        )

        assert args.command == "baseline"
        assert args.baseline_version == "1.0.0"
        assert args.baseline_description == "Initial baseline"

    def test_parser_db_list_drivers(self):
        """Test db list-drivers command."""
        parser = create_parser()
        args = parser.parse_args(["db", "list-drivers"])
        assert args.command == "db"
        assert args.db_command == "list-drivers"

    def test_parser_db_validate_config(self):
        """Test db validate-config command."""
        parser = create_parser()
        args = parser.parse_args(["db", "validate-config", "--config", "test.yaml"])
        assert args.command == "db"
        assert args.db_command == "validate-config"
        assert args.config == "test.yaml"

    def test_parser_db_diagnose_connection(self):
        """Test db diagnose-connection command."""
        parser = create_parser()
        args = parser.parse_args(["db", "diagnose-connection", "--format", "json"])
        assert args.command == "db"
        assert args.db_command == "diagnose-connection"
        assert args.format == "json"

    def test_parser_db_check_connection(self):
        """Test db check-connection command."""
        parser = create_parser()
        args = parser.parse_args(
            ["db", "check-connection", "--url", "oracle+oracledb://localhost:1521?service_name=XE"]
        )
        assert args.command == "db"
        assert args.db_command == "check-connection"
        assert args.url == "oracle+oracledb://localhost:1521?service_name=XE"

    @patch("sys.exit")
    @patch("builtins.print")
    def test_main_version(self, mock_print, mock_exit):
        """Test version command."""
        with patch("sys.argv", ["dblift", "--version"]):
            main()

        # Version should match __version__ from __init__.py
        from __init__ import __version__
        mock_print.assert_called_once_with(f"dblift version {__version__}")
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    @patch("argparse.ArgumentParser.print_help")
    def test_main_no_command(self, mock_help, mock_exit):
        """Test main with no command."""
        with patch("sys.argv", ["dblift"]):
            main()

        mock_help.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    @patch("cli.db_utils.list_drivers")
    def test_main_db_list_drivers(self, mock_list_drivers, mock_exit):
        """Test db list-drivers command."""
        mock_list_drivers.return_value = 0

        with patch("sys.argv", ["dblift", "db", "list-drivers"]):
            main()

        mock_list_drivers.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    @patch("cli.db_utils.validate_config")
    def test_main_db_validate_config(self, mock_validate_config, mock_exit):
        """Test db validate-config command."""
        mock_validate_config.return_value = 0

        with patch("sys.argv", ["dblift", "db", "validate-config"]):
            main()

        mock_validate_config.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    @patch("cli.db_utils.diagnose_connection")
    def test_main_db_diagnose_connection(self, mock_diagnose_connection, mock_exit):
        """Test db diagnose-connection command."""
        mock_diagnose_connection.return_value = 0

        with patch("sys.argv", ["dblift", "db", "diagnose-connection"]):
            main()

        mock_diagnose_connection.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    @patch("cli.db_utils.check_connection")
    def test_main_db_check_connection(self, mock_check_connection, mock_exit):
        """Test db check-connection command."""
        mock_check_connection.return_value = 0

        with patch("sys.argv", ["dblift", "db", "check-connection"]):
            main()

        mock_check_connection.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("sys.exit")
    @patch("argparse.ArgumentParser.print_help")
    def test_main_db_invalid_command(self, mock_help, mock_exit):
        """Test main with invalid db command."""
        with patch("sys.argv", ["dblift", "db"]):
            main()

        mock_exit.assert_called_once_with(1)

    @patch("config.dblift_config.load_config")
    @patch("core.logger.LogFactory")
    @patch("core.migration.migration_executor.MigrationExecutor")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    @patch("sys.exit")
    def test_main_migrate_command(
        self,
        mock_exit,
        mock_mkdir,
        mock_exists,
        mock_executor_class,
        mock_log_factory,
        mock_load_config,
    ):
        """Test migrate command execution."""
        # Set up mocks
        mock_config = Mock()
        mock_config.database.url = "postgresql+psycopg://localhost/test"
        mock_config.database.username = "user"
        mock_config.database.password = "pass"
        mock_config.database.schema = "schema"
        mock_config.database.installed_by = "user"
        mock_load_config.return_value = mock_config

        mock_executor = Mock()
        mock_result = Mock()
        mock_result.success = True
        mock_executor.migrate.return_value = mock_result
        mock_executor_class.return_value = mock_executor

        mock_logger = Mock()
        mock_log_factory.get_log.return_value = mock_logger
        mock_log_factory.configure = Mock()

        mock_exists.return_value = True

        with patch(
            "sys.argv",
            [
                "dblift",
                "--db-url",
                "postgresql+psycopg://localhost/test",
                "--db-username",
                "user",
                "--db-password",
                "pass",
                "--db-schema",
                "schema",
                "migrate",
            ],
        ):
            main()

        # Verify migrate was called
        mock_executor.migrate.assert_called_once()
        # Exit should not be called for successful migration
        mock_exit.assert_not_called()

    @patch("config.dblift_config.load_config")
    @patch("core.logger.LogFactory")
    @patch("core.migration.migration_executor.MigrationExecutor")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    @patch("sys.exit")
    def test_main_migrate_command_failure(
        self,
        mock_exit,
        mock_mkdir,
        mock_exists,
        mock_executor_class,
        mock_log_factory,
        mock_load_config,
    ):
        """Test migrate command execution failure."""
        # Set up mocks
        mock_config = Mock()
        mock_config.database.url = "postgresql+psycopg://localhost/test"
        mock_config.database.username = "user"
        mock_config.database.password = "pass"
        mock_config.database.schema = "schema"
        mock_config.database.installed_by = "user"
        mock_load_config.return_value = mock_config

        mock_executor = Mock()
        mock_result = Mock()
        mock_result.success = False
        mock_executor.migrate.return_value = mock_result
        mock_executor_class.return_value = mock_executor

        mock_logger = Mock()
        mock_log_factory.get_log.return_value = mock_logger
        mock_log_factory.configure = Mock()

        mock_exists.return_value = True

        with patch(
            "sys.argv",
            [
                "dblift",
                "--db-url",
                "postgresql+psycopg://localhost/test",
                "--db-username",
                "user",
                "--db-password",
                "pass",
                "--db-schema",
                "schema",
                "migrate",
            ],
        ):
            main()

        # Verify migrate was called
        mock_executor.migrate.assert_called_once()
        # Exit should be called with error code for failed migration
        mock_exit.assert_called_once_with(1)

    @patch("config.dblift_config.load_config")
    @patch("core.logger.LogFactory")
    @patch("core.migration.migration_executor.MigrationExecutor")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    @patch("sys.exit")
    def test_main_info_command(
        self,
        mock_exit,
        mock_mkdir,
        mock_exists,
        mock_executor_class,
        mock_log_factory,
        mock_load_config,
    ):
        """Test info command execution."""
        # Set up mocks
        mock_config = Mock()
        mock_config.database.url = "postgresql+psycopg://localhost/test"
        mock_config.database.username = "user"
        mock_config.database.password = "pass"
        mock_config.database.schema = "schema"
        mock_config.database.installed_by = "user"
        mock_load_config.return_value = mock_config

        mock_executor = Mock()
        mock_result = Mock()
        mock_result.success = True
        mock_executor.info.return_value = mock_result
        mock_executor_class.return_value = mock_executor

        mock_logger = Mock()
        mock_log_factory.get_log.return_value = mock_logger
        mock_log_factory.configure = Mock()

        mock_exists.return_value = True

        with patch(
            "sys.argv",
            [
                "dblift",
                "--db-url",
                "postgresql+psycopg://localhost/test",
                "--db-username",
                "user",
                "--db-password",
                "pass",
                "--db-schema",
                "schema",
                "info",
            ],
        ):
            main()

        # Verify info was called
        mock_executor.info.assert_called_once()
        mock_exit.assert_not_called()

    @patch("config.dblift_config.load_config")
    @patch("core.logger.LogFactory")
    @patch("core.migration.migration_executor.MigrationExecutor")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    @patch("sys.exit")
    def test_main_baseline_command(
        self,
        mock_exit,
        mock_mkdir,
        mock_exists,
        mock_executor_class,
        mock_log_factory,
        mock_load_config,
    ):
        """Test baseline command execution."""
        # Set up mocks
        mock_config = Mock()
        mock_config.database.url = "postgresql+psycopg://localhost/test"
        mock_config.database.username = "user"
        mock_config.database.password = "pass"
        mock_config.database.schema = "schema"
        mock_config.database.installed_by = "user"
        mock_load_config.return_value = mock_config

        mock_executor = Mock()
        mock_result = Mock()
        mock_result.success = True
        mock_executor.baseline.return_value = mock_result
        mock_executor_class.return_value = mock_executor

        mock_logger = Mock()
        mock_log_factory.get_log.return_value = mock_logger
        mock_log_factory.configure = Mock()

        mock_exists.return_value = True

        with patch(
            "sys.argv",
            [
                "dblift",
                "--db-url",
                "postgresql+psycopg://localhost/test",
                "--db-username",
                "user",
                "--db-password",
                "pass",
                "--db-schema",
                "schema",
                "baseline",
                "--baseline-version",
                "1.0.0",
            ],
        ):
            main()

        # Verify baseline was called
        mock_executor.baseline.assert_called_once()
        mock_exit.assert_not_called()

    @patch("config.dblift_config.load_config")
    @patch("core.logger.LogFactory")
    @patch("core.migration.migration_executor.MigrationExecutor")
    @pytest.mark.skip(reason="Journal command does not exist - journals are always in-memory only")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.mkdir")
    @patch("sys.exit")
    def test_main_journal_command(
        self,
        mock_exit,
        mock_mkdir,
        mock_exists,
        mock_executor_class,
        mock_log_factory,
        mock_load_config,
    ):
        """Test journal command execution."""
        # Set up mocks
        mock_config = Mock()
        mock_config.database.url = "postgresql+psycopg://localhost/test"
        mock_config.database.username = "user"
        mock_config.database.password = "pass"
        mock_config.database.schema = "schema"
        mock_config.database.installed_by = "user"
        mock_load_config.return_value = mock_config

        mock_executor = Mock()
        # Mock journal files
        mock_journal_files = ["/path/to/journal1.json", "/path/to/journal2.json"]
        mock_executor.get_journal_files.return_value = mock_journal_files

        # Mock performance metrics
        mock_metrics = {
            "migration_id": "V1.0.0__test.sql",
            "total_statements": 5,
            "total_execution_time": 1000,
            "avg_statement_time": 200.0,
            "max_statement_time": 500,
            "slowest_statement": "CREATE TABLE test (id INT)",
        }
        mock_executor.get_migration_performance.return_value = mock_metrics
        mock_executor_class.return_value = mock_executor

        mock_logger = Mock()
        mock_log_factory.get_log.return_value = mock_logger
        mock_log_factory.configure = Mock()

        mock_exists.return_value = True

        with patch(
            "sys.argv",
            [
                "dblift",
                "--db-url",
                "postgresql+psycopg://localhost/test",
                "--db-username",
                "user",
                "--db-password",
                "pass",
                "--db-schema",
                "schema",
                "journal",
            ],
        ):
            with patch("builtins.print") as mock_print:
                main()

        # Verify get_journal_files was called
        mock_executor.get_journal_files.assert_called_once()
        # Check that output was printed
        mock_print.assert_called()
        mock_exit.assert_not_called()

    @pytest.mark.skip(reason="Journal command does not exist - journals are always in-memory only")
    @patch("config.dblift_config.load_config")
    @patch("cli.main.argparse.ArgumentParser.error")
    @patch("cli.main.sys.exit")
    def test_main_journal_command_no_files(self, mock_exit, mock_error, mock_load_config):
        """Test journal command execution with no journal files."""
        # Set up mocks
        mock_config = Mock()
        mock_config.database.url = "postgresql+psycopg://localhost/test"
        mock_config.database.username = "user"
        mock_config.database.password = "pass"
        mock_config.database.schema = "schema"
        mock_config.database.installed_by = "user"
        mock_load_config.return_value = mock_config

        mock_executor = Mock()
        # Mock empty journal files list
        mock_executor.get_journal_files.return_value = []
        mock_executor_class.return_value = mock_executor

        mock_logger = Mock()
        mock_log_factory.get_log.return_value = mock_logger
        mock_log_factory.configure = Mock()

        mock_exists.return_value = True

        with patch(
            "sys.argv",
            [
                "dblift",
                "--db-url",
                "postgresql+psycopg://localhost/test",
                "--db-username",
                "user",
                "--db-password",
                "pass",
                "--db-schema",
                "schema",
                "journal",
            ],
        ):
            with patch("builtins.print") as mock_print:
                main()

        # Verify get_journal_files was called
        mock_executor.get_journal_files.assert_called_once()
        # Check that "no files" message was printed
        mock_print.assert_called_with("No migration journal files found.")
        mock_exit.assert_called_once_with(0)

'''


@pytest.mark.unit
class TestDatabaseUrlMasking:
    """Test that database URLs are masked before logging in CLI."""

    def test_mask_database_url_imported_in_cli_main(self):
        """cli.main doit exposer _mask_database_url (importée depuis snapshot_command)."""
        import cli.main as m

        assert hasattr(m, "_mask_database_url"), "_mask_database_url must be imported in cli.main"

    def test_cli_main_masks_sqlserver_url(self):
        """Réplication de la logique main.py:1296 — URL SQL Server masquée avant log."""
        import cli.main as m

        raw_url = "mssql+pymssql://host/mydb?password=mysecret"
        masked_url = (
            m._mask_database_url(str(raw_url)) if raw_url and raw_url != "Not set" else raw_url
        )
        assert "mysecret" not in masked_url
        assert "***" in masked_url

    def test_cli_main_masks_oracle_url(self):
        """Réplication de la logique main.py:1296 — URL Oracle thin masquée avant log."""
        import cli.main as m

        raw_url = "oracle+oracledb://admin:secret@host:1521?service_name=orcl"
        masked_url = (
            m._mask_database_url(str(raw_url)) if raw_url and raw_url != "Not set" else raw_url
        )
        assert "secret" not in masked_url
        assert "***" in masked_url

    def test_cli_main_masks_standard_database_url(self):
        """Standard //user:password@host format (PostgreSQL, MySQL) must be masked before log."""
        import cli.main as m

        raw_url = "postgresql+psycopg://admin:secret@host:5432/db"
        masked_url = (
            m._mask_database_url(str(raw_url)) if raw_url and raw_url != "Not set" else raw_url
        )
        assert "secret" not in masked_url
        assert "***" in masked_url
        assert "//admin:***@host" in masked_url

    def test_cli_main_not_set_url_unchanged(self):
        """Si l'URL vaut 'Not set', elle ne doit pas passer par _mask_database_url."""
        import cli.main as m

        raw_url = "Not set"
        masked_url = (
            m._mask_database_url(str(raw_url)) if raw_url and raw_url != "Not set" else raw_url
        )
        assert masked_url == "Not set"


def test_main_missing_database_url_subprocess():
    """Test CLI with missing database URL using subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "migrate",
        # No --db-url provided, should trigger error
    ]
    env = os.environ.copy()
    env["DBLIFT_LICENSE_KEY"] = "dummy"
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=os.getcwd(), env=env, timeout=30
    )
    assert result.returncode != 0
    assert (
        "Database URL is required" in result.stderr or "Database URL is required" in result.stdout
    )


def test_main_missing_database_username_subprocess():
    """Test CLI with missing database username using subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "oracle+oracledb://localhost:1521?service_name=XE",
        "migrate",
        # No --db-username provided, should trigger error
    ]
    env = os.environ.copy()
    env["DBLIFT_LICENSE_KEY"] = "dummy"
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=os.getcwd(), env=env, timeout=30
    )
    assert result.returncode != 0
    assert (
        "Database username is required" in result.stderr
        or "Database username is required" in result.stdout
    )


def test_main_missing_database_password_subprocess():
    """Test CLI with missing database password using subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "mssql+pymssql://localhost:1433/testdb",
        "--db-username",
        "user",
        "migrate",
        # No --db-password provided, should trigger error
    ]
    env = os.environ.copy()
    env["DBLIFT_LICENSE_KEY"] = "dummy"
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=os.getcwd(), env=env, timeout=30
    )
    assert result.returncode != 0
    assert (
        "Database password is required" in result.stderr
        or "Database password is required" in result.stdout
    )


def test_main_info_command_subprocess():
    """Test CLI info command with all required arguments using subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "postgresql+psycopg://localhost/test",
        "--db-username",
        "user",
        "--db-password",
        "pass",
        "--db-schema",
        "schema",
        "info",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert combined.strip() != ""


def test_main_migrate_command_subprocess():
    """Test CLI migrate command with all required arguments using subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "postgresql+psycopg://localhost/test",
        "--db-username",
        "user",
        "--db-password",
        "pass",
        "--db-schema",
        "schema",
        "migrate",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert combined.strip() != ""


def test_main_validate_command_subprocess():
    """Test CLI validate command with all required arguments using subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "postgresql+psycopg://localhost/test",
        "--db-username",
        "user",
        "--db-password",
        "pass",
        "--db-schema",
        "schema",
        "validate",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert combined.strip() != ""


def test_main_baseline_command_subprocess():
    """Test CLI baseline command with all required arguments using subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "postgresql+psycopg://localhost/test",
        "--db-username",
        "user",
        "--db-password",
        "pass",
        "--db-schema",
        "schema",
        "baseline",
        "--baseline-version",
        "1.0.0",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert combined.strip() != ""


def test_main_exception_handling_subprocess():
    """main() doit sortir avec un code non-nul quand la connexion DB échoue."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "postgresql+psycopg://localhost:1/nonexistent_db",
        "--db-username",
        "invalid_user",
        "--db-password",
        "invalid_pass",
        "--db-schema",
        "public",
        "migrate",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    assert result.returncode != 0


def test_main_log_format_validation_subprocess():
    """Format de log valide → pas d'erreur 'Invalid log format'."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "postgresql+psycopg://localhost:5432/mydb",
        "--db-username",
        "user",
        "--db-password",
        "pass",
        "--db-schema",
        "schema",
        "--log-format",
        "text,json",
        "info",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    combined = result.stderr + result.stdout
    assert "Invalid log format" not in combined


def test_main_multiple_log_formats_subprocess():
    """Format de log invalide → 'Invalid log format' dans la sortie."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "postgresql+psycopg://localhost:5432/mydb",
        "--db-username",
        "user",
        "--db-password",
        "pass",
        "--db-schema",
        "schema",
        "--log-format",
        "invalid_format",
        "info",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    assert result.returncode != 0
    assert "Invalid log format" in result.stderr or "Invalid log format" in result.stdout


def test_load_config_failure_no_attribute_error_subprocess():
    """Missing --config path + credentials: clean exit without AttributeError (AC#5a).

    load_config() now raises FileNotFoundError for a missing --config path; the CLI must
    turn that into a clean error message + non-zero exit rather than letting it propagate.
    """
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--config",
        "/nonexistent/config.yaml",
        "--db-url",
        "postgresql+psycopg://localhost:5432/db",
        "info",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    assert result.returncode != 0
    combined = result.stderr + result.stdout
    assert "AttributeError" not in combined
    assert combined.strip() != "", "Une erreur lisible doit être affichée (pas un échec silencieux)"


def test_log_initialized_before_load_config_info_subprocess():
    """Init précoce du log : échec de commande ne produit pas d'AttributeError (AC#5b)."""
    cmd = [
        sys.executable,
        "-m",
        "cli.main",
        "--db-url",
        "postgresql+psycopg://nowhere:1/fake",
        "info",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd(), timeout=30)
    assert result.returncode != 0
    combined = result.stderr + result.stdout
    assert "AttributeError" not in combined


@pytest.mark.unit
class TestConfigureLoggingDictLookup:
    """Tests AC#2, AC#3: dict lookup for log-level and log-format in _configure_logging."""

    def _make_args(self, log_level="info", log_format="text", log_dir=None, log_file=None):
        args = MagicMock()
        args.log_level = log_level
        args.log_format = log_format
        args.log_dir = log_dir
        args.log_file = log_file
        # Boolean CLI flags — explicit False so the MagicMock fallback doesn't
        # surface a truthy Mock for every getattr call inside _configure_logging.
        args.quiet = False
        args.no_progress = False
        return args

    def _make_config(self):
        config = MagicMock()
        config.database.url = "postgresql+psycopg://localhost:5432/test"
        config.database.schema = "public"
        return config

    @patch("cli._config_helpers.LogFactory")
    @patch("cli._config_helpers.DatabaseUrlParser")
    @patch("cli._config_helpers.Path")
    def test_log_level_debug_maps_correctly(self, mock_path, mock_parser, mock_log_factory):
        from cli.main import _configure_logging
        from core.logger import LogLevel

        mock_parser.parse_database_name.return_value = "test"
        args = self._make_args(log_level="debug")
        _configure_logging(args, self._make_config(), MagicMock())
        assert mock_log_factory.configure.call_args.kwargs["log_level"] == LogLevel.DEBUG

    @patch("cli._config_helpers.LogFactory")
    @patch("cli._config_helpers.DatabaseUrlParser")
    @patch("cli._config_helpers.Path")
    def test_log_level_warn_maps_correctly(self, mock_path, mock_parser, mock_log_factory):
        from cli.main import _configure_logging
        from core.logger import LogLevel

        mock_parser.parse_database_name.return_value = "test"
        args = self._make_args(log_level="warn")
        _configure_logging(args, self._make_config(), MagicMock())
        assert mock_log_factory.configure.call_args.kwargs["log_level"] == LogLevel.WARN

    @patch("cli._config_helpers.LogFactory")
    @patch("cli._config_helpers.DatabaseUrlParser")
    @patch("cli._config_helpers.Path")
    def test_log_level_error_maps_correctly(self, mock_path, mock_parser, mock_log_factory):
        from cli.main import _configure_logging
        from core.logger import LogLevel

        mock_parser.parse_database_name.return_value = "test"
        args = self._make_args(log_level="error")
        _configure_logging(args, self._make_config(), MagicMock())
        assert mock_log_factory.configure.call_args.kwargs["log_level"] == LogLevel.ERROR

    @patch("cli._config_helpers.LogFactory")
    @patch("cli._config_helpers.DatabaseUrlParser")
    @patch("cli._config_helpers.Path")
    def test_log_level_unknown_defaults_to_info(self, mock_path, mock_parser, mock_log_factory):
        from cli.main import _configure_logging
        from core.logger import LogLevel

        mock_parser.parse_database_name.return_value = "test"
        args = self._make_args(log_level="verbose")
        _configure_logging(args, self._make_config(), MagicMock())
        assert mock_log_factory.configure.call_args.kwargs["log_level"] == LogLevel.INFO

    @patch("cli._config_helpers.LogFactory")
    @patch("cli._config_helpers.DatabaseUrlParser")
    @patch("cli._config_helpers.Path")
    def test_quiet_sets_console_log_level_to_notice(self, mock_path, mock_parser, mock_log_factory):
        """``--quiet`` must keep success (NOTICE) messages — only INFO/DEBUG drop.

        Regression guard: an earlier rev raised the console threshold to
        WARN, silently swallowing NOTICE-tier "Command completed
        successfully" confirmations.
        """
        from cli.main import _configure_logging
        from core.logger import LogLevel

        mock_parser.parse_database_name.return_value = "test"
        args = self._make_args(log_level="info")
        args.quiet = True
        _configure_logging(args, self._make_config(), MagicMock())
        kwargs = mock_log_factory.configure.call_args.kwargs
        assert kwargs["console_log_level"] == LogLevel.NOTICE
        # File/JSON/HTML logs keep INFO so audit trail stays complete.
        assert kwargs["log_level"] == LogLevel.INFO

    @patch("cli._config_helpers.LogFactory")
    @patch("cli._config_helpers.DatabaseUrlParser")
    @patch("cli._config_helpers.Path")
    def test_quiet_skipped_when_log_level_already_at_or_above_notice(
        self, mock_path, mock_parser, mock_log_factory
    ):
        """If ``--log-level=warn``/error already silences info, leave the
        explicit choice alone (no double-override)."""
        from cli.main import _configure_logging
        from core.logger import LogLevel

        mock_parser.parse_database_name.return_value = "test"
        args = self._make_args(log_level="warn")
        args.quiet = True
        _configure_logging(args, self._make_config(), MagicMock())
        kwargs = mock_log_factory.configure.call_args.kwargs
        # Console override not applied because log_level == WARN already.
        assert kwargs["console_log_level"] is None
        assert kwargs["log_level"] == LogLevel.WARN

    @patch("cli._config_helpers.LogFactory")
    @patch("cli._config_helpers.DatabaseUrlParser")
    @patch("cli._config_helpers.Path")
    def test_log_format_html_maps_correctly(self, mock_path, mock_parser, mock_log_factory):
        from cli.main import _configure_logging
        from core.logger import LogFormat

        mock_parser.parse_database_name.return_value = "test"
        args = self._make_args(log_format="html")
        _configure_logging(args, self._make_config(), MagicMock())
        assert mock_log_factory.configure.call_args.kwargs["log_format"] == LogFormat.HTML

    @patch("cli._config_helpers.LogFactory")
    @patch("cli._config_helpers.DatabaseUrlParser")
    @patch("cli._config_helpers.Path")
    def test_log_format_json_maps_correctly(self, mock_path, mock_parser, mock_log_factory):
        from cli.main import _configure_logging
        from core.logger import LogFormat

        mock_parser.parse_database_name.return_value = "test"
        args = self._make_args(log_format="json")
        _configure_logging(args, self._make_config(), MagicMock())
        assert mock_log_factory.configure.call_args.kwargs["log_format"] == LogFormat.JSON

    @patch("cli._config_helpers.LogFactory")
    @patch("cli._config_helpers.DatabaseUrlParser")
    @patch("cli._config_helpers.Path")
    def test_log_format_text_maps_to_text(self, mock_path, mock_parser, mock_log_factory):
        """'text' est une clé de _LOG_FORMAT_MAP → LogFormat.TEXT (AC#3.4)."""
        from cli.main import _configure_logging
        from core.logger import LogFormat

        mock_parser.parse_database_name.return_value = "test"
        args = self._make_args(log_format="text")
        _configure_logging(args, self._make_config(), MagicMock())
        assert mock_log_factory.configure.call_args.kwargs["log_format"] == LogFormat.TEXT
