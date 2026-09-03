"""Extended unit tests for repair_command.py.

Covers previously untested paths to push coverage toward 70%+:
  - RepairCommand.execute() — happy path, dry_run, no repairs needed, exception paths
  - _build_migration_state — exception fallback to empty state
  - _detect_checksum_changes — empty / non-empty checksum_changes
  - _detect_checksum_drift — fallback when load fails, all_applied_objects fallback
  - _is_failed_migration — various inputs
  - _delete_failed_migration_entry — oracle dialect, non-transactional, fallback paths
  - _execute_repair_loop — CHECKSUM_MISMATCH, MISSING_SCRIPT, FAILED_MIGRATION,
    transaction rollback, commit failure
  - _validate_post_repair_state — remaining issues, exception swallowed
  - _build_repair_summary — all summary parts
  - _count_candidate_missing — module-level helper
  - RepairSafetyError handling in execute()
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from dblift.core.logger.results import RepairResult
from dblift.core.migration.commands.repair_command import (
    RepairCommand,
    RepairSafetyError,
    _count_candidate_missing,
)
from dblift.core.migration.state.migration_state import MigrationState
from dblift.db.provider_interfaces import TransactionalProvider

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
):
    """Build a RepairCommand with minimal mocked collaborators."""
    if config is None:
        _config = MagicMock()
        _config.database.schema = "public"
        _config.database.type = "postgresql"
    else:
        _config = config

    _log = log or MagicMock()
    _provider = provider or MagicMock()
    _hm = history_manager or MagicMock()
    _sm = script_manager or MagicMock()
    _stm = state_manager or MagicMock()

    cmd = RepairCommand(
        config=_config,
        log=_log,
        provider=_provider,
        script_manager=_sm,
        history_manager=_hm,
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=_stm,
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    return cmd


def _make_applied(script_name, version="1", type_name="SQL"):
    """Minimal applied migration stand-in."""
    return SimpleNamespace(
        script_name=script_name,
        version=version,
        description="",
        type=SimpleNamespace(name=type_name),
        checksum=100,
    )


# ---------------------------------------------------------------------------
# _count_candidate_missing (module-level helper)
# ---------------------------------------------------------------------------


class TestCountCandidateMissing(unittest.TestCase):
    def test_counts_regular_migrations(self):
        applied = [
            _make_applied("V1__a.sql"),
            _make_applied("V2__b.sql"),
        ]
        count = _count_candidate_missing(applied, set())
        self.assertEqual(count, 2)

    def test_skips_delete_type(self):
        applied = [
            _make_applied("V1__a.sql", type_name="DELETE"),
        ]
        count = _count_candidate_missing(applied, set())
        self.assertEqual(count, 0)

    def test_skips_baseline_type(self):
        applied = [
            _make_applied("B1__base.sql", type_name="BASELINE"),
        ]
        count = _count_candidate_missing(applied, set())
        self.assertEqual(count, 0)

    def test_skips_already_deleted_scripts(self):
        applied = [_make_applied("V1__a.sql")]
        count = _count_candidate_missing(applied, {"V1__a.sql"})
        self.assertEqual(count, 0)

    def test_skips_entries_with_no_script_name(self):
        applied = [SimpleNamespace(script_name="", version="1", type=None)]
        count = _count_candidate_missing(applied, set())
        self.assertEqual(count, 0)

    def test_string_type_delete_skipped(self):
        applied = [SimpleNamespace(script_name="V1__a.sql", version="1", type="DELETE")]
        count = _count_candidate_missing(applied, set())
        self.assertEqual(count, 0)

    def test_string_type_baseline_skipped(self):
        applied = [SimpleNamespace(script_name="B1__b.sql", version="1", type="BASELINE")]
        count = _count_candidate_missing(applied, set())
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# _build_migration_state
# ---------------------------------------------------------------------------


class TestBuildMigrationState(unittest.TestCase):
    def test_returns_state_on_success(self):
        state_manager = MagicMock()
        expected_state = MigrationState()
        state_manager.build_state.return_value = expected_state

        cmd = _make_cmd(state_manager=state_manager)
        result = cmd._build_migration_state(Path("/migrations"))
        self.assertIs(result, expected_state)

    def test_returns_empty_state_on_exception(self):
        state_manager = MagicMock()
        state_manager.build_state.side_effect = RuntimeError("build failed")

        cmd = _make_cmd(state_manager=state_manager)
        result = cmd._build_migration_state(Path("/migrations"))
        self.assertIsInstance(result, MigrationState)
        self.assertEqual(result.applied_objects, [])


# ---------------------------------------------------------------------------
# _detect_checksum_changes
# ---------------------------------------------------------------------------


class TestDetectChecksumChanges(unittest.TestCase):
    def test_returns_empty_when_no_checksum_changes(self):
        cmd = _make_cmd()
        state = MigrationState()
        repairs = cmd._detect_checksum_changes(state)
        self.assertEqual(repairs, [])

    def test_returns_repair_entry_per_change(self):
        cmd = _make_cmd()
        state = MigrationState()
        change = SimpleNamespace(
            script_name="V1__a.sql",
            previous_checksum=100,
            current_checksum=200,
        )
        state.checksum_changes = [change]

        repairs = cmd._detect_checksum_changes(state)
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["type"], "CHECKSUM_MISMATCH")
        self.assertEqual(repairs[0]["script"], "V1__a.sql")
        self.assertEqual(repairs[0]["old_checksum"], 100)
        self.assertEqual(repairs[0]["new_checksum"], 200)


# ---------------------------------------------------------------------------
# _detect_checksum_drift
# ---------------------------------------------------------------------------


class TestDetectChecksumDrift(unittest.TestCase):
    def test_returns_mismatch_when_checksums_differ(self):
        from dblift.core.migration.migration import MigrationType

        script_manager = MagicMock()
        fs_migration = SimpleNamespace(script_name="V1__a.sql", checksum=200)
        script_manager.load_migration_scripts.return_value = {"1": [fs_migration]}

        cmd = _make_cmd(script_manager=script_manager)
        applied = SimpleNamespace(
            script_name="V1__a.sql",
            version="1",
            type=MigrationType.SQL,
            checksum=100,
        )
        state = MigrationState()
        state.all_applied_objects = [applied]

        repairs = cmd._detect_checksum_drift(state, [], Path("/migrations"))
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["type"], "CHECKSUM_MISMATCH")

    def test_no_mismatch_when_checksums_match(self):
        from dblift.core.migration.migration import MigrationType

        script_manager = MagicMock()
        fs_migration = SimpleNamespace(script_name="V1__a.sql", checksum=100)
        script_manager.load_migration_scripts.return_value = {"1": [fs_migration]}

        cmd = _make_cmd(script_manager=script_manager)
        applied = SimpleNamespace(
            script_name="V1__a.sql",
            version="1",
            type=MigrationType.SQL,
            checksum=100,
        )
        state = MigrationState()
        state.all_applied_objects = [applied]

        repairs = cmd._detect_checksum_drift(state, [], Path("/migrations"))
        self.assertEqual(repairs, [])

    def test_skips_scripts_already_in_existing_repairs(self):
        from dblift.core.migration.migration import MigrationType

        script_manager = MagicMock()
        fs_migration = SimpleNamespace(script_name="V1__a.sql", checksum=200)
        script_manager.load_migration_scripts.return_value = {"1": [fs_migration]}

        cmd = _make_cmd(script_manager=script_manager)
        applied = SimpleNamespace(
            script_name="V1__a.sql",
            version="1",
            type=MigrationType.SQL,
            checksum=100,
        )
        state = MigrationState()
        state.all_applied_objects = [applied]

        # V1__a.sql already in existing_repairs — should not duplicate
        existing = [{"script": "V1__a.sql", "type": "CHECKSUM_MISMATCH"}]
        repairs = cmd._detect_checksum_drift(state, existing, Path("/migrations"))
        self.assertEqual(repairs, [])

    def test_fallback_to_applied_objects_when_all_applied_not_list(self):
        from dblift.core.migration.migration import MigrationType

        script_manager = MagicMock()
        fs_migration = SimpleNamespace(script_name="V1__a.sql", checksum=200)
        script_manager.load_migration_scripts.return_value = {"1": [fs_migration]}

        cmd = _make_cmd(script_manager=script_manager)
        applied = SimpleNamespace(
            script_name="V1__a.sql",
            version="1",
            type=MigrationType.SQL,
            checksum=100,
        )
        state = MigrationState()
        # all_applied_objects is not a list — should fall back to applied_objects
        state.all_applied_objects = "not-a-list"
        state.applied_objects = [applied]

        repairs = cmd._detect_checksum_drift(state, [], Path("/migrations"))
        self.assertEqual(len(repairs), 1)

    def test_load_failure_returns_empty_with_warning(self):
        script_manager = MagicMock()
        script_manager.load_migration_scripts.side_effect = RuntimeError("load error")
        log = MagicMock()

        cmd = _make_cmd(script_manager=script_manager, log=log)
        state = MigrationState()
        state.all_applied_objects = []

        repairs = cmd._detect_checksum_drift(state, [], Path("/migrations"))
        self.assertEqual(repairs, [])
        log.warning.assert_called()

    def test_returns_mismatch_when_db_checksum_failed_to_parse(self):
        """A stored checksum that isn't parseable as an int (e.g. a manually
        corrupted history row) surfaces as ``None`` after normalization —
        see ``normalize_migration_checksum``. That row must still be flagged
        for repair, not silently skipped because one side of the comparison
        is ``None``.
        """
        from dblift.core.migration.migration import MigrationType

        script_manager = MagicMock()
        fs_migration = SimpleNamespace(script_name="V1__a.sql", checksum=1223190650)
        script_manager.load_migration_scripts.return_value = {"1": [fs_migration]}

        cmd = _make_cmd(script_manager=script_manager)
        applied = SimpleNamespace(
            script_name="V1__a.sql",
            version="1",
            type=MigrationType.SQL,
            checksum=None,  # normalize_migration_checksum("deadbeef") -> None
        )
        state = MigrationState()
        state.all_applied_objects = [applied]

        repairs = cmd._detect_checksum_drift(state, [], Path("/migrations"))
        self.assertEqual(len(repairs), 1)
        self.assertEqual(repairs[0]["type"], "CHECKSUM_MISMATCH")
        self.assertEqual(repairs[0]["script"], "V1__a.sql")
        self.assertIsNone(repairs[0]["old_checksum"])
        self.assertEqual(repairs[0]["new_checksum"], 1223190650)


# ---------------------------------------------------------------------------
# _is_failed_migration
# ---------------------------------------------------------------------------


class TestIsFailedMigration(unittest.TestCase):
    def test_returns_false_for_empty_script(self):
        cmd = _make_cmd()
        self.assertFalse(cmd._is_failed_migration("", None))

    def test_returns_false_when_state_is_none(self):
        cmd = _make_cmd()
        self.assertFalse(cmd._is_failed_migration("V1__a.sql", None))

    def test_returns_true_when_in_failed_objects(self):
        cmd = _make_cmd()
        state = MigrationState()
        failed = SimpleNamespace(script_name="V1__a.sql")
        state.failed_objects = [failed]
        self.assertTrue(cmd._is_failed_migration("V1__a.sql", state))

    def test_returns_false_when_not_in_failed_objects(self):
        cmd = _make_cmd()
        state = MigrationState()
        state.failed_objects = [SimpleNamespace(script_name="V2__b.sql")]
        self.assertFalse(cmd._is_failed_migration("V1__a.sql", state))


# ---------------------------------------------------------------------------
# _delete_failed_migration_entry
# ---------------------------------------------------------------------------


class TestDeleteFailedMigrationEntry(unittest.TestCase):
    """The command delegates the delete; the history manager owns the statement.

    Which literal a dialect uses for ``False``, and whether the delete is
    SQL at all, is the history manager's business — relational backends
    emit a parameterised DELETE, document stores call their SDK.
    """

    class _NonTransactionalDdlProvider(TransactionalProvider):
        def __init__(self):
            self.connection = MagicMock()

        def begin_transaction(self):
            pass

        def commit_transaction(self):
            pass

        def rollback_transaction(self):
            pass

        def supports_transactional_ddl(self):
            return False

        def get_schema_qualified_name(self, schema, table):
            return f'"{schema}"."{table}"'

    @staticmethod
    def _make_cmd_with_history_manager(rows_deleted=1, provider=None):
        if provider is None:
            provider = MagicMock()
            provider.connection = MagicMock()
            provider.get_schema_qualified_name.return_value = '"public"."dblift_schema_history"'

        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"

        history_manager = MagicMock()
        history_manager.normalized_history_table = "dblift_schema_history"
        history_manager.delete_failed_migration_entry.return_value = bool(rows_deleted)

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            cmd = _make_cmd(provider=provider, config=config, history_manager=history_manager)
        return cmd, provider, history_manager

    def test_delegates_to_the_history_manager(self):
        cmd, _provider, history_manager = self._make_cmd_with_history_manager()
        repair = {"script": "V1__a.sql", "version": "1"}
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            deleted = cmd._delete_failed_migration_entry(repair, result)

        self.assertTrue(deleted)
        self.assertEqual(result.failed_migrations_removed, 1)
        history_manager.delete_failed_migration_entry.assert_called_once_with("V1__a.sql")

    def test_command_builds_no_sql_of_its_own(self):
        """No DELETE text is composed in the command any more."""
        cmd, provider, _history_manager = self._make_cmd_with_history_manager()
        repair = {"script": "V1__a.sql", "version": "1"}

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            cmd._delete_failed_migration_entry(repair, RepairResult())

        provider.execute_statement.assert_not_called()

    def test_non_transactional_ddl_repair_warns_retry_may_hit_existing_objects(self):
        provider = self._NonTransactionalDdlProvider()
        config = MagicMock()
        config.database.schema = "DBLIFT_TEST"
        config.database.type = "oracle"

        history_manager = MagicMock()
        history_manager.normalized_history_table = "DBLIFT_SCHEMA_HISTORY"
        history_manager.delete_failed_migration_entry.return_value = 1

        cmd = _make_cmd(provider=provider, config=config, history_manager=history_manager)
        repair = {"script": "V1__users.sql", "version": "1"}
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            deleted = cmd._delete_failed_migration_entry(repair, result)

        self.assertTrue(deleted)
        warning_text = " ".join(str(call.args[0]) for call in cmd.log.warning.call_args_list)
        self.assertIn("object already exists", warning_text)
        self.assertIn("clean --clean-enabled", warning_text)

    def test_returns_false_when_no_rows_deleted(self):
        cmd, _provider, _history_manager = self._make_cmd_with_history_manager(rows_deleted=0)
        repair = {"script": "V1__a.sql", "version": "1"}
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            deleted = cmd._delete_failed_migration_entry(repair, result)

        self.assertFalse(deleted)
        self.assertEqual(result.failed_migrations_removed, 0)

    def test_command_does_not_interpret_row_counts_itself(self):
        """Unknown-rowcount handling belongs to the facade, not the command."""
        import inspect

        from dblift.core.migration.commands.repair_command import RepairCommand

        source = inspect.getsource(RepairCommand._delete_failed_migration_entry)
        self.assertNotIn("SELECT 1 FROM", source)
        self.assertNotIn("rows_affected", source)

    def test_exception_propagates(self):
        cmd, _provider, history_manager = self._make_cmd_with_history_manager()
        history_manager.delete_failed_migration_entry.side_effect = RuntimeError("DB error")
        repair = {"script": "V1__a.sql", "version": "1"}

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            with self.assertRaises(RuntimeError):
                cmd._delete_failed_migration_entry(repair, RepairResult())


# ---------------------------------------------------------------------------
# _execute_repair_loop
# ---------------------------------------------------------------------------


class TestExecuteRepairLoop(unittest.TestCase):
    def _make_cmd_for_repair_loop(self):
        provider = MagicMock()
        provider.begin_transaction.return_value = None
        provider.commit_transaction.return_value = None

        history_manager = MagicMock()
        history_manager.repair_checksum.return_value = True
        history_manager.record_migration.return_value = None
        history_manager.normalized_history_table = "dblift_schema_history"

        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"

        cmd = _make_cmd(provider=provider, config=config, history_manager=history_manager)
        return cmd, provider

    def test_checksum_mismatch_repair(self):
        cmd, provider = self._make_cmd_for_repair_loop()
        repairs = [{"type": "CHECKSUM_MISMATCH", "script": "V1__a.sql", "new_checksum": 200}]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result)

        self.assertFalse(had_error)
        self.assertEqual(executed, 1)
        self.assertEqual(result.checksums_fixed, 1)

    def test_checksum_mismatch_string_checksum_converted_to_int(self):
        cmd, provider = self._make_cmd_for_repair_loop()
        repairs = [{"type": "CHECKSUM_MISMATCH", "script": "V1__a.sql", "new_checksum": "200"}]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result)

        self.assertFalse(had_error)
        # repair_checksum should be called with int 200
        cmd.history_manager.repair_checksum.assert_called_once_with("V1__a.sql", 200)

    def test_checksum_mismatch_none_checksum_raises_error(self):
        cmd, provider = self._make_cmd_for_repair_loop()
        repairs = [{"type": "CHECKSUM_MISMATCH", "script": "V1__a.sql", "new_checksum": None}]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result)

        self.assertTrue(had_error)
        self.assertIsNotNone(result.error_message)

    def test_checksum_mismatch_repair_checksum_returns_false_raises_error(self):
        provider = MagicMock()
        history_manager = MagicMock()
        history_manager.repair_checksum.return_value = False  # No row updated
        history_manager.normalized_history_table = "dblift_schema_history"

        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"

        cmd = _make_cmd(provider=provider, config=config, history_manager=history_manager)
        repairs = [{"type": "CHECKSUM_MISMATCH", "script": "V1__a.sql", "new_checksum": 200}]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result)

        self.assertTrue(had_error)

    def test_missing_script_repair_creates_delete_entry(self):
        cmd, provider = self._make_cmd_for_repair_loop()
        repairs = [
            {
                "type": "MISSING_SCRIPT",
                "script": "V1__a.sql",
                "version": "1",
                "description": "initial setup",
                "original_type": None,
            }
        ]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result)

        self.assertFalse(had_error)
        self.assertEqual(executed, 1)
        self.assertEqual(result.deleted_migrations_marked, 1)
        cmd.history_manager.record_migration.assert_called_once()

    def test_missing_script_repair_with_original_type_object(self):
        cmd, provider = self._make_cmd_for_repair_loop()
        original_type = SimpleNamespace(name="REPEATABLE")
        repairs = [
            {
                "type": "MISSING_SCRIPT",
                "script": "R__my_script.sql",
                "version": None,
                "description": "",
                "original_type": original_type,
            }
        ]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result)

        self.assertFalse(had_error)
        self.assertEqual(executed, 1)

    def test_failed_migration_repair(self):
        provider = MagicMock()
        provider.begin_transaction.return_value = None
        provider.commit_transaction.return_value = None
        provider.query_executor = MagicMock()
        provider.query_executor.execute_statement.return_value = 1
        provider.connection = MagicMock()
        provider.get_schema_qualified_name.return_value = '"public"."history"'

        history_manager = MagicMock()
        history_manager.normalized_history_table = "dblift_schema_history"
        history_manager.delete_failed_migration_entry.return_value = 1

        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"

        cmd = _make_cmd(provider=provider, config=config, history_manager=history_manager)
        repairs = [
            {"type": "FAILED_MIGRATION", "script": "V1__a.sql", "version": "1", "description": ""}
        ]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result)

        self.assertFalse(had_error)
        self.assertEqual(executed, 1)
        self.assertEqual(result.failed_migrations_removed, 1)

    def test_checksum_mismatch_on_failed_row_deletes_instead_of_updates(self):
        """When CHECKSUM_MISMATCH targets a failed row, should delete it instead."""
        provider = MagicMock()
        provider.begin_transaction.return_value = None
        provider.commit_transaction.return_value = None
        provider.query_executor = MagicMock()
        provider.query_executor.execute_statement.return_value = 1
        provider.connection = MagicMock()
        provider.get_schema_qualified_name.return_value = '"public"."history"'

        history_manager = MagicMock()
        history_manager.normalized_history_table = "dblift_schema_history"
        history_manager.delete_failed_migration_entry.return_value = 1

        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"

        cmd = _make_cmd(provider=provider, config=config, history_manager=history_manager)
        state = MigrationState()
        failed = SimpleNamespace(script_name="V1__a.sql")
        state.failed_objects = [failed]

        repairs = [{"type": "CHECKSUM_MISMATCH", "script": "V1__a.sql", "new_checksum": 200}]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result, migration_state=state)

        self.assertFalse(had_error)
        # repair_checksum should NOT be called
        history_manager.repair_checksum.assert_not_called()
        # failed_migrations_removed should be incremented
        self.assertEqual(result.failed_migrations_removed, 1)

    def test_error_triggers_rollback(self):
        provider = MagicMock()
        provider.begin_transaction.return_value = None
        provider.rollback_transaction.return_value = None

        history_manager = MagicMock()
        history_manager.repair_checksum.return_value = False  # causes error
        history_manager.normalized_history_table = "dblift_schema_history"

        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"

        cmd = _make_cmd(provider=provider, config=config, history_manager=history_manager)
        repairs = [{"type": "CHECKSUM_MISMATCH", "script": "V1__a.sql", "new_checksum": 200}]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result)

        self.assertTrue(had_error)
        provider.rollback_transaction.assert_called()

    def test_commit_failure_triggers_rollback(self):
        provider = MagicMock()
        provider.begin_transaction.return_value = None
        provider.commit_transaction.side_effect = RuntimeError("commit failed")
        provider.rollback_transaction.return_value = None

        history_manager = MagicMock()
        history_manager.repair_checksum.return_value = True
        history_manager.normalized_history_table = "dblift_schema_history"

        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"

        cmd = _make_cmd(provider=provider, config=config, history_manager=history_manager)
        repairs = [{"type": "CHECKSUM_MISMATCH", "script": "V1__a.sql", "new_checksum": 200}]
        result = RepairResult()

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop(repairs, result)

        self.assertTrue(had_error)
        provider.rollback_transaction.assert_called()

    def test_empty_repairs_no_begin_transaction(self):
        provider = MagicMock()
        history_manager = MagicMock()
        history_manager.normalized_history_table = "dblift_schema_history"

        cmd = _make_cmd(provider=provider, history_manager=history_manager)

        with patch("dblift.core.migration.commands.repair_command.ensure_provider_connection"):
            executed, had_error = cmd._execute_repair_loop([], RepairResult())

        self.assertEqual(executed, 0)
        self.assertFalse(had_error)


# ---------------------------------------------------------------------------
# _validate_post_repair_state
# ---------------------------------------------------------------------------


class TestValidatePostRepairState(unittest.TestCase):
    def test_returns_false_when_no_remaining_issues(self):
        state_manager = MagicMock()
        post_state = MigrationState()
        post_state.checksum_changes = []
        state_manager.build_state.return_value = post_state

        cmd = _make_cmd(state_manager=state_manager)
        result = RepairResult()
        had_error = cmd._validate_post_repair_state(
            migration_state=MigrationState(),
            repairs_needed=[{"script": "V1__a.sql", "type": "CHECKSUM_MISMATCH"}],
            scripts_dir=Path("/migrations"),
            recursive=True,
            additional_dirs=None,
            dir_recursive_map=None,
            result=result,
        )
        self.assertFalse(had_error)

    def test_returns_true_when_remaining_issues_found(self):
        state_manager = MagicMock()
        post_state = MigrationState()
        change = SimpleNamespace(script_name="V1__a.sql")
        post_state.checksum_changes = [change]
        state_manager.build_state.return_value = post_state

        cmd = _make_cmd(state_manager=state_manager)
        result = RepairResult()
        had_error = cmd._validate_post_repair_state(
            migration_state=MigrationState(),
            repairs_needed=[{"script": "V1__a.sql", "type": "CHECKSUM_MISMATCH"}],
            scripts_dir=Path("/migrations"),
            recursive=True,
            additional_dirs=None,
            dir_recursive_map=None,
            result=result,
        )
        self.assertTrue(had_error)
        self.assertIsNotNone(result.error_message)

    def test_exception_in_build_state_swallowed(self):
        state_manager = MagicMock()
        state_manager.build_state.side_effect = RuntimeError("rebuild failed")

        cmd = _make_cmd(state_manager=state_manager)
        result = RepairResult()
        # Should not raise
        had_error = cmd._validate_post_repair_state(
            migration_state=MigrationState(),
            repairs_needed=[{"script": "V1__a.sql"}],
            scripts_dir=Path("/migrations"),
            recursive=True,
            additional_dirs=None,
            dir_recursive_map=None,
            result=result,
        )
        self.assertFalse(had_error)


# ---------------------------------------------------------------------------
# _build_repair_summary
# ---------------------------------------------------------------------------


class TestBuildRepairSummary(unittest.TestCase):
    def test_logs_checksums_fixed(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = RepairResult()
        result.checksums_fixed = 3

        cmd._build_repair_summary(result)

        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("3 checksum", info_calls)

    def test_logs_failed_migrations_removed(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = RepairResult()
        result.failed_migrations_removed = 2

        cmd._build_repair_summary(result)

        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("2 failed migration", info_calls)

    def test_logs_deleted_migrations_marked(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = RepairResult()
        result.deleted_migrations_marked = 1

        cmd._build_repair_summary(result)

        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("1 missing migration", info_calls)

    def test_logs_generic_success_when_no_counters(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = RepairResult()

        cmd._build_repair_summary(result)

        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("completed successfully", info_calls)


# ---------------------------------------------------------------------------
# execute() — top-level flow
# ---------------------------------------------------------------------------


class TestRepairCommandExecute(unittest.TestCase):
    def _make_execute_cmd(self):
        """Build cmd with a state_manager that returns empty state."""
        provider = MagicMock()
        provider.begin_transaction.return_value = None
        provider.commit_transaction.return_value = None

        history_manager = MagicMock()
        history_manager.create_schema_and_history_table.return_value = None
        history_manager.normalized_history_table = "dblift_schema_history"

        state_manager = MagicMock()
        state_manager.build_state.return_value = MigrationState()
        state_manager.get_current_version.return_value = None

        script_manager = MagicMock()
        script_manager.load_migration_scripts.return_value = {}

        config = MagicMock()
        config.database.schema = "public"
        config.database.type = "postgresql"

        cmd = _make_cmd(
            provider=provider,
            config=config,
            history_manager=history_manager,
            state_manager=state_manager,
            script_manager=script_manager,
        )
        return cmd

    def test_no_repairs_needed_returns_success(self):
        cmd = self._make_execute_cmd()

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute(Path("/migrations"))

        self.assertTrue(result.success)

    def test_dry_run_logs_repairs_without_executing(self):
        log = MagicMock()
        cmd = self._make_execute_cmd()
        cmd.log = log

        # Force some repairs to be detected
        checksum_change = SimpleNamespace(
            script_name="V1__a.sql",
            previous_checksum=100,
            current_checksum=200,
        )
        state_with_changes = MigrationState()
        state_with_changes.checksum_changes = [checksum_change]
        cmd.state_manager.build_state.return_value = state_with_changes

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute(Path("/migrations"), dry_run=True)

        self.assertTrue(result.success)
        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("DRY RUN", info_calls)

    def test_general_exception_is_caught(self):
        cmd = self._make_execute_cmd()
        cmd.history_manager.create_schema_and_history_table.side_effect = RuntimeError("no DB")

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)
        self.assertIn("Repair operation failed", result.error_message)

    def test_repair_safety_error_caught(self):
        """RepairSafetyError should be caught and returned as error result."""
        cmd = self._make_execute_cmd()

        def _raise_safety(*args, **kwargs):
            raise RepairSafetyError("refusing to mass-mark")

        cmd.script_manager.load_migration_scripts.return_value = {}
        # Give the state some applied migrations so safety gate fires
        applied_state = MigrationState()
        applied_state.applied_objects = [_make_applied("V1__a.sql")]
        cmd.state_manager.build_state.return_value = applied_state

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute(Path("/migrations"))

        self.assertFalse(result.success)

    def test_result_target_schema_set(self):
        cmd = self._make_execute_cmd()

        with patch.object(cmd, "_populate_database_info"):
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute(Path("/migrations"))

        self.assertEqual(result.target_schema, "public")


if __name__ == "__main__":
    unittest.main()
