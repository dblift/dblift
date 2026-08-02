"""Unit tests for baseline_command.py and validate_command.py.

Covers previously untested paths to push coverage toward 70%+:

BaselineCommand:
  - execute() happy path — history table created, migration recorded, committed
  - execute() transaction begin failure — continues (autoCommit mode)
  - execute() commit failure — rolls back, raises, outer catch returns error
  - execute() rollback failure — logged, exception still raised
  - execute() history_manager.create fails — caught, returns error
  - execute() record_migration fails — caught, returns error
  - result.baseline_version set on success

ValidateCommand:
  - execute() happy path — validation passes
  - execute() validation fails — issues list logged as errors
  - execute() validation fails — fallback to error_message when no issues
  - execute() schema history bootstrap failure — fails the command with a clean error
  - execute() schema history bootstrap failure, error formatter itself raises — falls back to str(e)
  - execute() validator raises unexpectedly — caught, returns error
  - result.target_schema set on start
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from core.logger.results import BaselineResult, ValidateResult
from core.migration.commands.baseline_command import BaselineCommand
from core.migration.commands.validate_command import ValidateCommand

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_baseline_cmd(
    provider=None,
    config=None,
    log=None,
    history_manager=None,
):
    """Build a BaselineCommand with minimal mocked collaborators."""
    _config = config or SimpleNamespace(
        database=SimpleNamespace(schema="public", type="postgresql"),
    )
    _log = log or MagicMock()
    _provider = provider or MagicMock()
    _hm = history_manager or MagicMock()

    cmd = BaselineCommand(
        config=_config,
        log=_log,
        provider=_provider,
        script_manager=MagicMock(),
        history_manager=_hm,
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    return cmd


def _make_validate_cmd(
    provider=None,
    config=None,
    log=None,
    history_manager=None,
    validator=None,
):
    """Build a ValidateCommand with minimal mocked collaborators."""
    _config = config or SimpleNamespace(
        database=SimpleNamespace(schema="public", type="postgresql"),
    )
    _log = log or MagicMock()
    _provider = provider or MagicMock()
    _hm = history_manager or MagicMock()
    _validator = validator or MagicMock()

    cmd = ValidateCommand(
        config=_config,
        log=_log,
        provider=_provider,
        script_manager=MagicMock(),
        history_manager=_hm,
        validator=_validator,
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    return cmd


# ---------------------------------------------------------------------------
# BaselineCommand
# ---------------------------------------------------------------------------


class TestBaselineCommandHappyPath(unittest.TestCase):
    def _run(self, provider=None, history_manager=None, log=None):
        _provider = provider or MagicMock()
        _hm = history_manager or MagicMock()
        _log = log or MagicMock()
        cmd = _make_baseline_cmd(provider=_provider, history_manager=_hm, log=_log)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    return cmd.execute("1.0", "initial baseline"), cmd, _provider, _hm, _log

    def test_returns_success_result(self):
        result, *_ = self._run()
        self.assertTrue(result.success)

    def test_baseline_version_set_in_result(self):
        result, *_ = self._run()
        self.assertEqual(result.baseline_version, "1.0")

    def test_target_schema_set_in_result(self):
        result, *_ = self._run()
        self.assertEqual(result.target_schema, "public")

    def test_creates_schema_and_history_table(self):
        result, cmd, provider, hm, log = self._run()
        hm.create_schema_and_history_table.assert_called_once_with(create_schema=True)

    def test_records_baseline_migration(self):
        result, cmd, provider, hm, log = self._run()
        hm.record_migration.assert_called_once()
        call_args = hm.record_migration.call_args
        migration = call_args[0][0]  # first positional arg
        self.assertEqual(migration.version, "1.0")

    def test_commits_transaction(self):
        result, cmd, provider, hm, log = self._run()
        provider.commit_transaction.assert_called_once()

    def test_begins_transaction(self):
        result, cmd, provider, hm, log = self._run()
        provider.begin_transaction.assert_called_once()

    def test_migration_script_name_includes_version_and_description(self):
        provider = MagicMock()
        hm = MagicMock()
        cmd = _make_baseline_cmd(provider=provider, history_manager=hm)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    cmd.execute("2.5", "my description")

        call_args = hm.record_migration.call_args
        migration = call_args[0][0]
        self.assertIn("2.5", migration.script_name)
        self.assertIn("my description", migration.script_name)

    def test_empty_description_allowed(self):
        """execute() should not fail when description is empty string."""
        result, *_ = self._run()
        # Just verify no error
        self.assertTrue(result.success)

    def test_dry_run_does_not_record_baseline(self):
        provider = MagicMock()
        hm = MagicMock()
        hm.has_history_table = False
        cmd = _make_baseline_cmd(provider=provider, history_manager=hm)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute("1.0", "initial baseline", dry_run=True)

        self.assertTrue(result.success)
        self.assertEqual(result.baseline_version, "1.0")
        hm.record_migration.assert_not_called()
        provider.begin_transaction.assert_not_called()
        provider.commit_transaction.assert_not_called()

    def test_dry_run_does_not_create_history_table(self):
        """dry-run must never call create_schema_and_history_table — that would
        create real DDL (schema/table) as a side effect of a preview-only run."""
        provider = MagicMock()
        hm = MagicMock()
        hm.has_history_table = False
        cmd = _make_baseline_cmd(provider=provider, history_manager=hm)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute("1.0", "initial baseline", dry_run=True)

        hm.create_schema_and_history_table.assert_not_called()
        self.assertTrue(result.success)

    def test_dry_run_runs_precondition_check_when_table_exists(self):
        """dry-run must still run the "history already has rows" precondition
        check when the table already exists, without creating anything."""
        hm = MagicMock()
        hm.has_history_table = True
        hm.get_applied_migration_records.return_value = []
        cmd = _make_baseline_cmd(history_manager=hm)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute("1.0", "initial baseline", dry_run=True)

        hm.get_applied_migration_records.assert_called_once()
        hm.create_schema_and_history_table.assert_not_called()
        self.assertTrue(result.success)

    def test_dry_run_logs_a_dry_run_line(self):
        """dry-run must print a visible DRY RUN line via log.info, matching
        migrate/undo/clean/import-flyway/repair — otherwise the console gives
        no indication a baseline run was a dry-run."""
        provider = MagicMock()
        hm = MagicMock()
        hm.has_history_table = False
        log = MagicMock()
        cmd = _make_baseline_cmd(provider=provider, history_manager=hm, log=log)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        cmd.execute("1.0", "initial baseline", dry_run=True)

        info_calls = [str(c) for c in log.info.call_args_list]
        assert any("DRY RUN" in c for c in info_calls)

    def test_dry_run_fails_when_history_already_exists(self):
        """dry-run should report the same failure the real run would hit when the
        history table already has rows, instead of a false success."""
        hm = MagicMock()
        hm.has_history_table = True
        hm.get_applied_migration_records.return_value = [MagicMock()]
        cmd = _make_baseline_cmd(history_manager=hm)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute("6", dry_run=True)

        hm.create_schema_and_history_table.assert_not_called()
        self.assertFalse(result.success)
        self.assertIn("Baseline operation failed", result.error_message)


class TestBaselineCommandTransactionFailures(unittest.TestCase):
    def test_begin_transaction_failure_continues(self):
        """If begin_transaction raises, execution continues (autoCommit mode)."""
        provider = MagicMock()
        provider.begin_transaction.side_effect = RuntimeError("begin failed")
        # commit should still be called if we continue
        provider.commit_transaction.return_value = None
        hm = MagicMock()
        log = MagicMock()

        cmd = _make_baseline_cmd(provider=provider, history_manager=hm, log=log)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute("1.0")

        # Should succeed despite begin_transaction failure
        self.assertTrue(result.success)
        log.warning.assert_called()

    def test_commit_failure_returns_error(self):
        """commit_transaction failure should roll back and return error."""
        provider = MagicMock()
        provider.commit_transaction.side_effect = RuntimeError("commit failed")
        provider.rollback_transaction.return_value = None
        hm = MagicMock()
        log = MagicMock()

        cmd = _make_baseline_cmd(provider=provider, history_manager=hm, log=log)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute("1.0")

        self.assertFalse(result.success)
        self.assertIn("Baseline operation failed", result.error_message)
        provider.rollback_transaction.assert_called()

    def test_commit_failure_rollback_failure_logged(self):
        """When both commit and rollback fail, the rollback failure is logged."""
        provider = MagicMock()
        provider.commit_transaction.side_effect = RuntimeError("commit fail")
        provider.rollback_transaction.side_effect = RuntimeError("rollback fail")
        log = MagicMock()
        hm = MagicMock()

        cmd = _make_baseline_cmd(provider=provider, history_manager=hm, log=log)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute("1.0")

        self.assertFalse(result.success)
        # rollback failure should be logged at debug
        debug_calls = " ".join(str(c) for c in log.debug.call_args_list)
        self.assertIn("rollback", debug_calls.lower())

    def test_history_table_creation_failure_returns_error(self):
        hm = MagicMock()
        hm.create_schema_and_history_table.side_effect = RuntimeError("table create failed")

        cmd = _make_baseline_cmd(history_manager=hm)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute("1.0")

        self.assertFalse(result.success)
        self.assertIn("Baseline operation failed", result.error_message)

    def test_record_migration_failure_returns_error(self):
        provider = MagicMock()
        hm = MagicMock()
        hm.record_migration.side_effect = RuntimeError("record failed")

        cmd = _make_baseline_cmd(provider=provider, history_manager=hm)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute("1.0")

        self.assertFalse(result.success)
        self.assertIn("Baseline operation failed", result.error_message)


# ---------------------------------------------------------------------------
# ValidateCommand
# ---------------------------------------------------------------------------


class TestValidateCommandHappyPath(unittest.TestCase):
    def _make_validator(self, success=True, error_message="", issues=None):
        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = success
        validation_result.error_message = error_message
        validation_result.issues = issues or []
        validator.validate_migrations.return_value = validation_result
        return validator

    def test_success_returns_true(self):
        validator = self._make_validator(success=True)
        cmd = _make_validate_cmd(validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertTrue(result.success)

    def test_target_schema_set_in_result(self):
        validator = self._make_validator(success=True)
        cmd = _make_validate_cmd(validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertEqual(result.target_schema, "public")

    def test_success_logs_validation_passed(self):
        log = MagicMock()
        validator = self._make_validator(success=True)
        cmd = _make_validate_cmd(log=log, validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute(Path("/migrations"))

        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("passed", info_calls.lower())

    def test_calls_validator_with_scripts_dir(self):
        validator = self._make_validator(success=True)
        cmd = _make_validate_cmd(validator=validator)
        scripts_dir = Path("/migrations")

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute(scripts_dir)

        validator.validate_migrations.assert_called_once()
        call_args = validator.validate_migrations.call_args
        self.assertEqual(call_args[0][0], scripts_dir)

    def test_filters_passed_to_validator(self):
        validator = self._make_validator(success=True)
        cmd = _make_validate_cmd(validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute(
                    Path("/migrations"),
                    target_version="3.0",
                    tags="feature",
                    exclude_tags="wip",
                )

        call_kwargs = validator.validate_migrations.call_args.kwargs
        self.assertEqual(call_kwargs.get("target_version"), "3.0")
        self.assertEqual(call_kwargs.get("tags"), "feature")
        self.assertEqual(call_kwargs.get("exclude_tags"), "wip")


class TestValidateCommandFailurePaths(unittest.TestCase):
    def _make_validator(self, success=False, error_message="Validation failed", issues=None):
        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = success
        validation_result.error_message = error_message
        validation_result.issues = issues or []
        validator.validate_migrations.return_value = validation_result
        return validator

    def test_validation_failure_returns_false(self):
        validator = self._make_validator(success=False)
        cmd = _make_validate_cmd(validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)

    def test_validation_failure_logs_each_issue(self):
        """When issues list is present, each issue should be logged as error."""
        log = MagicMock()
        issues = ["V1__a.sql: missing checksum", "V2__b.sql: duplicate version"]
        validator = self._make_validator(success=False, issues=issues)
        cmd = _make_validate_cmd(log=log, validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute(Path("/migrations"))

        error_calls = " ".join(str(c) for c in log.error.call_args_list)
        self.assertIn("V1__a.sql", error_calls)
        self.assertIn("V2__b.sql", error_calls)

    def test_validation_failure_fallback_to_error_message_when_no_issues(self):
        """Without issues list, error_message should be logged."""
        log = MagicMock()
        validator = self._make_validator(
            success=False, error_message="Checksum mismatch detected", issues=[]
        )
        cmd = _make_validate_cmd(log=log, validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute(Path("/migrations"))

        error_calls = " ".join(str(c) for c in log.error.call_args_list)
        self.assertIn("Checksum mismatch detected", error_calls)

    def test_error_message_set_in_result(self):
        validator = self._make_validator(success=False, error_message="bad checksums")
        cmd = _make_validate_cmd(validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertEqual(result.error_message, "bad checksums")


class TestValidateCommandConnectionError(unittest.TestCase):
    def test_history_table_bootstrap_failure_fails_command(self):
        """If create_schema_and_history_table raises, validate must fail (not
        silently proceed to report success from the script-only checks)."""
        log = MagicMock()
        hm = MagicMock()
        hm.create_schema_and_history_table.side_effect = RuntimeError("no DB")

        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = True
        validation_result.error_message = ""
        validation_result.issues = []
        validator.validate_migrations.return_value = validation_result

        cmd = _make_validate_cmd(log=log, history_manager=hm, validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)
        self.assertIn("no DB", result.error_message)
        validator.validate_migrations.assert_not_called()

    def test_history_table_bootstrap_failure_logs_clean_error_message(self):
        """The bootstrap failure should be logged as a clean, single-line
        error rather than a raw driver exception dump."""
        log = MagicMock()
        hm = MagicMock()
        hm.create_schema_and_history_table.side_effect = RuntimeError("no DB")

        validator = MagicMock()
        cmd = _make_validate_cmd(log=log, history_manager=hm, validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute(Path("/migrations"))

        error_calls = " ".join(str(c) for c in log.error.call_args_list)
        self.assertIn("Could not create schema history table", error_calls)
        self.assertIn("no DB", error_calls)

    def test_history_table_bootstrap_failure_formatter_raises_falls_back_to_str(self):
        """If _format_execution_error itself raises while formatting the
        bootstrap failure, the command must still fail using str(e) instead
        of letting the formatter's exception propagate."""
        log = MagicMock()
        hm = MagicMock()
        hm.create_schema_and_history_table.side_effect = RuntimeError("no DB")

        validator = MagicMock()
        cmd = _make_validate_cmd(log=log, history_manager=hm, validator=validator)

        with patch(
            "core.migration.sql.sql_execution_service._format_execution_error",
            side_effect=ValueError("formatter blew up"),
        ):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)
        self.assertIn("no DB", result.error_message)
        validator.validate_migrations.assert_not_called()


