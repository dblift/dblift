"""
Direct CLI runner for integration tests that contributes to code coverage.

This module provides an alternative to cli_runner.py that calls main() directly
instead of via subprocess, allowing integration tests to contribute to code coverage.

Usage:
    from tests.integration.helpers.cli_runner_direct import DBLiftCLIDirect

    cli = DBLiftCLIDirect(config_file, migrations_dir)
    result = cli.migrate()
    assert result.success

This is a drop-in replacement for DBLiftCLI that can be used when
you want integration tests to contribute to code coverage. Both interfaces
are compatible.
"""

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from cli.main import main


@dataclass
class CommandResult:
    """Structured result from a CLI command execution.

    NOTE: Intentionally duplicated in cli_runner.py (standalone subprocess module).
    This is the canonical version re-exported by helpers/__init__.py.
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


# The true (non-captured) streams, recorded the first time we see a real stream.
# Concurrent in-process runs swap the global sys.stdout/stderr to per-call
# StringIO captures; if a racing thread saved another thread's capture as its
# "original" and restored to it, the global would be left pointing at a dead
# StringIO and a later sequential capture (e.g. `info`) would read empty. Always
# restore to the true stream so the global can never be left on a capture buffer.
_TRUE_STDOUT = None
_TRUE_STDERR = None


@contextmanager
def capture_main_execution(argv_list: List[str]):
    """Context manager to capture main() execution with mocked sys.argv and sys.exit."""
    global _TRUE_STDOUT, _TRUE_STDERR
    if not isinstance(sys.stdout, StringIO):
        _TRUE_STDOUT = sys.stdout
    if not isinstance(sys.stderr, StringIO):
        _TRUE_STDERR = sys.stderr

    original_argv = sys.argv.copy()
    original_stdout = _TRUE_STDOUT if _TRUE_STDOUT is not None else sys.stdout
    original_stderr = _TRUE_STDERR if _TRUE_STDERR is not None else sys.stderr
    original_exit = sys.exit

    stdout_capture = StringIO()
    stderr_capture = StringIO()
    exit_code = [0]  # Use list to allow modification from nested function

    def mock_exit(code: int = 0):
        """Mock sys.exit to capture exit code instead of actually exiting."""
        exit_code[0] = code
        raise SystemExit(code)

    try:
        # Set up mocked environment
        sys.argv = argv_list
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture
        from core.logger.console import reset_stderr_console, reset_stdout_console

        reset_stdout_console()
        reset_stderr_console()

        with patch("sys.exit", side_effect=mock_exit):
            try:
                main()
            except SystemExit as e:
                exit_code[0] = e.code if isinstance(e.code, int) else 0

        # Get captured output
        stdout_value = stdout_capture.getvalue()
        stderr_value = stderr_capture.getvalue()

        yield CommandResult(
            returncode=exit_code[0],
            stdout=stdout_value,
            stderr=stderr_value,
            command=argv_list,
        )
    finally:
        # Restore original state
        sys.argv = original_argv
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        reset_stdout_console()
        reset_stderr_console()


def _is_coverage_enabled() -> bool:
    """Check if coverage is currently enabled (pytest-cov or coverage module active)."""
    # Check if coverage module is imported (indicates coverage is active)
    if "coverage" in sys.modules or "pytest_cov" in sys.modules:
        return True

    # Check environment variables (coverage tools set these)
    if "COVERAGE_PROCESS_START" in os.environ or "COV_CORE" in os.environ:
        return True

    # Check if pytest is running with coverage (check command line args)
    # This is a fallback - pytest-cov sets up coverage before tests run
    for arg in sys.argv:
        if "--cov" in arg or "pytest_cov" in arg:
            return True

    return False


class DBLiftCLIDirect:
    """
    Direct CLI runner that calls main() directly (for code coverage).

    This is a drop-in replacement for DBLiftCLI that calls main() directly
    instead of via subprocess, allowing integration tests to contribute to
    code coverage.

    Example:
        >>> cli = DBLiftCLIDirect(config_file, migrations_dir)
        >>> result = cli.migrate()
        >>> assert result.success
        >>> assert "V1_0_0" in result.stdout
    """

    CLI_MODULE = "cli.main"  # Keep same interface as DBLiftCLI

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
            cwd: Working directory for command execution (not used in direct mode)
        """
        self.config_file = Path(config_file)
        self.migrations_dir = Path(migrations_dir)
        self.cwd = cwd or Path.cwd()

        self._use_subprocess = False

        if self._use_subprocess:
            # Import subprocess runner lazily
            from tests.integration.helpers.cli_runner import DBLiftCLI as DBLiftCLISubprocess

            self._subprocess_runner = DBLiftCLISubprocess(
                self.config_file, self.migrations_dir, self.cwd
            )

    def _build_argv(self, command: str, **kwargs) -> List[str]:
        """Build argv list for main() function."""
        argv = ["dblift"]  # Script name

        # Add global arguments BEFORE the subcommand
        if kwargs.get("log_level"):
            argv.extend(["--log-level", kwargs["log_level"]])

        if kwargs.get("log_format"):
            for fmt in kwargs["log_format"]:
                argv.extend(["--log-format", fmt])

        argv.append(command)

        # Support grouped subcommands, e.g. command="data", data_command="plan" | "apply" | "status" | "undo"
        data_sub = kwargs.pop("data_command", None) or kwargs.pop("sub_command", None)
        if data_sub:
            argv.append(data_sub)

            # Positional arguments for data subcommands
            if data_sub == "apply" and kwargs.get("plan_file"):
                argv.append(str(kwargs["plan_file"]))
            elif data_sub == "undo":
                undo_id = kwargs.get("id") or kwargs.get("undo_id")
                if undo_id:
                    argv.append(str(undo_id))

        # Add config (always required)
        argv.extend(["--config", str(self.config_file)])

        # Add migration path(s) - only for commands that need it
        if command != "snapshot":
            argv.extend(["--scripts", str(self.migrations_dir)])

            # Add additional script directories if provided
            if kwargs.get("additional_scripts"):
                for script_dir in kwargs["additional_scripts"]:
                    argv.extend(["--scripts", str(script_dir)])

        # Add command-specific options
        if kwargs.get("target_version"):
            argv.extend(["--target-version", kwargs["target_version"]])

        if kwargs.get("baseline_version"):
            argv.extend(["--baseline-version", kwargs["baseline_version"]])

        if kwargs.get("baseline_description"):
            argv.extend(["--baseline-description", kwargs["baseline_description"]])

        if kwargs.get("tags"):
            tags_val = kwargs["tags"]
            if isinstance(tags_val, list):
                tags_val = ",".join(tags_val)
            argv.extend(["--tags", tags_val])

        if kwargs.get("exclude_tags"):
            exclude_tags_val = kwargs["exclude_tags"]
            if isinstance(exclude_tags_val, list):
                exclude_tags_val = ",".join(exclude_tags_val)
            argv.extend(["--exclude-tags", exclude_tags_val])

        if kwargs.get("versions"):
            versions_val = kwargs["versions"]
            if isinstance(versions_val, list):
                versions_val = ",".join(versions_val)
            argv.extend(["--versions", versions_val])

        if kwargs.get("exclude_versions"):
            exclude_versions_val = kwargs["exclude_versions"]
            if isinstance(exclude_versions_val, list):
                exclude_versions_val = ",".join(exclude_versions_val)
            argv.extend(["--exclude-versions", exclude_versions_val])

        if kwargs.get("placeholders"):
            placeholders_val = kwargs["placeholders"]
            if isinstance(placeholders_val, list):
                argv.extend(["--placeholders", *placeholders_val])
            else:
                argv.extend(["--placeholders", placeholders_val])

        # Add boolean flags
        if kwargs.get("dry_run"):
            argv.append("--dry-run")

        if kwargs.get("mark_as_executed"):
            argv.append("--mark-as-executed")

        if kwargs.get("show_sql"):
            argv.append("--show-sql")

        if kwargs.get("ignore_unmanaged"):
            argv.append("--ignore-unmanaged")

        if kwargs.get("skip_validation"):
            argv.append("--skip-validation")

        if kwargs.get("clean_enabled"):
            argv.append("--clean-enabled")

        # Export-schema specific options
        if kwargs.get("output"):
            argv.extend(["--output", kwargs["output"]])
        if kwargs.get("output_dir"):
            argv.extend(["--output-dir", kwargs["output_dir"]])
        if kwargs.get("split_by_type"):
            argv.append("--split-by-type")
        if kwargs.get("types"):
            argv.extend(["--types", kwargs["types"]])
        if kwargs.get("tables"):
            argv.extend(["--tables", kwargs["tables"]])
        if kwargs.get("managed_only"):
            argv.append("--managed-only")
        if kwargs.get("unmanaged_only"):
            argv.append("--unmanaged-only")
        if kwargs.get("include_drops"):
            argv.append("--include-drops")
        if kwargs.get("schema"):
            argv.extend(["--schema", kwargs["schema"]])
        if kwargs.get("description"):
            argv.extend(["--description", kwargs["description"]])
        if kwargs.get("source"):
            argv.extend(["--source", kwargs["source"]])
        if kwargs.get("snapshot_model"):
            argv.extend(["--snapshot-model", kwargs["snapshot_model"]])

        # Data (Lane B) options (plan/status use --dataset; apply uses positional plan_file + --force)
        if kwargs.get("dataset"):
            argv.extend(["--dataset", str(kwargs["dataset"])])
        if kwargs.get("force"):
            argv.append("--force")

        return argv

    def _run_command(self, command: str, **kwargs) -> CommandResult:
        """Execute a single CLI command by calling main() directly or via subprocess."""
        # If coverage + driver, use subprocess to avoid segfaults
        if self._use_subprocess:
            # Delegate to subprocess runner's _run_command method
            return self._subprocess_runner._run_command(command, **kwargs)

        # Otherwise, use direct mode for coverage
        argv = self._build_argv(command, **kwargs)

        with capture_main_execution(argv) as result:
            return result

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
        """Run migrate command with options."""
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
        """Run info command with options."""
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
        """Run baseline command."""
        return self._run_command(
            "baseline",
            baseline_version=baseline_version,
            baseline_description=baseline_description,
            dry_run=dry_run,
            log_level=log_level,
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
        """Run undo command."""
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

    def diff(
        self,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        ignore_unmanaged: bool = False,
        **kwargs,
    ) -> CommandResult:
        """Run diff command."""
        return self._run_command(
            "diff",
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            ignore_unmanaged=ignore_unmanaged,
            **kwargs,
        )

    def export_schema(
        self,
        output_file: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        split_by_type: bool = False,
        types: Optional[str] = None,
        tables: Optional[str] = None,
        managed_only: bool = False,
        unmanaged_only: bool = False,
        include_drops: bool = False,
        schema: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs,
    ) -> CommandResult:
        """Run export-schema command."""
        output_kwargs = {}
        if output_file:
            output_kwargs["output"] = str(output_file)
        if output_dir:
            output_kwargs["output_dir"] = str(output_dir)
        if split_by_type:
            output_kwargs["split_by_type"] = True
        if types:
            output_kwargs["types"] = types
        if tables:
            output_kwargs["tables"] = tables
        if managed_only:
            output_kwargs["managed_only"] = True
        if unmanaged_only:
            output_kwargs["unmanaged_only"] = True
        if include_drops:
            output_kwargs["include_drops"] = True
        if schema:
            output_kwargs["schema"] = schema
        if description:
            output_kwargs["description"] = description

        return self._run_command("export-schema", **output_kwargs, **kwargs)

    def snapshot(
        self,
        output: str,
        source: str = "database-stored",
        **kwargs,
    ) -> CommandResult:
        """Run snapshot command."""
        return self._run_command(
            "snapshot",
            output=output,
            source=source,
            **kwargs,
        )

    def data_plan(self, dataset: str, output: Optional[str] = None, **kwargs) -> CommandResult:
        """Run `data plan --dataset X [--output ...]`."""
        return self._run_command(
            "data",
            data_command="plan",
            dataset=dataset,
            output=output,
            **kwargs,
        )

    def data_apply(self, plan_file: str, force: bool = False, **kwargs) -> CommandResult:
        """Run `data apply <plan.json> [--force]`."""
        return self._run_command(
            "data",
            data_command="apply",
            plan_file=plan_file,
            force=force,
            **kwargs,
        )

    def data_status(self, dataset: str, **kwargs) -> CommandResult:
        """Run `data status --dataset X`."""
        return self._run_command(
            "data",
            data_command="status",
            dataset=dataset,
            **kwargs,
        )

    def data_undo(self, cid: str, dataset: str, force: bool = False, **kwargs) -> CommandResult:
        """Run `data undo <id> --dataset X [--force]`."""
        return self._run_command(
            "data",
            data_command="undo",
            id=cid,
            dataset=dataset,
            force=force,
            **kwargs,
        )

    def chain(self, *commands: str, **kwargs) -> CommandResult:
        """Execute multiple commands in sequence (command chaining)."""
        # If coverage + driver, use subprocess to avoid segfaults
        if self._use_subprocess:
            return self._subprocess_runner.chain(*commands, **kwargs)

        # Otherwise, use direct mode for coverage
        argv = ["dblift"]

        # Add global arguments
        if kwargs.get("log_level"):
            argv.extend(["--log-level", kwargs["log_level"]])

        # Add all commands
        argv.extend(commands)

        # Add config
        argv.extend(["--config", str(self.config_file)])
        argv.extend(["--scripts", str(self.migrations_dir)])

        with capture_main_execution(argv) as result:
            return result


def get_cli_version() -> str:
    """Get CLI version by calling main() directly with --version."""
    argv = ["dblift", "--version"]
    with capture_main_execution(argv) as result:
        if result.success:
            return result.stdout.strip()
        return ""
