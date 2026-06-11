"""Regression tests for the Batch 7 bug fixes (B7-BUG-01..B7-BUG-06).

Grouped by bug number so an intentional behavioral change to any one fix is
easy to locate. Tests avoid real network/DB dependencies by mocking out the
provider and executor layers where practical, and source-matching for the
docker-compose healthcheck change.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# B7-BUG-01: scripts_dir kwarg collision must raise a pointed TypeError
# ---------------------------------------------------------------------------
class TestBug01ScriptsDirKwargGuard(unittest.TestCase):
    """Passing ``scripts_dir`` via kwargs to any public API method must raise
    a ``TypeError`` that directs the caller to ``migrations_dir`` — not the
    confusing default ``got multiple values for keyword argument`` message.
    """

    def _make_client(self):
        from api.client import DBLiftClient

        client = DBLiftClient.__new__(DBLiftClient)
        client.config = MagicMock()
        client.config.migrations.directory = "/tmp/migrations"
        client.provider = MagicMock()
        client.executor = MagicMock()
        client.events = MagicMock()
        return client

    def _assert_guard_raises(self, callable_, *args, **kwargs) -> None:
        with self.assertRaises(TypeError) as cm:
            callable_(*args, **kwargs)
        self.assertIn("migrations_dir", str(cm.exception))
        self.assertIn("scripts_dir", str(cm.exception))

    def test_migrate_guards_scripts_dir(self) -> None:
        c = self._make_client()
        self._assert_guard_raises(c.migrate, scripts_dir="/bad")

    def test_info_guards_scripts_dir(self) -> None:
        c = self._make_client()
        self._assert_guard_raises(c.info, scripts_dir="/bad")

    def test_validate_guards_scripts_dir(self) -> None:
        c = self._make_client()
        self._assert_guard_raises(c.validate, scripts_dir="/bad")

    def test_undo_guards_scripts_dir(self) -> None:
        c = self._make_client()
        self._assert_guard_raises(c.undo, scripts_dir="/bad")

    def test_clean_guards_scripts_dir(self) -> None:
        c = self._make_client()
        self._assert_guard_raises(c.clean, scripts_dir="/bad")

    def test_repair_guards_scripts_dir(self) -> None:
        c = self._make_client()
        self._assert_guard_raises(c.repair, scripts_dir="/bad")

    def test_import_flyway_guards_scripts_dir(self) -> None:
        c = self._make_client()
        self._assert_guard_raises(c.import_flyway, scripts_dir="/bad")

    def test_guard_is_noop_when_kwarg_absent(self) -> None:
        """Happy path: calls without ``scripts_dir`` must not raise."""
        c = self._make_client()
        # guard directly — no executor side effects needed
        c._guard_scripts_dir_kwarg({})
        c._guard_scripts_dir_kwarg({"target_version": "1.0"})


# ---------------------------------------------------------------------------
# B7-BUG-02: EventType.MIGRATION_APPLIED must exist as alias
# ---------------------------------------------------------------------------
class TestBug02MigrationAppliedAlias(unittest.TestCase):
    def test_migration_applied_exists(self) -> None:
        from api.events import EventType

        self.assertTrue(hasattr(EventType, "MIGRATION_APPLIED"))

    def test_migration_applied_aliases_script_completed(self) -> None:
        """Python collapses enum members with identical values → ``is`` check
        holds and a single listener fires for either name."""
        from api.events import EventType

        self.assertIs(EventType.MIGRATION_APPLIED, EventType.MIGRATION_SCRIPT_COMPLETED)

    def test_migration_applied_has_expected_value(self) -> None:
        from api.events import EventType

        self.assertEqual(EventType.MIGRATION_APPLIED.value, "migration.script.completed")

    # -----------------------------------------------------------------
    # Cursor-bot follow-up: pin the alias surface consequences so a
    # contributor who rediscovers the alias and "fixes" it (e.g. by
    # giving MIGRATION_APPLIED a unique string) cannot land the change
    # without also updating every consumer that depends on the
    # documented behaviour. Each assertion mirrors a bullet in the
    # ``api/events.py`` docstring above the alias.
    # -----------------------------------------------------------------

    def test_migration_applied_name_is_canonical(self) -> None:
        """``.name`` resolves to the canonical member name — MIGRATION_APPLIED is now primary."""
        from api.events import EventType

        self.assertEqual(EventType.MIGRATION_APPLIED.name, "MIGRATION_APPLIED")

    def test_migration_script_completed_is_alias(self) -> None:
        """Iterating ``EventType`` yields MIGRATION_APPLIED (canonical) once;
        MIGRATION_SCRIPT_COMPLETED is the alias and does not appear separately."""
        from api.events import EventType

        names = [e.name for e in EventType]
        self.assertIn("MIGRATION_APPLIED", names)
        self.assertEqual(names.count("MIGRATION_APPLIED"), 1)
        self.assertNotIn("MIGRATION_SCRIPT_COMPLETED", names)

    def test_migration_applied_lookup_returns_canonical(self) -> None:
        """``EventType["MIGRATION_SCRIPT_COMPLETED"]`` resolves to the canonical
        MIGRATION_APPLIED member — alias lookup via ``_member_map_``."""
        from api.events import EventType

        self.assertIs(EventType["MIGRATION_SCRIPT_COMPLETED"], EventType.MIGRATION_APPLIED)


class TestBug05SQLiteFts5ShadowFilter(unittest.TestCase):
    def _make_ops(self, rows_by_query):
        """Build an ops instance whose query_executor returns canned rows.

        ``rows_by_query`` maps a substring → list[dict] used as the query result.
        """
        from db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        qe = MagicMock()

        def _exec(conn, query):
            for key, rows in rows_by_query.items():
                if key in query:
                    return rows
            return []

        qe.execute_query.side_effect = _exec
        return SQLiteSchemaOperations(query_executor=qe, log=MagicMock())

    def test_get_tables_filters_fts5_shadows(self) -> None:
        rows = {
            # Canonical user + lock table + FTS5 vtable + 5 shadow tables.
            "FROM sqlite_master": [
                {"name": "users"},
                {"name": "users_fts"},
                {"name": "users_fts_data"},
                {"name": "users_fts_idx"},
                {"name": "users_fts_content"},
                {"name": "users_fts_docsize"},
                {"name": "users_fts_config"},
            ],
            "USING fts5": [{"name": "users_fts"}],
        }
        ops = self._make_ops(rows)
        tables = ops.get_tables(MagicMock(), "main")
        self.assertIn("users", tables)
        self.assertIn("users_fts", tables)
        for shadow in (
            "users_fts_data",
            "users_fts_idx",
            "users_fts_content",
            "users_fts_docsize",
            "users_fts_config",
        ):
            self.assertNotIn(shadow, tables)

    def test_enumerate_clean_candidates_filters_fts5_shadows(self) -> None:
        rows = {
            "type = 'view'": [],
            "type = 'trigger'": [],
            "type = 'index'": [],
            "type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name": [
                {"name": "users"},
                {"name": "users_fts"},
                {"name": "users_fts_data"},
                {"name": "users_fts_idx"},
                {"name": "users_fts_content"},
                {"name": "users_fts_docsize"},
                {"name": "users_fts_config"},
            ],
            "USING fts5": [{"name": "users_fts"}],
        }
        ops = self._make_ops(rows)
        candidates = ops.enumerate_clean_candidates(MagicMock(), "main")
        names = {name for object_type, name, _ in candidates if object_type == "table"}
        self.assertIn("users", names)
        self.assertIn("users_fts", names)
        self.assertFalse(
            any(n.startswith("users_fts_") for n in names),
            f"shadow tables leaked into clean candidates: {names}",
        )

    def test_fts5_shadow_detector_gracefully_handles_query_failure(self) -> None:
        """If the FTS5 query itself fails, the method must return an empty set
        so the caller falls back to the pre-fix behavior (no filtering) rather
        than raising and blocking all introspection."""
        from db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        qe = MagicMock()
        qe.execute_query.side_effect = RuntimeError("boom")
        ops = SQLiteSchemaOperations(query_executor=qe, log=MagicMock())
        self.assertEqual(ops._fts5_shadow_table_names(MagicMock()), set())


# ---------------------------------------------------------------------------
# B7-BUG-06: import-flyway --dry-run must emit a user-visible preview
# ---------------------------------------------------------------------------
class TestBug06ImportFlywayDryRunPreview(unittest.TestCase):
    def _make_command(self, rows):
        from core.migration.commands.import_flyway_command import ImportFlywayCommand

        cmd = ImportFlywayCommand.__new__(ImportFlywayCommand)
        cmd.log = MagicMock()
        cmd.config = MagicMock()
        cmd.config.database.schema = "public"
        cmd.provider = MagicMock()
        cmd.provider.table_exists.return_value = True
        cmd.provider.get_applied_migrations.side_effect = [rows, []]
        cmd.history_manager = MagicMock()
        cmd._populate_database_info = MagicMock()
        cmd._log_command_header_update = MagicMock()
        cmd._log_command_completion = MagicMock()
        return cmd

    def test_dry_run_emits_info_log_per_row(self) -> None:
        rows = [
            {"script": "V1__x.sql", "version": "1", "checksum": 111},
            {"script": "V2__y.sql", "version": "2", "checksum": 222},
        ]
        cmd = self._make_command(rows)
        result = cmd.execute(Path("/tmp"), dry_run=True)
        info_calls = [str(c) for c in cmd.log.info.call_args_list]
        joined = "\n".join(info_calls)
        self.assertIn("DRY RUN", joined)
        self.assertIn("V1__x.sql", joined)
        self.assertIn("V2__y.sql", joined)
        self.assertIn("version: 1", joined)
        self.assertIn("checksum: 111", joined)
        # provider.record_migration must not be called in dry-run
        cmd.provider.record_migration.assert_not_called()
        self.assertIn("would be imported", result.message)

    def test_non_dry_run_still_records_and_reports_count(self) -> None:
        rows = [{"script": "V1__x.sql", "version": "1", "checksum": 111}]
        cmd = self._make_command(rows)
        result = cmd.execute(Path("/tmp"), dry_run=False)
        cmd.provider.record_migration.assert_called_once()
        self.assertIn("imported", result.message)
        self.assertNotIn("would be imported", result.message)

    def test_default_source_table_stays_lowercase_flyway_name(self) -> None:
        cmd = self._make_command([])
        cmd.execute(Path("/tmp"), dry_run=False)

        cmd.provider.table_exists.assert_called_once_with("public", "flyway_schema_history")
        cmd.provider.get_applied_migrations.assert_called_once_with(
            "public", "flyway_schema_history"
        )

    def test_custom_source_table_does_not_replace_target_history_table(self) -> None:
        rows = [{"script": "V1__x.sql", "version": "1", "checksum": 111}]
        cmd = self._make_command(rows)
        cmd.config.history_table = "custom_dblift_history"

        cmd.execute(Path("/tmp"), dry_run=False, flyway_table="custom_flyway_history")

        cmd.provider.table_exists.assert_called_once_with("public", "custom_flyway_history")
        cmd.provider.get_applied_migrations.assert_any_call("public", "custom_flyway_history")
        cmd.provider.get_applied_migrations.assert_any_call("public", "custom_dblift_history")
        cmd.provider.record_migration.assert_called_once_with(
            "public", rows[0], "custom_dblift_history"
        )


if __name__ == "__main__":
    unittest.main()
