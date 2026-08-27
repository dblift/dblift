"""
CLI validation tests.

CRITICAL: These tests ensure that integration tests are using the correct
production CLI (cli/main.py) and not the experimental implementations.

All integration tests MUST use cli/main.py which is the CLI that ships
in distributions to end users.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration.helpers.cli_runner_direct import DBLiftCLIDirect as DBLiftCLI
from tests.integration.helpers.cli_runner_direct import get_cli_version


@pytest.mark.integration
class TestCLIValidation:
    """Validate that tests are using the correct production CLI."""

    def test_cli_is_production_version(self):
        """Verify that cli/main.py is the CLI we're testing."""
        # Get version from production CLI
        result = subprocess.run(
            [sys.executable, "-m", "cli.main", "--version"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, "Production CLI failed to run"
        assert (
            "dblift" in result.stdout.lower() or "version" in result.stdout.lower()
        ), f"Version output doesn't look right: {result.stdout}"

    def test_cli_main_module_exists(self):
        """Verify that cli.main module can be imported."""
        try:
            import cli.main  # noqa: F401
        except ImportError as e:
            pytest.fail(f"cli.main module cannot be imported: {e}")

    def test_cli_help_command(self):
        """Verify that production CLI help command works."""
        result = subprocess.run(
            [sys.executable, "-m", "cli.main", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, "Production CLI help failed"
        assert "migrate" in result.stdout.lower()
        assert "baseline" in result.stdout.lower()
        assert "info" in result.stdout.lower()

    def test_cli_available_commands(self):
        """Verify that all expected commands are available."""
        result = subprocess.run(
            [sys.executable, "-m", "cli.main", "--help"],
            capture_output=True,
            text=True,
        )

        expected_commands = [
            "migrate",
            "info",
            "validate",
            "baseline",
            "undo",
            "clean",
            "repair",
        ]

        output_lower = result.stdout.lower()
        for command in expected_commands:
            assert command in output_lower, f"Command '{command}' not found in CLI help"

    def test_get_cli_version_helper(self):
        """Verify that the get_cli_version helper works."""
        version = get_cli_version()
        assert version, "get_cli_version() returned empty string"

    def test_dblift_cli_class_uses_correct_module(self):
        """Verify that DBLiftCLI class uses cli.main."""
        assert (
            DBLiftCLI.CLI_MODULE == "cli.main"
        ), f"DBLiftCLI is using wrong module: {DBLiftCLI.CLI_MODULE}"

    def test_do_not_use_dblift_cli_py(self):
        """
        Document that legacy experimental CLIs must not be used in integration tests.

        Older repositories contained a hand-rolled ``dblift_cli.py`` and ``__main__.py``;
        they may no longer be present, but the guards remain to emphasise that tests
        must execute the production CLI.
        """

        assert DBLiftCLI.CLI_MODULE == "cli.main"

    def test_cli_runner_creates_correct_commands(self, tmp_path):
        """Verify that DBLiftCLI generates correct command lines."""
        config_file = tmp_path / "dblift.yaml"
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        cli = DBLiftCLI(config_file, migrations_dir)

        # Verify paths are set correctly
        assert cli.config_file == config_file
        assert cli.migrations_dir == migrations_dir

        # Verify it can execute a command (direct mode doesn't have cli_base)
        result = cli.info()
        # Just verify it doesn't crash - actual functionality tested elsewhere
        assert result is not None
