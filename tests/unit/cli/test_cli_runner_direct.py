"""Unit tests for cli_runner_direct helper."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.integration.helpers.cli_runner_direct import (
    DBLiftCLIDirect,
    capture_main_execution,
)


@pytest.mark.unit
class TestCLIRunnerDirect:
    """Test direct CLI runner helper."""

    def test_version_command(self, tmp_path):
        """Test --version command works."""
        config_file = tmp_path / "dblift.yaml"
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        cli = DBLiftCLIDirect(config_file, migrations_dir)

        # Build argv for --version
        argv = ["dblift", "--version"]

        with capture_main_execution(argv) as result:
            assert result.success
            assert "dblift" in result.stdout.lower() or "version" in result.stdout.lower()
            assert result.returncode == 0

    def test_help_command(self, tmp_path):
        """Test --help command works."""
        config_file = tmp_path / "dblift.yaml"
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        cli = DBLiftCLIDirect(config_file, migrations_dir)

        # Build argv for --help (no command)
        argv = ["dblift", "--help"]

        with capture_main_execution(argv) as result:
            # Help should succeed (exit code 0)
            assert result.returncode == 0
            assert "migrate" in result.stdout.lower()

    def test_cli_runner_interface(self, tmp_path):
        """Test that DBLiftCLIDirect has same interface as DBLiftCLI."""
        config_file = tmp_path / "dblift.yaml"
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        cli = DBLiftCLIDirect(config_file, migrations_dir)

        # Should have same attributes
        assert hasattr(cli, "config_file")
        assert hasattr(cli, "migrations_dir")
        assert hasattr(cli, "CLI_MODULE")
        assert cli.CLI_MODULE == "cli.main"

        # Should have same methods
        assert hasattr(cli, "migrate")
        assert hasattr(cli, "info")
        assert hasattr(cli, "baseline")
        assert hasattr(cli, "undo")
        assert hasattr(cli, "validate")
        assert hasattr(cli, "clean")
        assert hasattr(cli, "repair")
        assert hasattr(cli, "snapshot")
        assert hasattr(cli, "chain")

    def test_direct_runner_stays_direct_mode(self, tmp_path):
        """Native integration tests run directly under coverage."""
        config_file = tmp_path / "dblift.yaml"
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        cli = DBLiftCLIDirect(config_file, migrations_dir)

        assert cli._use_subprocess is False
