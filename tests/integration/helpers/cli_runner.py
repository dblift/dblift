"""
CLI command execution helper for integration tests.

IMPORTANT: This module exclusively uses .cli.main which is the production CLI
used in distributions. DO NOT use dblift_cli.py or __main__.py.

Usage:
    from tests.integration.helpers.cli_runner import DBLiftCLI

    cli = DBLiftCLI(config_file, migrations_dir)
    result = cli.migrate()
    assert result.success
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CommandResult:
    """Structured result from a CLI command execution.

    NOTE: This dataclass is intentionally duplicated in cli_runner_direct.py.
    cli_runner.py is a standalone subprocess-only module with no intra-package
    imports, and merging would add coupling for no benefit.  The canonical
    CommandResult re-exported by helpers/__init__.py comes from cli_runner_direct.
    See story 23-6 AC#7 analysis.
    """

    returncode: int
    stdout: str
    stderr: str
    command: List[str]

    @property
    def success(self) -> bool:
        """Check if command succeeded."""
        return self.returncode == 0

    @property
    def failed(self) -> bool:
        """Check if command failed."""
        return self.returncode != 0

    @property
    def output(self) -> str:
        """Get combined output."""
        return self.stdout + self.stderr


class DBLiftCLI:
    """
    Helper for running DBLift CLI commands in integration tests.

    IMPORTANT: This exclusively uses .cli.main which is the production CLI
    used in distributions. DO NOT use dblift_cli.py or __main__.py.

    Example:
        >>> cli = DBLiftCLI(config_file, migrations_dir)
        >>> result = cli.migrate()
        >>> assert result.success
        >>> assert "V1_0_0" in result.stdout
    """

    # Production CLI - this is what gets distributed to users
    # Use absolute module path (cli.main) instead of relative (.cli.main)
    # Relative imports don't work with python -m
    CLI_MODULE = "cli.main"

    def __init__(
        self,
        config_file: Path,
        migrations_dir: Path,
        cwd: Optional[Path] = None,
    ):
        """
        Initialize CLI helper.

        Args:
            config_file: Path to dblift.yaml configuration
            migrations_dir: Path to migrations directory
            cwd: Working directory for command execution (defaults to project root)
        """
        self.config_file = Path(config_file)
        self.migrations_dir = Path(migrations_dir)
        self.cwd = cwd or Path.cwd()

        # Use production CLI module
        self.cli_base = [sys.executable, "-m", self.CLI_MODULE]

    def migrate(
        self,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        placeholders: Optional[str] = None,
        dry_run: bool = False,
        mark_as_executed: bool = False,
        show_sql: bool = False,
        skip_validation: bool = False,
        additional_scripts: Optional[List[Path]] = None,
        log_level: Optional[str] = "debug",
        log_format: Optional[List[str]] = None,
        **kwargs,
    ) -> CommandResult:
        """
        Run migrate command with options.

        Examples:
            # Basic migration
            result = cli.migrate()

            # Target version
            result = cli.migrate(target_version="1.0.1")

            # With tags
            result = cli.migrate(tags=["core", "init"])

            # Dry run
            result = cli.migrate(dry_run=True)

            # Multiple migration directories
            result = cli.migrate(additional_scripts=[Path("./module1/migrations")])
        """
        return self._run_command(
            "migrate",
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            placeholders=placeholders,
            dry_run=dry_run,
            mark_as_executed=mark_as_executed,
            show_sql=show_sql,
            skip_validation=skip_validation,
            additional_scripts=additional_scripts,
            log_level=log_level,
            log_format=log_format,
            **kwargs,
        )

    def info(
        self,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        log_level: Optional[str] = None,
        **kwargs,
    ) -> CommandResult:
        """
        Run info command with options.

        Examples:
            # Basic info
            result = cli.info()

            # With tag filter
            result = cli.info(tags="core")
        """
        return self._run_command(
            "info",
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            log_level=log_level,
            **kwargs,
        )

    def baseline(
        self,
        baseline_version: str,
        baseline_description: Optional[str] = None,
        dry_run: bool = False,
        log_level: Optional[str] = "debug",
        **kwargs,
    ) -> CommandResult:
        """
        Run baseline command.

        Examples:
            # Basic baseline
            result = cli.baseline(baseline_version="1.0.0")

            # With description
            result = cli.baseline(
                baseline_version="1.0.0",
                baseline_description="Existing production schema"
            )
        """
        return self._run_command(
            "baseline",
            baseline_version=baseline_version,
            baseline_description=baseline_description,
            dry_run=dry_run,
            **kwargs,
        )

    def undo(
        self,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        dry_run: bool = False,
        show_sql: bool = False,
        **kwargs,
    ) -> CommandResult:
        """
        Run undo command.

        Examples:
            # Undo to specific version
            result = cli.undo(target_version="1.0.0")

            # Undo with dry run
            result = cli.undo(target_version="1.0.0", dry_run=True)
        """
        return self._run_command(
            "undo",
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            dry_run=dry_run,
            show_sql=show_sql,
            **kwargs,
        )

    def validate(self, skip_validation: bool = False, **kwargs) -> CommandResult:
        """Run validate command."""
        return self._run_command("validate", skip_validation=skip_validation, **kwargs)

    def clean(self, dry_run: bool = False, **kwargs) -> CommandResult:
        """Run clean command."""
        if not dry_run:
            kwargs.setdefault("clean_enabled", True)
        return self._run_command("clean", dry_run=dry_run, **kwargs)

    def repair(self, dry_run: bool = False, **kwargs) -> CommandResult:
        """Run repair command."""
        return self._run_command("repair", dry_run=dry_run, **kwargs)

    def import_flyway(self, **kwargs) -> CommandResult:
        """Run import-flyway command."""
        return self._run_command("import-flyway", **kwargs)

    def snapshot(
        self,
        output: str,
        source: str = "database-stored",
        **kwargs,
    ) -> CommandResult:
        """
        Run snapshot command.

        Examples:
            # Export from database-stored snapshot
            result = cli.snapshot(output="snapshot.json", source="database-stored")

            # Export from live database
            result = cli.snapshot(output="snapshot.json", source="live-database")
        """
        return self._run_command(
            "snapshot",
            output=output,
            source=source,
            **kwargs,
        )

    def chain(self, *commands: str, **kwargs) -> CommandResult:
        """
        Execute multiple commands in sequence (command chaining).

        Examples:
            # Validate, then migrate, then info
            result = cli.chain("validate", "migrate", "info")
            assert result.success
        """
        return self._run_chained_commands(commands, **kwargs)

    def _run_command(self, command: str, **kwargs) -> CommandResult:
        """
        Execute a single CLI command and return structured result.

        This method builds the command line from the base CLI module,
        the command name, standard options, and keyword arguments.
        """
        cmd = self.cli_base.copy()

        # Add global arguments BEFORE the subcommand
        if kwargs.get("log_level"):
            cmd.extend(["--log-level", kwargs["log_level"]])

        if kwargs.get("log_format"):
            for fmt in kwargs["log_format"]:
                cmd.extend(["--log-format", fmt])

        cmd.append(command)

        # Add config (always required)
        cmd.extend(["--config", str(self.config_file)])

        # Add migration path(s) - only for commands that need it
        # Snapshot command doesn't need --scripts
        # Baseline accepts --scripts for command chaining compatibility
        if command != "snapshot":
            cmd.extend(["--scripts", str(self.migrations_dir)])

            # Add additional script directories if provided
            if kwargs.get("additional_scripts"):
                for script_dir in kwargs["additional_scripts"]:
                    cmd.extend(["--scripts", str(script_dir)])

        # Add command-specific options
        if kwargs.get("target_version"):
            cmd.extend(["--target-version", kwargs["target_version"]])

        if kwargs.get("baseline_version"):
            cmd.extend(["--baseline-version", kwargs["baseline_version"]])

        if kwargs.get("baseline_description"):
            cmd.extend(["--baseline-description", kwargs["baseline_description"]])

        if kwargs.get("tags"):
            tags_val = kwargs["tags"]
            if isinstance(tags_val, list):
                tags_val = ",".join(tags_val)
            cmd.extend(["--tags", tags_val])

        if kwargs.get("exclude_tags"):
            exclude_tags_val = kwargs["exclude_tags"]
            if isinstance(exclude_tags_val, list):
                exclude_tags_val = ",".join(exclude_tags_val)
            cmd.extend(["--exclude-tags", exclude_tags_val])

        if kwargs.get("versions"):
            versions_val = kwargs["versions"]
            if isinstance(versions_val, list):
                versions_val = ",".join(versions_val)
            cmd.extend(["--versions", versions_val])

        if kwargs.get("exclude_versions"):
            exclude_versions_val = kwargs["exclude_versions"]
            if isinstance(exclude_versions_val, list):
                exclude_versions_val = ",".join(exclude_versions_val)
            cmd.extend(["--exclude-versions", exclude_versions_val])

        # log_level and log_format are now added before the subcommand (see above)

        if kwargs.get("placeholders"):
            placeholders_val = kwargs["placeholders"]
            if isinstance(placeholders_val, list):
                cmd.extend(["--placeholders", *placeholders_val])
            else:
                cmd.extend(["--placeholders", placeholders_val])

        # Add boolean flags
        if kwargs.get("dry_run"):
            cmd.append("--dry-run")

        if kwargs.get("mark_as_executed"):
            cmd.append("--mark-as-executed")

        if kwargs.get("show_sql"):
            cmd.append("--show-sql")

        if kwargs.get("ignore_unmanaged"):
            cmd.append("--ignore-unmanaged")

        if kwargs.get("skip_validation"):
            cmd.append("--skip-validation")

        if kwargs.get("clean_enabled"):
            cmd.append("--clean-enabled")

        # Export-schema specific options
        if kwargs.get("output"):
            cmd.extend(["--output", kwargs["output"]])
        if kwargs.get("output_dir"):
            cmd.extend(["--output-dir", kwargs["output_dir"]])
        if kwargs.get("split_by_type"):
            cmd.append("--split-by-type")
        if kwargs.get("types"):
            cmd.extend(["--types", kwargs["types"]])
        if kwargs.get("tables"):
            cmd.extend(["--tables", kwargs["tables"]])
        if kwargs.get("managed_only"):
            cmd.append("--managed-only")
        if kwargs.get("unmanaged_only"):
            cmd.append("--unmanaged-only")
        if kwargs.get("include_drops"):
            cmd.append("--include-drops")
        if kwargs.get("schema"):
            cmd.extend(["--schema", kwargs["schema"]])
        if kwargs.get("description"):
            cmd.extend(["--description", kwargs["description"]])
        if kwargs.get("source"):
            cmd.extend(["--source", kwargs["source"]])
        # Execute command
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.cwd)

        return CommandResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            command=cmd,
        )

    def _run_chained_commands(self, commands: tuple, **kwargs) -> CommandResult:
        """
        Execute multiple commands in a single CLI invocation.

        DBLift supports command chaining: dblift info migrate info
        """
        cmd = self.cli_base.copy()

        # Add all commands
        cmd.extend(commands)

        # Add config
        cmd.extend(["--config", str(self.config_file)])
        cmd.extend(["--scripts", str(self.migrations_dir)])

        # Execute
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.cwd)

        return CommandResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            command=cmd,
        )


def get_cli_version() -> str:
    """
    Get the version of the production CLI.
    Useful for version-specific test logic.
    """
    result = subprocess.run(
        [sys.executable, "-m", DBLiftCLI.CLI_MODULE, "--version"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
