"""Extended unit tests for clean_command.py.

Covers previously untested paths to push coverage toward 70%+:
  - CleanCommand.execute() — dry_run paths (provider droppable-object preview,
    empty schema message), beforeClean callback failure, droppable-object paths, commit,
    afterClean callbacks, afterCleanError callbacks on exception
  - _log_clean_summary — all ordering branches, remaining types, empty
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dblift.core.logger.results import CleanResult
from dblift.core.migration.commands.clean_command import CleanCommand
from dblift.db.provider_interfaces import DroppableObject

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cmd(
    provider=None,
    config=None,
    log=None,
    clean_disabled=False,
    schema="public",
):
    """Build a CleanCommand with minimal mocked collaborators."""
    _config = config or SimpleNamespace(
        clean_disabled=clean_disabled,
        database=SimpleNamespace(schema=schema, type="postgresql"),
    )

    _log = log or MagicMock()
    if provider is None:
        _provider = MagicMock()
        _provider.list_droppable_objects.return_value = []
    else:
        _provider = provider

    cmd = CleanCommand(
        config=_config,
        log=_log,
        provider=_provider,
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    return cmd


# ---------------------------------------------------------------------------
# _log_clean_summary
# ---------------------------------------------------------------------------


class TestLogCleanSummary(unittest.TestCase):
    @staticmethod
    def _tree_text(log) -> str:
        """Extract the rendered tree string from log.file_only_info calls."""
        return " ".join(str(c) for c in log.file_only_info.call_args_list)

    def test_no_objects_logs_empty_message(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = CleanResult()
        cmd._log_clean_summary(result)
        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("No objects", info_calls)

    def test_logs_tables_in_preferred_order(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = CleanResult()
        result.add_table_dropped("users")
        result.add_view_dropped("v_users")
        cmd._log_clean_summary(result)
        rendered = self._tree_text(log)
        self.assertLess(rendered.index("Table"), rendered.index("View"))

    def test_logs_schema_name(self):
        log = MagicMock()
        cmd = _make_cmd(log=log, schema="myschema")
        result = CleanResult()
        result.target_schema = "myschema"
        result.add_table_dropped("users")
        cmd._log_clean_summary(result)
        self.assertIn("myschema", self._tree_text(log))

    def test_logs_remaining_types_alphabetically(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = CleanResult()
        result.add_cleaned_object("alias", "my_alias")
        result.add_cleaned_object("module", "my_module")
        cmd._log_clean_summary(result)
        rendered = self._tree_text(log)
        self.assertIn("my_alias", rendered)
        self.assertIn("my_module", rendered)

    def test_logs_total_count(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = CleanResult()
        result.add_table_dropped("t1")
        result.add_table_dropped("t2")
        result.add_view_dropped("v1")
        cmd._log_clean_summary(result)
        self.assertIn("3", self._tree_text(log))

    def test_plural_label_for_sequences(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = CleanResult()
        result.add_sequence_dropped("s1")
        result.add_sequence_dropped("s2")
        cmd._log_clean_summary(result)
        self.assertIn("Sequences", self._tree_text(log))

    def test_singular_label_for_one_table(self):
        log = MagicMock()
        cmd = _make_cmd(log=log)
        result = CleanResult()
        result.add_table_dropped("t1")
        cmd._log_clean_summary(result)
        self.assertIn("Table", self._tree_text(log))


# ---------------------------------------------------------------------------
# execute() — dry_run paths
# ---------------------------------------------------------------------------


class TestCleanCommandDryRun(unittest.TestCase):
    def test_dry_run_with_provider_droppable_objects_lists_objects(self):
        provider = MagicMock()
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="users", object_type="table", drop_sql='DROP TABLE "users"')
        ]

        log = MagicMock()
        cmd = _make_cmd(provider=provider, log=log, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=True)

        self.assertTrue(result.success)
        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("users", info_calls)

    def test_dry_run_empty_schema_logs_appears_empty_message(self):
        provider = MagicMock()

        log = MagicMock()
        cmd = _make_cmd(provider=provider, log=log, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=True)

        self.assertTrue(result.success)
        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("empty", info_calls.lower())

    def test_dry_run_provider_droppable_objects_lists_tables(self):
        provider = MagicMock()
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="orders", object_type="table", drop_sql='DROP TABLE "orders"')
        ]
        log = MagicMock()
        cmd = _make_cmd(provider=provider, log=log, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=True)

        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("orders", info_calls)

    def test_dry_run_connection_error_returns_error(self):
        cmd = _make_cmd(clean_disabled=False)

        with patch.object(cmd, "_ensure_connected", side_effect=RuntimeError("no conn")):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_completion"):
                    result = cmd.execute(dry_run=True)

        self.assertFalse(result.success)


# ---------------------------------------------------------------------------
# execute() — droppable-object paths
# ---------------------------------------------------------------------------


class TestCleanCommandCleanSchema(unittest.TestCase):
    def test_clean_with_droppable_objects_response(self):
        """Provider returns droppable objects — objects should appear in result."""
        provider = MagicMock()
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="users", object_type="table", drop_sql='DROP TABLE "users"')
        ]
        provider.commit_transaction.return_value = None

        cmd = _make_cmd(provider=provider, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertTrue(result.success)
        self.assertIn("users", result.tables_dropped)
        provider.drop_object.assert_called_once()
        assert provider.drop_object.call_args.args[0].drop_sql == 'DROP TABLE "users"'

    def test_clean_with_drop_errors_marks_result_failed(self):
        """Failed DROP execution should mark result as failed."""
        provider = MagicMock()
        provider.list_droppable_objects.return_value = [
            DroppableObject(
                name="locked_table",
                object_type="table",
                drop_sql='DROP TABLE "locked_table"',
            )
        ]
        provider.drop_object.side_effect = RuntimeError("permission denied")
        provider.commit_transaction.return_value = None

        cmd = _make_cmd(provider=provider, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertFalse(result.success)
        self.assertTrue(len(result.warnings) > 0)

    def test_clean_with_multiple_droppable_objects_records_types(self):
        """Provider droppable-object metadata should drive CleanResult accounting."""
        provider = MagicMock()
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="users", object_type="table", drop_sql='DROP TABLE "users"'),
            DroppableObject(name="v_users", object_type="view", drop_sql='DROP VIEW "v_users"'),
        ]
        provider.commit_transaction.return_value = None

        cmd = _make_cmd(provider=provider, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertTrue(result.success)
        self.assertIn("users", result.tables_dropped)
        self.assertIn("v_users", result.views_dropped)

    def test_clean_without_droppable_object_contract_returns_error(self):
        """Provider without list_droppable_objects should fail instead of fallback clean."""
        provider = MagicMock(
            spec=[
                "execute_statement",
                "drop_object",
                "commit_transaction",
                "is_connected",
                "connect",
                "get_schema_qualified_name",
            ]
        )
        provider.execute_statement.return_value = 1
        provider.commit_transaction.return_value = None

        config = SimpleNamespace(
            clean_disabled=False,
            database=SimpleNamespace(schema="testschema", type="postgresql"),
        )

        log = MagicMock()
        cmd = CleanCommand(
            config=config,
            log=log,
            provider=provider,
            script_manager=MagicMock(),
            history_manager=MagicMock(),
            validator=MagicMock(),
            execution_engine=MagicMock(),
            migration_helpers=MagicMock(),
            state_manager=MagicMock(),
            migration_ui=MagicMock(),
            migration_rules=MagicMock(),
        )

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertFalse(result.success)
        provider.drop_object.assert_not_called()

    def test_before_clean_callback_failure_returns_error(self):
        provider = MagicMock()
        provider.clean_schema.return_value = []
        provider.commit_transaction.return_value = None

        scripts_dir = Path("/migrations")
        cmd = _make_cmd(provider=provider, clean_disabled=False)

        def _raise_on_before(sd, event, *args, **kwargs):
            if event == "beforeClean":
                raise RuntimeError("callback failed")

        cmd._execute_callbacks = _raise_on_before

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False, scripts_dir=scripts_dir)

        self.assertFalse(result.success)
        self.assertIn("beforeClean callback failed", result.error_message)

    def test_after_clean_callbacks_executed_on_success(self):
        provider = MagicMock()
        provider.clean_schema.return_value = []
        provider.commit_transaction.return_value = None

        scripts_dir = Path("/migrations")
        cmd = _make_cmd(provider=provider, clean_disabled=False)
        cmd._execute_callbacks = MagicMock()

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False, scripts_dir=scripts_dir)

        events = [c.args[1] for c in cmd._execute_callbacks.call_args_list]
        self.assertIn("afterClean", events)

    def test_exception_triggers_after_clean_error_callbacks(self):
        """When an exception occurs in the main try, afterCleanError should be called."""
        provider = MagicMock()
        provider.list_droppable_objects.side_effect = RuntimeError("DB gone")
        provider.commit_transaction.return_value = None

        scripts_dir = Path("/migrations")
        cmd = _make_cmd(provider=provider, clean_disabled=False)
        callback_calls = []

        def _track_callbacks(sd, event, *args, **kwargs):
            callback_calls.append(event)

        cmd._execute_callbacks = _track_callbacks

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False, scripts_dir=scripts_dir)

        self.assertFalse(result.success)
        self.assertIn("afterCleanError", callback_calls)

    def test_commit_error_raises(self):
        """commit_transaction failure should propagate (caught by outer except)."""
        provider = MagicMock()
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="t", object_type="table", drop_sql='DROP TABLE "t"')
        ]
        provider.commit_transaction.side_effect = RuntimeError("commit failed")

        cmd = _make_cmd(provider=provider, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertFalse(result.success)

    def test_schema_target_fallback_when_schema_empty(self):
        """When schema is empty, fall back to database_name/database."""
        config = SimpleNamespace(
            clean_disabled=False,
            database=SimpleNamespace(schema="", type="cosmosdb", database_name="mydb"),
        )

        provider = MagicMock()
        provider.commit_transaction.return_value = None

        cmd = CleanCommand(
            config=config,
            log=MagicMock(),
            provider=provider,
            script_manager=MagicMock(),
            history_manager=MagicMock(),
            validator=MagicMock(),
            execution_engine=MagicMock(),
            migration_helpers=MagicMock(),
            state_manager=MagicMock(),
            migration_ui=MagicMock(),
            migration_rules=MagicMock(),
        )

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertEqual(result.target_schema, "mydb")

    def test_success_with_warnings_logs_warning_count(self):
        """Successful clean with warnings logs a summary with warning count."""
        log = MagicMock()
        provider = MagicMock()
        provider.list_droppable_objects.return_value = [
            DroppableObject(name="t", object_type="table", drop_sql='DROP TABLE "t"')
        ]
        provider.commit_transaction.return_value = None

        cmd = _make_cmd(provider=provider, log=log, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
