"""Regression tests for the Batch 8 bug fixes (B8-BUG-01..B8-BUG-05).

Grouped by bug number so an intentional behavioral change to any one fix is
easy to locate. Mirrors the conventions of ``test_batch7_bug_fixes.py``.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# B8-BUG-01: --recursive / --no-recursive must be classified as GLOBAL args
# ---------------------------------------------------------------------------
class TestBug01RecursiveIsGlobal(unittest.TestCase):
    """Both ``--recursive`` and ``--no-recursive`` live on the top-level
    parser's mutually-exclusive group. They must be extracted as global
    arguments, otherwise argparse on the subparser rejects them as
    "unrecognized arguments"."""

    def _extract(self, argv):
        from cli._command_handlers import _AVAILABLE_COMMANDS
        from cli._config_helpers import _extract_commands_from_argv

        global_only_args = [
            "--version",
            "--license-key",
            "--log-dir",
            "--log-format",
            "--log-level",
            "--log-file",
            "--db-url",
            "--db-username",
            "--db-password",
            "--db-schema",
            "--config",
            "--scripts",
            "--dry-run",
            "--recursive",
            "--no-recursive",
        ]
        return _extract_commands_from_argv(argv, _AVAILABLE_COMMANDS, global_only_args)

    def test_recursive_routed_as_global(self) -> None:
        commands, global_args, subcmd_args = self._extract(["--recursive", "migrate"])
        self.assertEqual(commands, ["migrate"])
        self.assertIn("--recursive", global_args)
        self.assertNotIn("--recursive", subcmd_args)

    def test_no_recursive_routed_as_global(self) -> None:
        commands, global_args, subcmd_args = self._extract(["--no-recursive", "info"])
        self.assertEqual(commands, ["info"])
        self.assertIn("--no-recursive", global_args)
        self.assertNotIn("--no-recursive", subcmd_args)

    def test_recursive_does_not_swallow_following_command(self) -> None:
        """--recursive is a boolean flag — it must not consume ``migrate``
        as its value."""
        commands, _, _ = self._extract(["--recursive", "migrate"])
        self.assertEqual(commands, ["migrate"])

    def test_no_recursive_in_global_boolean_flags_set(self) -> None:
        from cli._config_helpers import _GLOBAL_BOOLEAN_FLAGS

        self.assertIn("--recursive", _GLOBAL_BOOLEAN_FLAGS)
        self.assertIn("--no-recursive", _GLOBAL_BOOLEAN_FLAGS)


# ---------------------------------------------------------------------------
# B8-BUG-02: SQLite export-schema must ignore --db-schema and use "main"
# ---------------------------------------------------------------------------
class TestBug02SqliteSchemaOverride(unittest.TestCase):
    """Verify that SchemaExporter._setup_infrastructure() forces target_schema
    to 'main' for SQLite regardless of user input, and still errors on
    schema-required dialects. We stub the executor so _setup_infrastructure
    does not create a real provider."""

    def _make_exporter(self, db_type, cli_schema, config_schema=None):
        from core.migration.commands.export_schema_command import (
            ExportSchemaOptions,
            SchemaExporter,
        )

        config = MagicMock()
        config.database.type = db_type
        config.database.schema = config_schema
        options = ExportSchemaOptions(schema=cli_schema)

        # Pre-populate executor so _setup_infrastructure skips provider creation.
        executor = MagicMock()
        executor.provider = MagicMock()
        executor.history_manager.get_applied_migrations.return_value = []
        executor.snapshot_service = None
        exp = SchemaExporter(config, options, executor=executor, log=MagicMock())
        return exp

    def test_sqlite_forces_main_when_user_passes_non_main(self) -> None:
        exp = self._make_exporter(db_type="sqlite", cli_schema="dblift_test")
        exp._setup_infrastructure()
        self.assertEqual(exp.state.target_schema, "main")
        warn_calls = [str(c) for c in exp.log.warning.call_args_list]
        self.assertTrue(
            any("uses a fixed schema" in c for c in warn_calls),
            f"expected SQLite override warning; got: {warn_calls}",
        )

    def test_sqlite_uses_main_when_no_schema_supplied(self) -> None:
        exp = self._make_exporter(db_type="sqlite", cli_schema=None)
        exp._setup_infrastructure()
        self.assertEqual(exp.state.target_schema, "main")
        warn_calls = [str(c) for c in exp.log.warning.call_args_list]
        self.assertFalse(
            any("uses a fixed schema" in c for c in warn_calls),
            "should not warn when user did not supply a schema",
        )

    def test_sqlite_accepts_main_without_warning(self) -> None:
        exp = self._make_exporter(db_type="sqlite", cli_schema="main")
        exp._setup_infrastructure()
        self.assertEqual(exp.state.target_schema, "main")
        warn_calls = [str(c) for c in exp.log.warning.call_args_list]
        self.assertFalse(
            any("uses a fixed schema" in c for c in warn_calls),
            "should not warn when user supplied the canonical 'main'",
        )

    def test_non_sqlite_dialect_still_requires_schema(self) -> None:
        exp = self._make_exporter(db_type="postgresql", cli_schema=None)
        ok = exp._setup_infrastructure()
        self.assertFalse(ok)
        err_calls = [str(c) for c in exp.log.error.call_args_list]
        self.assertTrue(
            any("Database schema is required" in c for c in err_calls),
            f"expected 'schema required' error; got: {err_calls}",
        )


# ---------------------------------------------------------------------------
# B8-BUG-03: DBLiftClient reuses provider across snapshot / export_schema
# ---------------------------------------------------------------------------
class TestBug03ProviderPassthrough(unittest.TestCase):
    def test_snapshot_impl_reuses_provided_provider(self) -> None:
        """When caller passes ``provider=`` the impl must NOT invoke
        ``ProviderRegistry.create_provider``."""
        from core.migration.commands.snapshot_command import snapshot as snapshot_impl

        provider = MagicMock()
        provider.is_connected.return_value = True
        # ``is_connected`` True means create_connection() isn't called.
        # Stub out SchemaSnapshotService wiring + MigrationExecutor so that
        # ``snapshot`` exits before touching any heavy I/O.
        with (
            patch("core.migration.commands.snapshot_command.ProviderRegistry") as pr_mock,
            patch("core.migration.executor.migration_executor.MigrationExecutor") as me_mock,
        ):
            me_mock.return_value.snapshot_service = None  # force early return
            ok, _ = snapshot_impl(
                config=MagicMock(),
                output="/tmp/snap.json",
                source="live-database",
                log=MagicMock(),
                provider=provider,
            )
        self.assertFalse(ok)  # snapshot_service unavailable → False
        pr_mock.create_provider.assert_not_called()

    def test_snapshot_impl_creates_when_no_provider(self) -> None:
        from core.migration.commands.snapshot_command import snapshot as snapshot_impl

        with (
            patch("core.migration.commands.snapshot_command.ProviderRegistry") as pr_mock,
            patch("core.migration.executor.migration_executor.MigrationExecutor") as me_mock,
        ):
            pr_mock.create_provider.return_value.is_connected.return_value = True
            me_mock.return_value.snapshot_service = None
            snapshot_impl(
                config=MagicMock(),
                output="/tmp/snap.json",
                source="live-database",
                log=MagicMock(),
            )
        pr_mock.create_provider.assert_called_once()

    def test_export_schema_impl_reuses_provided_provider(self) -> None:
        from core.migration.commands.export_schema_command import (
            ExportSchemaOptions,
            SchemaExporter,
        )

        config = MagicMock()
        config.database.type = "postgresql"
        config.database.schema = "public"
        options = ExportSchemaOptions(schema=None)
        provider = MagicMock()
        provider._ensure_connection = MagicMock()

        # Supply an executor so _setup_infrastructure doesn't try to create
        # one from ProviderRegistry itself.
        executor = MagicMock()
        executor.provider = MagicMock()  # irrelevant for this test
        executor.history_manager.get_applied_migrations.return_value = []
        executor.snapshot_service = None
        exp = SchemaExporter(
            config,
            options,
            executor=executor,
            log=MagicMock(),
            provider=provider,
        )
        self.assertIs(exp.state.provider, provider)

        with patch("core.migration.commands.export_schema_command.ProviderRegistry") as pr_mock:
            exp._setup_infrastructure()
        # The critical assertion: we did NOT create a second provider.
        pr_mock.create_provider.assert_not_called()
        self.assertIs(exp.state.provider, provider)

    def test_client_snapshot_forwards_provider(self) -> None:
        from api.client import DBLiftClient

        client = DBLiftClient.__new__(DBLiftClient)
        client.config = MagicMock()
        client.provider = MagicMock()
        client.executor = MagicMock()
        client.logger = MagicMock()
        client.events = MagicMock()

        with patch("core.migration.commands.snapshot_command.snapshot") as snap_mock:
            snap_mock.return_value = (True, None)
            client.snapshot(output="/tmp/x.json", source="live-database")
        kwargs = snap_mock.call_args.kwargs
        self.assertIs(kwargs["provider"], client.provider)

    def test_client_snapshot_populates_error_message_on_failure(self) -> None:
        """SnapshotResult.error_message must carry the failure reason from snapshot_impl."""
        from api.client import DBLiftClient

        client = DBLiftClient.__new__(DBLiftClient)
        client.config = MagicMock()
        client.provider = MagicMock()
        client.executor = MagicMock()
        client.logger = MagicMock()
        client.events = MagicMock()

        with patch("core.migration.commands.snapshot_command.snapshot") as snap_mock:
            snap_mock.return_value = (False, "'str' object has no attribute 'name'")
            result = client.snapshot(output="/tmp/x.json", source="live-database")

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "'str' object has no attribute 'name'")

    def test_client_export_schema_forwards_provider(self) -> None:
        from api.client import DBLiftClient

        client = DBLiftClient.__new__(DBLiftClient)
        client.config = MagicMock()
        client.config.migrations.directory = "/tmp/m"
        client.config.migrations.recursive = True
        client.provider = MagicMock()
        client.executor = MagicMock()
        client.logger = MagicMock()
        client.events = MagicMock()

        with (
            patch("core.migration.commands.export_schema_command.export_schema") as es_mock,
            patch.object(client, "_guard_scripts_dir_kwarg"),
        ):
            es_mock.return_value = True
            client.export_schema(output="/tmp/out.sql")
        kwargs = es_mock.call_args.kwargs
        self.assertIs(kwargs["provider"], client.provider)


# ---------------------------------------------------------------------------
# B8-BUG-04: error_with_exception must strip FQCNs beyond com.*
# ---------------------------------------------------------------------------
class TestBug04JavaFqcnStrip(unittest.TestCase):
    def _capture(self, exc):
        from core.logger.log import AbstractLog

        captured = []

        class _Probe(AbstractLog):
            def _write_log_event(self, event, console_only=False):
                captured.append((event.level, event.message))

        log = _Probe("test")
        log.error_with_exception("Boom", exc)
        return captured

    def test_postgres_fqcn_stripped(self) -> None:
        captured = self._capture(
            Exception("org.postgresql.util.PSQLException: FATAL: password authentication failed")
        )
        msg = "\n".join(m for _, m in captured)
        self.assertNotIn("org.postgresql.util.PSQLException", msg)
        self.assertIn("FATAL: password authentication failed", msg)

    def test_java_sql_fqcn_stripped(self) -> None:
        captured = self._capture(Exception("java.sql.SQLException: timeout waiting for connection"))
        msg = "\n".join(m for _, m in captured)
        self.assertNotIn("java.sql.SQLException", msg)
        self.assertIn("timeout waiting for connection", msg)

    def test_oracle_fqcn_stripped(self) -> None:
        captured = self._capture(
            Exception("oracle.jdbc.OracleDatabaseException: ORA-12541: TNS:no listener")
        )
        msg = "\n".join(m for _, m in captured)
        self.assertNotIn("oracle.jdbc.OracleDatabaseException", msg)
        self.assertIn("ORA-12541", msg)

    def test_plain_python_exception_unchanged(self) -> None:
        captured = self._capture(ValueError("plain old python error"))
        msg = "\n".join(m for _, m in captured)
        self.assertIn("plain old python error", msg)


# ---------------------------------------------------------------------------
# B8-BUG-05: --min-confidence gating
# ---------------------------------------------------------------------------
class TestBug05MinConfidenceGating(unittest.TestCase):
    def _call_snapshot(self, min_confidence, overall_score):
        from core.migration.commands.snapshot_command import snapshot as snapshot_impl

        provider = MagicMock()
        provider.is_connected.return_value = True
        payload = MagicMock()
        payload.metadata = {
            "validation": {
                "confidence": {
                    "overall_score": overall_score,
                    "confidence_level": "MEDIUM",
                }
            }
        }
        payload.to_dict.return_value = {}

        snapshot_service = MagicMock()
        snapshot_service.build_live_payload.return_value = payload

        log = MagicMock()

        with (
            patch("core.migration.commands.snapshot_command.ProviderRegistry"),
            patch("core.migration.executor.migration_executor.MigrationExecutor") as me_mock,
        ):
            me_mock.return_value.snapshot_service = snapshot_service
            ok, _err = snapshot_impl(
                config=MagicMock(),
                output=str(Path("/tmp/mc-snap.json")),
                source="live-database",
                log=log,
                provider=provider,
                min_confidence=min_confidence,
            )
        return ok, log

    def test_below_threshold_fails(self) -> None:
        ok, log = self._call_snapshot(min_confidence=0.8, overall_score=0.4)
        self.assertFalse(ok)
        err_calls = [str(c) for c in log.error.call_args_list]
        joined = "\n".join(err_calls)
        self.assertIn("below the required minimum", joined)
        self.assertIn("40.0%", joined)
        self.assertIn("80.0%", joined)

    def test_above_threshold_succeeds(self) -> None:
        ok, _log = self._call_snapshot(min_confidence=0.4, overall_score=0.9)
        self.assertTrue(ok)

    def test_exactly_at_threshold_succeeds(self) -> None:
        ok, _log = self._call_snapshot(min_confidence=0.75, overall_score=0.75)
        self.assertTrue(ok)

    def test_invalid_min_confidence_fails(self) -> None:
        ok, log = self._call_snapshot(min_confidence=1.5, overall_score=0.9)
        self.assertFalse(ok)
        err_calls = [str(c) for c in log.error.call_args_list]
        self.assertTrue(any("[0.0, 1.0]" in c for c in err_calls))

    def test_no_min_confidence_skips_gating(self) -> None:
        """No flag → any confidence is accepted (pre-fix behaviour)."""
        ok, _log = self._call_snapshot(min_confidence=None, overall_score=0.01)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