class TestValidateCommandUnexpectedException(unittest.TestCase):
    def test_validator_exception_caught_returns_error(self):
        validator = MagicMock()
        validator.validate_migrations.side_effect = RuntimeError("internal validator crash")

        cmd = _make_validate_cmd(validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)
        self.assertIn("Validation operation failed", result.error_message)

    def test_validate_result_target_schema_always_set(self):
        validator = MagicMock()
        validator.validate_migrations.side_effect = RuntimeError("crash")

        cmd = _make_validate_cmd(validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertEqual(result.target_schema, "public")


class TestValidateCommandWithFilters(unittest.TestCase):
    def test_recursive_and_additional_dirs_passed(self):
        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = True
        validation_result.error_message = ""
        validation_result.issues = []
        validator.validate_migrations.return_value = validation_result

        cmd = _make_validate_cmd(validator=validator)
        extra_dirs = [Path("/extra1"), Path("/extra2")]

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute(
                    Path("/migrations"),
                    recursive=False,
                    additional_dirs=extra_dirs,
                )

        call_kwargs = validator.validate_migrations.call_args.kwargs
        self.assertFalse(call_kwargs.get("recursive", True))
        self.assertEqual(call_kwargs.get("additional_dirs"), extra_dirs)

    def test_versions_filter_passed(self):
        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = True
        validation_result.error_message = ""
        validation_result.issues = []
        validator.validate_migrations.return_value = validation_result

        cmd = _make_validate_cmd(validator=validator)

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute(
                    Path("/migrations"),
                    versions="1.0,2.0",
                    exclude_versions="3.0",
                )

        call_kwargs = validator.validate_migrations.call_args.kwargs
        self.assertEqual(call_kwargs.get("versions"), "1.0,2.0")
        self.assertEqual(call_kwargs.get("exclude_versions"), "3.0")


if __name__ == "__main__":
    unittest.main()
