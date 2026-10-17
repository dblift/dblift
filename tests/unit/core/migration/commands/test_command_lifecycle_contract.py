"""Guardrails for the command lifecycle skeleton.

The private lifecycle runner is intentionally incremental: it should make the
common preflight/header/body/footer order explicit without forcing every
command into the same shape before its current behavior is pinned.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from dblift.core.migration.commands.base_command import BaseCommand, PreflightConnectionError


def _make_command_stub() -> BaseCommand:
    command = BaseCommand.__new__(BaseCommand)
    command.log = MagicMock()
    command._log_command_header_update = MagicMock()
    command._log_command_completion = MagicMock()
    return command


def _make_result() -> SimpleNamespace:
    result = SimpleNamespace(success=True, error_message="", end_time=None)

    def set_error(message: str) -> None:
        result.success = False
        result.error_message = message

    result.set_error = set_error
    return result


@pytest.mark.unit
class TestCommandLifecycleRunner:
    def test_runner_orders_preflight_header_body_and_completion(self):
        command = _make_command_stub()
        result = _make_result()
        calls: list[str] = []

        command._log_command_header_update.side_effect = lambda *_a, **_k: calls.append("header")
        command._log_command_completion.side_effect = lambda *_a, **_k: calls.append("completion")

        returned = command._run_command_lifecycle(
            "info",
            result,
            body=lambda: calls.append("body"),
            preflight=lambda: calls.append("preflight"),
            before_body=lambda: calls.append("before_body"),
        )

        assert returned is result
        assert calls == ["preflight", "header", "before_body", "body", "completion"]
        command._log_command_header_update.assert_called_once_with("info")
        command._log_command_completion.assert_called_once_with("info", result)

    def test_body_exception_is_converted_to_result_error_and_footer(self):
        command = _make_command_stub()
        result = _make_result()

        def body() -> None:
            raise RuntimeError("boom")

        command._run_command_lifecycle(
            "info",
            result,
            body=body,
            error_message_prefix="Info operation failed",
        )

        assert result.success is False
        assert result.error_message == "Info operation failed: boom"
        command.log.error.assert_called_once_with("Info operation failed: boom")
        command._log_command_completion.assert_called_once_with("info", result)

    def test_preflight_exception_still_propagates_without_footer(self):
        command = _make_command_stub()
        result = _make_result()

        with pytest.raises(RuntimeError, match="connect failed"):
            command._run_command_lifecycle(
                "info",
                result,
                body=lambda: None,
                preflight=lambda: (_ for _ in ()).throw(RuntimeError("connect failed")),
            )

        command._log_command_header_update.assert_not_called()
        command._log_command_completion.assert_not_called()


@pytest.mark.unit
class TestCommandLifecycleIntentionalDeviations:
    """Source-level guardrails for commands not migrated to the runner yet."""

    def _source(self, relative_path: str) -> str:
        return Path(relative_path).read_text(encoding="utf-8")

    def test_clean_retains_custom_dry_run_connection_handling(self):
        source = self._source("dblift/core/migration/commands/clean_command.py")
        assert "dry_run" in source
        assert "list_droppable_objects" in source
        assert "_run_command_lifecycle" not in source

    def test_undo_retains_multiple_early_completion_paths(self):
        source = self._source("dblift/core/migration/commands/undo_command.py")
        assert "should_undo_version" in source
        assert source.count('_log_command_completion("undo"') >= 3
        assert "_run_command_lifecycle" not in source


@pytest.mark.unit
class TestDryRunFooterMessage:
    """BUG-02: dry-run footer must say 'N migration(s) would be applied', not
    'No pending migrations found'."""

    def _run_log_completion(self, result):
        from dblift.core.migration.commands.base_command import BaseCommand

        cmd = BaseCommand.__new__(BaseCommand)
        cmd.log = MagicMock()
        cmd._log_command_header_update = MagicMock()
        cmd._has_own_console_footer = True  # suppress Rich panel output in unit tests
        cmd._log_text_block = MagicMock()
        cmd._build_footer_panel = MagicMock()
        cmd._format_command_footer = MagicMock(return_value="")
        cmd._log_command_completion("migrate", result)
        # Return the applied_scripts that were built inside the method by
        # capturing what _format_command_footer was called with.
        call_kwargs = cmd._format_command_footer.call_args
        return call_kwargs[1].get("applied_scripts") if call_kwargs else None

    def test_dry_run_shows_count_not_no_pending(self):
        from dblift.core.logger.results import MigrateResult

        result = MigrateResult()
        result.dry_run_count = 3
        applied_scripts = self._run_log_completion(result)
        assert applied_scripts is not None
        assert len(applied_scripts) == 1
        assert "3" in applied_scripts[0]
        assert "would be applied" in applied_scripts[0]
        assert "No pending" not in applied_scripts[0]

    def test_no_pending_message_when_truly_empty(self):
        from dblift.core.logger.results import MigrateResult

        result = MigrateResult()
        applied_scripts = self._run_log_completion(result)
        assert applied_scripts == ["No pending migrations found"]


@pytest.mark.unit
class TestPrintMainHeaderOnceRouting:
    """OBS-01: _print_main_header_once must emit to stderr, not stdout."""

    def _make_command_with_console_log(self):
        from dblift.core.logger.log import ConsoleLog
        from dblift.core.migration.commands.base_command import BaseCommand

        cmd = BaseCommand.__new__(BaseCommand)
        cmd.log = MagicMock(spec=ConsoleLog)
        cmd.config = MagicMock()
        cmd.config.database.database_name = "testdb"
        cmd.config.database.database = "testdb"
        cmd.config.database.schema = "public"
        return cmd

    def test_banner_fallback_goes_to_stderr(self, capsys):
        import dblift.core.migration.commands.base_command as cmd_mod

        cmd = self._make_command_with_console_log()
        # Reset the flag so the header is actually printed
        original = getattr(cmd_mod, "_console_main_header_printed", None)
        cmd_mod._console_main_header_printed = False
        try:
            with patch(
                "dblift.core.logger.log.TextFormatter.format_header",
                return_value="DBLIFT v1.4.1 — testdb",
            ):
                cmd._print_main_header_once()
        finally:
            if original is not None:
                cmd_mod._console_main_header_printed = original
            else:
                del cmd_mod._console_main_header_printed

        captured = capsys.readouterr()
        assert captured.out == "", "banner must NOT appear on stdout"
        assert "DBLIFT" in captured.err, "banner must appear on stderr"


def _build_command(command_class, **collaborators):
    """Build *command_class* with MagicMock collaborators, overridable by keyword."""
    deps = {
        "config": SimpleNamespace(database=SimpleNamespace(schema="public", type="postgresql")),
        "log": MagicMock(),
        "provider": MagicMock(),
        "script_manager": MagicMock(),
        "history_manager": MagicMock(),
        "validator": MagicMock(),
        "execution_engine": MagicMock(),
        "migration_helpers": MagicMock(),
        "state_manager": MagicMock(),
        "migration_ui": MagicMock(),
        "migration_rules": MagicMock(),
    }
    deps.update(collaborators)
    command = command_class(**deps)
    command._run_preflight = MagicMock()
    command._log_command_header_update = MagicMock()
    command._log_command_completion = MagicMock()
    return command


def _validate_case(fail_body: bool):
    from dblift.core.migration.commands.validate_command import ValidateCommand

    command = _build_command(ValidateCommand)
    verdict = MagicMock(success=True, error_message="", issues=[])
    command.validator.validate_snapshot.return_value = verdict
    if fail_body:
        command.state_manager.build_validation_snapshot.side_effect = RuntimeError("x")
    return command, lambda: command.execute(Path("/migrations")), "validate"


def _baseline_case(fail_body: bool):
    from dblift.core.migration.commands.baseline_command import BaselineCommand
    from dblift.db.provider_interfaces import TransactionalProvider

    provider = MagicMock()
    provider.__class__ = TransactionalProvider
    command = _build_command(BaselineCommand, provider=provider)
    if fail_body:
        command.history_manager.record_migration.side_effect = RuntimeError("x")
    return command, lambda: command.execute("1.0", "initial"), "baseline"


def _import_flyway_case(fail_body: bool):
    from dblift.core.migration.commands.import_flyway_command import ImportFlywayCommand

    command = _build_command(ImportFlywayCommand)
    command.state_manager.resolve_flyway_source_table.return_value = "flyway_schema_history"
    command.state_manager.history_source_exists.return_value = True
    command.state_manager.read_history_rows.return_value = []
    if fail_body:
        command.state_manager.resolve_flyway_source_table.side_effect = RuntimeError("x")
    return command, lambda: command.execute(Path("/scripts")), "import-flyway"


def _repair_case(fail_body: bool):
    from dblift.core.migration.commands.repair_command import RepairCommand
    from dblift.core.migration.state.migration_state import MigrationState

    command = _build_command(RepairCommand)
    command.state_manager.build_state.return_value = MigrationState()
    command.state_manager.get_grouped_migrations.return_value = {}
    if fail_body:
        command.state_manager.build_state.side_effect = RuntimeError("x")
    return command, lambda: command.execute(Path("/migrations")), "repair"


_LIFECYCLE_COMMANDS = {
    "validate": (_validate_case, "Validation operation failed"),
    "baseline": (_baseline_case, "Baseline operation failed"),
    "import-flyway": (_import_flyway_case, "Import Flyway operation failed"),
    "repair": (_repair_case, "Repair operation failed"),
}


@pytest.mark.unit
@pytest.mark.parametrize("name", list(_LIFECYCLE_COMMANDS))
class TestMigrationCommandsShareTheLifecycle:
    """validate, baseline, import-flyway and repair log one footer on every exit."""

    def test_footer_logged_once_on_success(self, name):
        build, _prefix = _LIFECYCLE_COMMANDS[name]
        command, run, command_name = build(fail_body=False)

        result = run()

        assert result.success is True
        command._log_command_completion.assert_called_once_with(command_name, result)

    def test_footer_logged_once_on_body_error(self, name):
        build, prefix = _LIFECYCLE_COMMANDS[name]
        command, run, command_name = build(fail_body=True)

        result = run()

        assert result.success is False
        assert result.error_message == f"{prefix}: x"
        command._log_command_completion.assert_called_once_with(command_name, result)

    def test_preflight_error_propagates(self, name):
        build, _prefix = _LIFECYCLE_COMMANDS[name]
        command, run, _command_name = build(fail_body=False)
        command._run_preflight.side_effect = PreflightConnectionError("down")

        with pytest.raises(PreflightConnectionError):
            run()

        command._log_command_completion.assert_not_called()


@pytest.mark.unit
def test_repair_safety_error_has_no_prefix():
    from dblift.core.migration.commands.repair_command import RepairSafetyError

    command, run, _name = _repair_case(fail_body=False)
    command._detect_missing_migrations = MagicMock(side_effect=RepairSafetyError("refusing"))

    result = run()

    assert result.success is False
    assert result.error_message == "refusing"
    command._log_command_completion.assert_called_once_with("repair", result)


@pytest.mark.unit
class TestBaselineHeader:
    """The baseline header is logged once per run; only a dry run carries ``dry_run``."""

    def test_dry_run_header_marks_dry_run(self):
        from dblift.core.migration.commands.baseline_command import BaselineCommand

        command = _build_command(BaselineCommand)
        command.history_manager.has_history_table = False

        command.execute("1.0", "initial", dry_run=True)

        command._log_command_header_update.assert_called_once_with(
            "baseline", baseline_version="1.0", dry_run=True
        )

    def test_real_run_header_has_no_dry_run(self):
        command, run, _name = _baseline_case(fail_body=False)

        run()

        command._log_command_header_update.assert_called_once_with(
            "baseline", baseline_version="1.0"
        )
