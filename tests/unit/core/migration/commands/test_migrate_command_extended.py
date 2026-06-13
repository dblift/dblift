"""Extended unit tests for migrate_command.py.

Covers previously untested paths to push coverage toward 70%+:
  - MigrateCommand construction
  - _initialize_migration_execution
  - _handle_dry_run
  - _mark_migrations_as_executed — success, failure
  - _execute_before_callbacks — versioned/repeatable filtering
  - _execute_after_callbacks — skipped on error, versioned/repeatable
  - _handle_failed_migration — journal, no prior error_message
  - _execute_single_migration — success, engine error, exception path
  - _execute_migration_loop — stops after first failure
  - _update_final_state
  - execute() — no pending, dry_run, mark_as_executed, lock failure, commit error
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from core.logger.results import MigrateResult, MigrationInfo
from core.migration.commands.migrate_command import MigrateCommand
from core.migration.migration import MigrationType
from core.migration.state.migration_state import MigrationState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cmd(
    provider=None,
    config=None,
    log=None,
    history_manager=None,
    script_manager=None,
    state_manager=None,
    execution_engine=None,
    migration_helpers=None,
    validator=None,
    snapshot_service=None,
    journal=None,
):
    """Build a MigrateCommand with minimal mocked collaborators."""
    _config = config or MagicMock()
    _config.database.schema = "public"
    _config.database.type = "postgresql"

    _log = log or MagicMock()
    _provider = provider or MagicMock()
    _hm = history_manager or MagicMock()
    _sm = script_manager or MagicMock()
    _stm = state_manager or MagicMock()
    _ee = execution_engine or MagicMock()
    _mh = migration_helpers or MagicMock()
    _validator = validator  # None is valid (skips validation)

    cmd = MigrateCommand(
        config=_config,
        log=_log,
        provider=_provider,
        script_manager=_sm,
        history_manager=_hm,
        validator=_validator,
        execution_engine=_ee,
        migration_helpers=_mh,
        state_manager=_stm,
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
        snapshot_service=snapshot_service,
        journal=journal,
    )
    return cmd


def _make_migration(
    script_name="V1__init.sql", version="1", description="init", type_=None, checksum=123
):
    """Minimal migration stand-in.

    Use SimpleNamespace so we can pass it freely without enum attribute restrictions.
    The type is kept as the real MigrationType enum so comparisons (m.type == MigrationType.REPEATABLE)
    work correctly. type_.value is the enum's own property and is never assigned here.
    """
    actual_type = type_ if type_ is not None else MigrationType.SQL
    return SimpleNamespace(
        script_name=script_name,
        version=version,
        description=description,
        type=actual_type,
        checksum=checksum,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestMigrateCommandConstruction(unittest.TestCase):
    def test_snapshot_service_stored(self):
        svc = MagicMock()
        cmd = _make_cmd(snapshot_service=svc)
        self.assertIs(cmd.snapshot_service, svc)

    def test_snapshot_service_defaults_to_none(self):
        cmd = _make_cmd()
        self.assertIsNone(cmd.snapshot_service)

    def test_log_defaults_to_nulllog_when_none(self):
        from core.logger import NullLog

        cmd = MigrateCommand(
            config=MagicMock(),
            log=None,
            provider=MagicMock(),
            script_manager=MagicMock(),
            history_manager=MagicMock(),
            validator=None,
            execution_engine=MagicMock(),
            migration_helpers=MagicMock(),
            state_manager=MagicMock(),
            migration_ui=MagicMock(),
            migration_rules=MagicMock(),
        )
        self.assertIsInstance(cmd.log, NullLog)


# ---------------------------------------------------------------------------
# _handle_dry_run
# ---------------------------------------------------------------------------


class TestHandleDryRun(unittest.TestCase):
    def test_logs_each_pending_migration(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        m1 = _make_migration("V1__a.sql")
        m2 = _make_migration("V2__b.sql")
        result = MigrateResult()

        with patch.object(cmd, "_log_command_completion"):
            cmd._handle_dry_run([m1, m2], result)

        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("V1__a.sql", info_calls)
        self.assertIn("V2__b.sql", info_calls)

    def test_returns_result(self):
        cmd = _make_cmd()
        result = MigrateResult()
        with patch.object(cmd, "_log_command_completion"):
            returned = cmd._handle_dry_run([], result)
        self.assertIs(returned, result)

    def test_show_sql_collects_executable_sql(self):
        cmd = _make_cmd()
        cmd.execution_engine.get_executable_sql_statements.return_value = [
            "CREATE TABLE users (id INT)"
        ]
        migration = _make_migration("V1__a.sql", version="1", description="create users")
        result = MigrateResult()

        with patch.object(cmd, "_log_command_completion"):
            returned = cmd._handle_dry_run([migration], result, show_sql=True)

        self.assertIs(returned, result)
        self.assertTrue(result.show_sql)
        self.assertEqual(len(result.sql), 1)
        self.assertEqual(result.sql[0].script, "V1__a.sql")
        self.assertEqual(result.sql[0].statements, ["CREATE TABLE users (id INT)"])


# ---------------------------------------------------------------------------
# _mark_migrations_as_executed
# ---------------------------------------------------------------------------


class TestMarkMigrationsAsExecuted(unittest.TestCase):
    def test_records_each_migration_in_history(self):
        history_manager = MagicMock()
        cmd = _make_cmd(history_manager=history_manager)
        m1 = _make_migration("V1__a.sql")
        m2 = _make_migration("V2__b.sql")
        result = MigrateResult()

        success = cmd._mark_migrations_as_executed([m1, m2], result)

        self.assertTrue(success)
        self.assertEqual(history_manager.record_migration.call_count, 2)
        self.assertEqual(len(result.migrations), 2)

    def test_returns_false_on_record_error(self):
        history_manager = MagicMock()
        history_manager.record_migration.side_effect = RuntimeError("DB error")
        cmd = _make_cmd(history_manager=history_manager)
        m1 = _make_migration("V1__a.sql")
        result = MigrateResult()

        success = cmd._mark_migrations_as_executed([m1], result)

        self.assertFalse(success)
        self.assertIsNotNone(result.error_message)

    def test_logs_each_migration_as_executed(self):
        log = MagicMock()
        cmd = _make_cmd(log=log, history_manager=MagicMock())
        m1 = _make_migration("V1__a.sql")
        result = MigrateResult()

        cmd._mark_migrations_as_executed([m1], result)

        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("V1__a.sql", info_calls)


# ---------------------------------------------------------------------------
# _execute_before_callbacks
# ---------------------------------------------------------------------------


class TestExecuteBeforeCallbacks(unittest.TestCase):
    def test_always_calls_before_migrate(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        cmd._execute_before_callbacks(Path("/migrations"), [], [], True, None, None)
        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertIn("beforeMigrate", events)

    def test_calls_before_versioned_when_versioned_migrations_present(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        m = _make_migration()
        cmd._execute_before_callbacks(Path("/migrations"), [m], [], True, None, None)
        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertIn("beforeVersioned", events)

    def test_skips_before_versioned_when_no_versioned_migrations(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        cmd._execute_before_callbacks(Path("/migrations"), [], [], True, None, None)
        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertNotIn("beforeVersioned", events)

    def test_calls_before_repeatable_when_repeatable_migrations_present(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        m = _make_migration(type_=MigrationType.REPEATABLE)
        cmd._execute_before_callbacks(Path("/migrations"), [], [m], True, None, None)
        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertIn("beforeRepeatable", events)

    def test_skips_before_repeatable_when_no_repeatable_migrations(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        cmd._execute_before_callbacks(Path("/migrations"), [], [], True, None, None)
        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertNotIn("beforeRepeatable", events)


# ---------------------------------------------------------------------------
# _execute_after_callbacks
# ---------------------------------------------------------------------------


class TestExecuteAfterCallbacks(unittest.TestCase):
    def test_skips_all_callbacks_when_error_present(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        result = MigrateResult()
        result.set_error("Migration failed")

        cmd._execute_after_callbacks(Path("/migrations"), [], [], True, None, None, result)

        cmd._execute_callbacks.assert_not_called()

    def test_calls_after_migrate_when_no_error(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        result = MigrateResult()

        cmd._execute_after_callbacks(Path("/migrations"), [], [], True, None, None, result)

        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertIn("afterMigrate", events)

    def test_calls_after_versioned_when_versioned_present(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        m = _make_migration()
        result = MigrateResult()

        cmd._execute_after_callbacks(Path("/migrations"), [m], [], True, None, None, result)

        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertIn("afterVersioned", events)

    def test_calls_after_repeatable_when_repeatable_present(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        m = _make_migration(type_=MigrationType.REPEATABLE)
        result = MigrateResult()

        cmd._execute_after_callbacks(Path("/migrations"), [], [m], True, None, None, result)

        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertIn("afterRepeatable", events)


# ---------------------------------------------------------------------------
# _handle_failed_migration
# ---------------------------------------------------------------------------


class TestHandleFailedMigration(unittest.TestCase):
    def test_sets_error_when_no_prior_error(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        m = _make_migration("V1__a.sql")
        result = MigrateResult()

        cmd._handle_failed_migration(
            m, 0.0, RuntimeError("oops"), result, Path("/migrations"), True, None, None
        )

        self.assertFalse(result.success)
        self.assertIn("oops", result.error_message)

    def test_does_not_overwrite_existing_error_message(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        m = _make_migration("V1__a.sql")
        result = MigrateResult()
        result.set_error("original error")

        cmd._handle_failed_migration(
            m, 0.0, RuntimeError("new error"), result, Path("/migrations"), True, None, None
        )

        # error_message should still be the original one
        self.assertIn("original error", result.error_message)

    def test_ends_journal_when_present(self):
        journal = MagicMock()
        cmd = _make_cmd(journal=journal)
        cmd._execute_callbacks = MagicMock()
        m = _make_migration("V1__a.sql")
        result = MigrateResult()

        import time

        start_time = time.time()
        cmd._handle_failed_migration(
            m, start_time, RuntimeError("err"), result, Path("/migrations"), True, None, None
        )

        journal.end_migration.assert_called_once()
        call_kwargs = journal.end_migration.call_args
        self.assertFalse(call_kwargs.kwargs.get("success", True))

    def test_executes_after_migrate_error_callback(self):
        cmd = _make_cmd()
        cmd._execute_callbacks = MagicMock()
        m = _make_migration("V1__a.sql")
        result = MigrateResult()

        cmd._handle_failed_migration(
            m, 0.0, RuntimeError("err"), result, Path("/migrations"), True, None, None
        )

        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertIn("afterMigrateError", events)


# ---------------------------------------------------------------------------
# _execute_single_migration
# ---------------------------------------------------------------------------


class TestExecuteSingleMigration(unittest.TestCase):
    def test_successful_migration_returns_true(self):
        execution_engine = MagicMock()
        cmd = _make_cmd(execution_engine=execution_engine)
        cmd._execute_callbacks = MagicMock()
        cmd.journal = None
        m = _make_migration("V1__a.sql")
        result = MigrateResult()

        with patch("core.migration.commands.migrate_command._emit_script_event"):
            success = cmd._execute_single_migration(
                m, Path("/migrations"), True, None, None, result
            )

        self.assertTrue(success)
        self.assertEqual(len(result.migrations), 1)

    def test_engine_sets_error_returns_false(self):
        """When execution_engine sets result.error_message, returns False."""

        def _set_error(migration, result):
            result.set_error("migration failed")

        execution_engine = MagicMock()
        execution_engine.execute_migration.side_effect = _set_error
        cmd = _make_cmd(execution_engine=execution_engine)
        cmd._execute_callbacks = MagicMock()
        cmd.journal = None
        m = _make_migration("V1__a.sql")
        result = MigrateResult()

        with patch("core.migration.commands.migrate_command._emit_script_event"):
            success = cmd._execute_single_migration(
                m, Path("/migrations"), True, None, None, result
            )

        self.assertFalse(success)

    def test_exception_in_execute_migration_returns_false(self):
        execution_engine = MagicMock()
        execution_engine.execute_migration.side_effect = RuntimeError("driver error")
        cmd = _make_cmd(execution_engine=execution_engine)
        cmd._execute_callbacks = MagicMock()
        cmd.journal = None
        m = _make_migration("V1__a.sql")
        result = MigrateResult()

        with patch("core.migration.commands.migrate_command._emit_script_event"):
            success = cmd._execute_single_migration(
                m, Path("/migrations"), True, None, None, result
            )

        self.assertFalse(success)

    def test_journal_started_and_ended_on_success(self):
        journal = MagicMock()
        execution_engine = MagicMock()
        cmd = _make_cmd(execution_engine=execution_engine, journal=journal)
        cmd._execute_callbacks = MagicMock()
        m = _make_migration("V1__a.sql")
        result = MigrateResult()

        with patch("core.migration.commands.migrate_command._emit_script_event"):
            cmd._execute_single_migration(m, Path("/migrations"), True, None, None, result)

        journal.start_migration.assert_called_once_with("V1__a.sql", details=unittest.mock.ANY)
        journal.end_migration.assert_called_once()
        kwargs = journal.end_migration.call_args.kwargs
        self.assertTrue(kwargs.get("success", False))


# ---------------------------------------------------------------------------
# _execute_migration_loop
# ---------------------------------------------------------------------------


class TestExecuteMigrationLoop(unittest.TestCase):
    def test_stops_after_first_failure(self):
        """Migration loop should break after a failure (not execute next migration)."""
        cmd = _make_cmd()
        call_count = {"n": 0}

        def _failing_single(migration, *args, **kwargs):
            call_count["n"] += 1
            return False  # fail always

        cmd._execute_single_migration = _failing_single
        m1 = _make_migration("V1__a.sql")
        m2 = _make_migration("V2__b.sql")
        result = MigrateResult()

        cmd._execute_migration_loop([m1, m2], Path("/migrations"), True, None, None, result)

        self.assertEqual(call_count["n"], 1)

    def test_executes_all_on_success(self):
        cmd = _make_cmd()
        cmd._execute_single_migration = MagicMock(return_value=True)
        m1 = _make_migration("V1__a.sql")
        m2 = _make_migration("V2__b.sql")
        result = MigrateResult()

        cmd._execute_migration_loop([m1, m2], Path("/migrations"), True, None, None, result)

        self.assertEqual(cmd._execute_single_migration.call_count, 2)

    def test_show_sql_collects_statement_before_failed_execution(self):
        cmd = _make_cmd()
        cmd._execute_single_migration = MagicMock(return_value=False)
        cmd.execution_engine.get_executable_sql_statements.return_value = [
            "CREATE TABLE users (id INT)"
        ]
        migration = _make_migration("V1__a.sql", version="1", description="create users")
        result = MigrateResult()
        result.show_sql = True

        cmd._execute_migration_loop([migration], Path("/migrations"), True, None, None, result)

        cmd._execute_single_migration.assert_called_once()
        self.assertEqual(len(result.sql), 1)
        self.assertEqual(result.sql[0].script, "V1__a.sql")
        self.assertEqual(result.sql[0].statements, ["CREATE TABLE users (id INT)"])


# ---------------------------------------------------------------------------
# _update_final_state
# ---------------------------------------------------------------------------


class TestUpdateFinalState(unittest.TestCase):
    def test_sets_current_schema_version_when_available(self):
        state_manager = MagicMock()
        post_state = MigrationState()
        post_state.applied_objects = []
        state_manager.build_state.return_value = post_state
        state_manager.get_current_version.return_value = "3.0"

        cmd = _make_cmd(state_manager=state_manager)
        result = MigrateResult()

        cmd._update_final_state(result, Path("/migrations"), True, None, None)

        self.assertEqual(result.current_schema_version, "3.0")

    def test_does_not_set_version_when_none(self):
        state_manager = MagicMock()
        post_state = MigrationState()
        state_manager.build_state.return_value = post_state
        state_manager.get_current_version.return_value = None

        cmd = _make_cmd(state_manager=state_manager)
        result = MigrateResult()

        cmd._update_final_state(result, Path("/migrations"), True, None, None)

        self.assertIsNone(result.current_schema_version)


# ---------------------------------------------------------------------------
# execute() — top-level integration
# ---------------------------------------------------------------------------


class TestMigrateCommandExecute(unittest.TestCase):
    def _make_execute_cmd(self, pending=None, lock_acquired=True):
        provider = MagicMock()
        provider.acquire_migration_lock.return_value = lock_acquired
        provider.release_migration_lock.return_value = None
        provider.commit_transaction.return_value = None

        history_manager = MagicMock()
        history_manager.create_schema_and_history_table.return_value = None
        history_manager.get_applied_migrations.return_value = []

        state = MigrationState()
        state.applied_objects = []
        state.pending_objects = pending or []

        state_manager = MagicMock()
        state_manager.build_state.return_value = state
        state_manager.get_current_version.return_value = None

        migration_helpers = MagicMock()
        migration_helpers.setup_migration_parameters.return_value = (True, None)

        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"

        cmd = _make_cmd(
            provider=provider,
            config=config,
            history_manager=history_manager,
            state_manager=state_manager,
            migration_helpers=migration_helpers,
        )
        return cmd

    def test_no_pending_migrations_returns_success(self):
        cmd = self._make_execute_cmd(pending=[])

        with patch("core.licensing._guard._refresh_state", return_value=None):
            with patch.object(cmd, "_run_preflight"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_current_schema_version"):
                        with patch.object(cmd, "_log_command_completion"):
                            result = cmd.execute(Path("/migrations"))

        self.assertTrue(result.success)

    def test_dry_run_does_not_apply_migrations(self):
        m = _make_migration("V1__a.sql")
        cmd = self._make_execute_cmd(pending=[m])

        with patch("core.licensing._guard._refresh_state", return_value=None):
            with patch.object(cmd, "_run_preflight"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_current_schema_version"):
                        with patch.object(cmd, "_log_command_completion"):
                            result = cmd.execute(Path("/migrations"), dry_run=True)

        self.assertTrue(result.success)
        cmd.provider.acquire_migration_lock.assert_not_called()

    def test_lock_not_acquired_returns_error(self):
        m = _make_migration("V1__a.sql")
        cmd = self._make_execute_cmd(pending=[m], lock_acquired=False)

        with patch("core.licensing._guard._refresh_state", return_value=None):
            with patch.object(cmd, "_run_preflight"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_current_schema_version"):
                        with patch.object(cmd, "_log_command_completion"):
                            result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)
        self.assertIn("migration lock", result.error_message.lower())

    def test_mark_as_executed_records_without_running(self):
        m = _make_migration("V1__a.sql")
        cmd = self._make_execute_cmd(pending=[m])

        with patch("core.licensing._guard._refresh_state", return_value=None):
            with patch.object(cmd, "_run_preflight"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_current_schema_version"):
                        with patch.object(cmd, "_update_final_state"):
                            with patch.object(cmd, "_log_command_completion"):
                                result = cmd.execute(Path("/migrations"), mark_as_executed=True)

        cmd.history_manager.record_migration.assert_called()
        # Should not call execute_migration
        cmd.execution_engine.execute_migration.assert_not_called()

    def test_mark_as_executed_commit_failure_returns_error(self):
        m = _make_migration("V1__a.sql")
        cmd = self._make_execute_cmd(pending=[m])
        cmd.provider.commit_transaction.side_effect = RuntimeError("commit failed")

        with patch("core.licensing._guard._refresh_state", return_value=None):
            with patch.object(cmd, "_run_preflight"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_current_schema_version"):
                        with patch.object(cmd, "_log_command_completion"):
                            result = cmd.execute(Path("/migrations"), mark_as_executed=True)

        self.assertFalse(result.success)

    def test_lock_released_even_after_exception(self):
        """Migration lock should always be released."""
        m = _make_migration("V1__a.sql")
        cmd = self._make_execute_cmd(pending=[m])

        # Make migration execution raise
        def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        with patch("core.licensing._guard._refresh_state", return_value=None):
            with patch.object(cmd, "_run_preflight"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_current_schema_version"):
                        with patch.object(
                            cmd, "_execute_migration_loop", side_effect=RuntimeError("boom")
                        ):
                            with patch.object(cmd, "_execute_before_callbacks"):
                                with patch.object(cmd, "_execute_after_callbacks"):
                                    with patch.object(cmd, "_log_command_completion"):
                                        with patch.object(cmd, "_update_final_state"):
                                            result = cmd.execute(Path("/migrations"))

        cmd.provider.release_migration_lock.assert_called()

    def test_result_target_schema_set(self):
        cmd = self._make_execute_cmd(pending=[])

        with patch("core.licensing._guard._refresh_state", return_value=None):
            with patch.object(cmd, "_run_preflight"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_current_schema_version"):
                        with patch.object(cmd, "_log_command_completion"):
                            result = cmd.execute(Path("/migrations"))

        self.assertEqual(result.target_schema, "public")

    def test_outer_exception_caught(self):
        """An exception raised inside the main try block should be caught and returned as error."""
        m = _make_migration("V1__a.sql")
        cmd = self._make_execute_cmd(pending=[m])

        # _initialize_migration_execution raises inside the try block → outer except catches it
        with patch("core.licensing._guard._refresh_state", return_value=None):
            with patch.object(
                cmd, "_initialize_migration_execution", side_effect=RuntimeError("internal error")
            ):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)
        self.assertIn("Migration operation failed", result.error_message)


class TestStrictModeWarningSupression(unittest.TestCase):
    """BUG-01: strict mode must not emit a non-strict 'Applying anyway' warning.

    When --strict is active, build_state() must receive strict_mode=True so
    _is_versioned_pending raises ValueError immediately instead of emitting
    the misleading 'Applying anyway; use --strict' warning.
    """

    def _make_strict_cmd(self):
        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"
        config.strict_mode = True
        cmd = _make_cmd(config=config)
        return cmd

    def test_build_state_called_with_strict_mode_true(self):
        cmd = self._make_strict_cmd()
        state = MagicMock()
        state.pending_objects = []
        state.applied_objects = []
        cmd.state_manager.build_state.return_value = state

        with patch.object(cmd, "_initialize_migration_execution", return_value=(True, True, [])):
            with patch.object(cmd, "_update_final_state"):
                with patch.object(cmd, "_log_command_completion"):
                    cmd.execute(Path("/migrations"))

        call_kwargs = cmd.state_manager.build_state.call_args[1]
        self.assertTrue(
            call_kwargs.get("strict_mode"),
            "build_state must be called with strict_mode=True when config.strict_mode=True",
        )

    def test_strict_mode_error_surfaces_directly_without_operation_failed_prefix(self):
        """StrictModeError from _is_versioned_pending is surfaced directly, not wrapped.

        PR #241 Bugbot: previously the catch was ``except ValueError`` which
        also swallowed unrelated ValueErrors. Now narrowed to
        ``StrictModeError`` (a ``ValueError`` subclass).
        """
        from core.migration.state.migration_state_manager import StrictModeError

        cmd = self._make_strict_cmd()
        strict_msg = (
            "Strict mode: out-of-order migration V1.5__foo.sql "
            "(version 1.5 <= current version 2). Renumber the script."
        )
        cmd.state_manager.build_state.side_effect = StrictModeError(strict_msg)

        with patch.object(cmd, "_initialize_migration_execution", return_value=(True, True, [])):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, strict_msg)
        # Must NOT have the "Migration operation failed:" prefix
        self.assertNotIn("Migration operation failed", result.error_message)

    def test_unrelated_value_error_still_gets_operation_failed_prefix(self):
        """Regression guard: a plain ValueError elsewhere in the migrate
        flow must NOT be silently surfaced — it gets the broader
        "Migration operation failed:" treatment so operators can
        distinguish it from a strict-mode violation. (PR #241 Bugbot.)
        """
        cmd = self._make_strict_cmd()
        cmd.state_manager.build_state.side_effect = ValueError("something else broke")

        with patch.object(cmd, "_initialize_migration_execution", return_value=(True, True, [])):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)
        self.assertIn("Migration operation failed", result.error_message)
        self.assertIn("something else broke", result.error_message)

    def test_non_strict_mode_does_not_pass_strict_to_build_state(self):
        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"
        config.strict_mode = False
        cmd = _make_cmd(config=config)
        state = MagicMock()
        state.pending_objects = []
        state.applied_objects = []
        cmd.state_manager.build_state.return_value = state

        with patch.object(cmd, "_initialize_migration_execution", return_value=(True, True, [])):
            with patch.object(cmd, "_update_final_state"):
                with patch.object(cmd, "_log_command_completion"):
                    cmd.execute(Path("/migrations"))

        call_kwargs = cmd.state_manager.build_state.call_args[1]
        self.assertFalse(call_kwargs.get("strict_mode", False))


if __name__ == "__main__":
    unittest.main()
