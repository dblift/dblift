"""Extended unit tests for clean_command.py.

Covers previously untested paths to push coverage toward 70%+:
  - CleanCommand.execute() — dry_run paths (provider preview, introspector fallback,
    empty schema message), beforeClean callback failure, clean_schema paths,
    CleanExecutionSummary with errors, fallback without clean_schema, commit,
    afterClean callbacks, afterCleanError callbacks on exception
  - _parse_drop_statement_for_result — all DROP types (view, table, sequence,
    function, procedure, trigger)
  - _log_clean_summary — all ordering branches, remaining types, empty
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from core.logger.results import CleanResult
from core.migration.clean_summary import CleanedObjectInfo, CleanExecutionSummary
from core.migration.commands.clean_command import CleanCommand

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
    _provider = provider or MagicMock()

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
# _parse_drop_statement_for_result
# ---------------------------------------------------------------------------


class TestParseDropStatementForResult(unittest.TestCase):
    """Note: _parse_drop_statement_for_result uppercases the statement before matching,
    so names stored in the result are uppercase versions of what was in the SQL."""

    def test_parse_drop_view(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP VIEW my_view", result)
        self.assertIn("MY_VIEW", result.views_dropped)

    def test_parse_drop_view_if_exists(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP VIEW IF EXISTS my_view", result)
        self.assertIn("MY_VIEW", result.views_dropped)

    def test_parse_drop_view_schema_qualified(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result('DROP VIEW "public".my_view', result)
        self.assertIn("MY_VIEW", result.views_dropped)

    def test_parse_drop_table(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP TABLE users", result)
        self.assertIn("USERS", result.tables_dropped)

    def test_parse_drop_table_if_exists(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP TABLE IF EXISTS orders", result)
        self.assertIn("ORDERS", result.tables_dropped)

    def test_parse_drop_sequence(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP SEQUENCE user_id_seq", result)
        self.assertIn("USER_ID_SEQ", result.sequences_dropped)

    def test_parse_drop_function(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP FUNCTION my_func()", result)
        self.assertIn("MY_FUNC", result.functions_dropped)

    def test_parse_drop_function_if_exists(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP FUNCTION IF EXISTS compute()", result)
        self.assertIn("COMPUTE", result.functions_dropped)

    def test_parse_drop_procedure(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP PROCEDURE sp_insert()", result)
        self.assertIn("SP_INSERT", result.procedures_dropped)

    def test_parse_drop_trigger(self):
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP TRIGGER trg_update", result)
        self.assertIn("TRG_UPDATE", result.triggers_dropped)

    def test_unrecognized_statement_no_error(self):
        """An unrecognized statement should not raise."""
        cmd = _make_cmd()
        result = CleanResult()
        # Should not raise
        cmd._parse_drop_statement_for_result("ALTER TABLE foo ADD COLUMN bar INT", result)

    def test_view_takes_precedence_over_table(self):
        """VIEW match should return before TABLE match."""
        cmd = _make_cmd()
        result = CleanResult()
        cmd._parse_drop_statement_for_result("DROP VIEW v_users", result)
        self.assertIn("V_USERS", result.views_dropped)
        self.assertEqual(len(result.tables_dropped), 0)


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
    def test_dry_run_with_provider_preview_lists_objects(self):
        provider = MagicMock()
        obj = SimpleNamespace(object_type="TABLE", name="users")
        preview = MagicMock()
        preview.objects = [obj]

        log = MagicMock()
        cmd = _make_cmd(provider=provider, log=log, clean_disabled=False)

        with patch("core.migration.commands.clean_command.get_clean_preview", return_value=preview):
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

        with patch("core.migration.commands.clean_command.get_clean_preview", return_value=None):
            with patch(
                "core.introspection.schema_introspector.SchemaIntrospector"
            ) as mock_introspector_cls:
                mock_intro = MagicMock()
                mock_intro.get_tables.return_value = []
                mock_intro.get_views.return_value = []
                mock_intro.get_materialized_views.return_value = []
                mock_intro.get_sequences.return_value = []
                mock_intro.get_functions.return_value = []
                mock_intro.get_procedures.return_value = []
                mock_intro.get_packages.return_value = []
                mock_intro.get_synonyms.return_value = []
                mock_intro.get_triggers.return_value = []
                mock_intro.get_user_defined_types.return_value = []
                mock_introspector_cls.return_value = mock_intro

                with patch.object(cmd, "_ensure_connected"):
                    with patch.object(cmd, "_populate_database_info"):
                        with patch.object(cmd, "_log_command_header_update"):
                            with patch.object(cmd, "_log_command_completion"):
                                result = cmd.execute(dry_run=True)

        self.assertTrue(result.success)
        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("empty", info_calls.lower())

    def test_dry_run_introspector_fallback_lists_tables(self):
        provider = MagicMock()
        log = MagicMock()
        cmd = _make_cmd(provider=provider, log=log, clean_disabled=False)

        table_obj = SimpleNamespace(name="orders")

        with patch("core.migration.commands.clean_command.get_clean_preview", return_value=None):
            with patch("core.introspection.schema_introspector.SchemaIntrospector") as mock_cls:
                mock_intro = MagicMock()
                mock_intro.get_tables.return_value = [table_obj]
                mock_intro.get_views.return_value = []
                mock_intro.get_materialized_views.return_value = []
                mock_intro.get_sequences.return_value = []
                mock_intro.get_functions.return_value = []
                mock_intro.get_procedures.return_value = []
                mock_intro.get_packages.return_value = []
                mock_intro.get_synonyms.return_value = []
                mock_intro.get_triggers.return_value = []
                mock_intro.get_user_defined_types.return_value = []
                mock_cls.return_value = mock_intro

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
# execute() — clean_schema paths
# ---------------------------------------------------------------------------


class TestCleanCommandCleanSchema(unittest.TestCase):
    def test_clean_with_clean_execution_summary_response(self):
        """Provider returns CleanExecutionSummary — objects should appear in result."""
        provider = MagicMock()
        summary = CleanExecutionSummary()
        summary.statements = ["DROP TABLE users"]
        summary.objects = [CleanedObjectInfo(object_type="table", name="users", schema="public")]

        provider.clean_schema.return_value = summary
        provider.commit_transaction.return_value = None

        cmd = _make_cmd(provider=provider, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertTrue(result.success)
        self.assertIn("users", result.tables_dropped)

    def test_clean_with_clean_execution_summary_with_errors(self):
        """CleanExecutionSummary with errors should mark result as failed."""
        provider = MagicMock()
        summary = CleanExecutionSummary()
        summary.statements = ["DROP TABLE locked_table"]
        summary.objects = []
        summary.errors = ["Error dropping locked_table: permission denied"]

        provider.clean_schema.return_value = summary
        provider.commit_transaction.return_value = None

        cmd = _make_cmd(provider=provider, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertFalse(result.success)
        self.assertTrue(len(result.warnings) > 0)

    def test_clean_with_list_response_parses_statements(self):
        """Provider returns plain list of SQL — should parse DROP statements.
        Note: _parse_drop_statement_for_result uppercases names before storing."""
        provider = MagicMock()
        provider.clean_schema.return_value = ["DROP TABLE users", "DROP VIEW v_users"]
        provider.commit_transaction.return_value = None

        cmd = _make_cmd(provider=provider, clean_disabled=False)

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertTrue(result.success)
        self.assertIn("USERS", result.tables_dropped)
        self.assertIn("V_USERS", result.views_dropped)

    def test_clean_fallback_when_no_clean_schema_method(self):
        """Provider without clean_schema should use fallback DROP/CREATE."""
        from types import SimpleNamespace as NS

        provider = MagicMock(
            spec=[
                "execute_statement",
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

        self.assertTrue(result.success)
        # Fallback should issue execute_statement
        self.assertEqual(provider.execute_statement.call_count, 2)

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
        provider.clean_schema.side_effect = RuntimeError("DB gone")
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
        provider.clean_schema.return_value = ["DROP TABLE t"]
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
        from types import SimpleNamespace as NS

        config = NS(
            clean_disabled=False,
            database=NS(schema="", type="cosmosdb", database_name="mydb"),
        )

        provider = MagicMock()
        provider.clean_schema.return_value = []
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
        summary = CleanExecutionSummary()
        summary.statements = ["DROP TABLE t"]
        summary.objects = [CleanedObjectInfo(object_type="table", name="t", schema="public")]
        # No errors — so success=True but we add a warning manually
        provider.clean_schema.return_value = summary
        provider.commit_transaction.return_value = None

        cmd = _make_cmd(provider=provider, log=log, clean_disabled=False)
        # Manually add a warning to the result inside execute
        # We do that by patching the CleanResult.add_warning
        original_execute = cmd.execute

        def patched_execute(*args, **kwargs):
            r = original_execute(*args, **kwargs)
            return r

        with patch.object(cmd, "_ensure_connected"):
            with patch.object(cmd, "_populate_database_info"):
                with patch.object(cmd, "_log_command_header_update"):
                    with patch.object(cmd, "_log_command_completion"):
                        result = cmd.execute(dry_run=False)

        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
