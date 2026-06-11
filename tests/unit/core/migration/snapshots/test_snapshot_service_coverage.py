"""Coverage-targeted tests for core/migration/snapshots/schema_snapshot_service.py.

Focuses on lines not covered by existing tests:
- SnapshotConnectionContext.__init__ / __enter__ / __exit__ (lines 29-70)
- SchemaSnapshotService.capture_snapshot / build_live_payload (lines 105-120)
- save_payload with migration metadata (lines 129-153)
- load_snapshot_payload_from_path non-JSON branch (lines 157-168)
- validate_snapshot_quality with quality_metrics (lines 179-260)
- _build_payload (lines 264-446)
- _collect_migration_metadata (lines 449-490)
- _validate_snapshot_accuracy (lines 515-615)
- _filter_* methods (lines 617-733)
- _ensure_clean_connection_state / _ensure_valid_connection (lines 846-920)
- _try_bulk_indexes (lines 781-808)
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, call, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(dialect="postgresql", schema="public"):
    config = MagicMock()
    config.database.type = dialect
    config.database.schema = schema
    config.max_snapshots = 1
    config.snapshot_table = None
    return config


def _make_service(dialect="postgresql", schema="public"):
    from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

    config = _make_config(dialect, schema)
    provider = MagicMock()
    provider.MIGRATION_LOCK_TABLE = "dblift_lock"
    history_manager = MagicMock()
    history_manager.history_table = "dblift_schema_history"
    log = MagicMock()
    with patch("core.migration.snapshots.schema_snapshot_service.SchemaSnapshotRepository"):
        svc = SchemaSnapshotService(
            config=config,
            provider=provider,
            history_manager=history_manager,
            log=log,
        )
    svc.repository = MagicMock()
    return svc, config, provider


# ---------------------------------------------------------------------------
# SnapshotConnectionContext
# ---------------------------------------------------------------------------


class TestSnapshotConnectionContextInit(unittest.TestCase):
    def test_init_with_log(self):
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        log = MagicMock()
        ctx = SnapshotConnectionContext(provider, log)
        self.assertIs(ctx.provider, provider)
        self.assertIs(ctx.log, log)
        self.assertIsNone(ctx.original_connection)
        self.assertIsNone(ctx.snapshot_connection)

    def test_init_without_log_uses_nulllog(self):
        from core.logger import NullLog
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        ctx = SnapshotConnectionContext(provider)
        self.assertIsInstance(ctx.log, NullLog)

    def test_enter_stores_original_connection_from_provider(self):
        """Lines 38-39: provider has 'connection' attribute."""
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        fake_conn = MagicMock()
        provider = MagicMock(spec=["connection", "is_connected", "create_connection"])
        provider.connection = fake_conn
        provider.is_connected.return_value = True

        ctx = SnapshotConnectionContext(provider)
        with ctx as c:
            self.assertIs(c.original_connection, fake_conn)

    def test_enter_stores_connection_from_query_executor_when_no_provider_connection(self):
        """Lines 40-43: provider has query_executor with connection, but no direct connection."""
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        fake_conn = MagicMock()
        query_executor = MagicMock(spec=["connection"])
        query_executor.connection = fake_conn

        # provider spec does NOT include 'connection' so hasattr returns False
        provider = SimpleNamespace(
            query_executor=query_executor,
            is_connected=lambda: True,
        )

        ctx = SnapshotConnectionContext(provider)
        with ctx as c:
            self.assertIs(c.original_connection, fake_conn)

    def test_enter_calls_create_connection_when_not_connected(self):
        """Lines 46-47: is_connected() returns False → create_connection called."""
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        provider.is_connected.return_value = False
        ctx = SnapshotConnectionContext(provider)
        with ctx:
            provider.create_connection.assert_called_once()

    def test_enter_stores_snapshot_connection_from_provider(self):
        """Lines 50-51: snapshot_connection stored from provider.connection."""
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        fake_conn = MagicMock()
        provider = MagicMock(spec=["connection", "is_connected", "create_connection"])
        provider.connection = fake_conn
        provider.is_connected.return_value = True

        ctx = SnapshotConnectionContext(provider)
        with ctx as c:
            self.assertIs(c.snapshot_connection, fake_conn)

    def test_enter_stores_snapshot_connection_from_query_executor(self):
        """Lines 52-55: snapshot_connection stored from query_executor.connection."""
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        fake_conn = MagicMock()
        query_executor = MagicMock(spec=["connection"])
        query_executor.connection = fake_conn

        provider = SimpleNamespace(
            query_executor=query_executor,
            is_connected=lambda: True,
        )

        ctx = SnapshotConnectionContext(provider)
        with ctx as c:
            self.assertIs(c.snapshot_connection, fake_conn)

    def test_enter_logs_debug_on_success(self):
        """Line 57: debug log on successful entry."""
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        provider.is_connected.return_value = True
        log = MagicMock()
        ctx = SnapshotConnectionContext(provider, log)
        with ctx:
            pass
        log.debug.assert_called()

    def test_enter_logs_debug_on_exception(self):
        """Lines 59-60: exception in __enter__ is caught and logged."""
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        provider.is_connected.side_effect = RuntimeError("boom")
        log = MagicMock()
        ctx = SnapshotConnectionContext(provider, log)
        with ctx:  # must not raise
            pass
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("boom" in c or "Could not" in c for c in debug_calls)

    def test_exit_logs_completion(self):
        """Line 68: __exit__ logs completion."""
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        provider.is_connected.return_value = True
        log = MagicMock()
        ctx = SnapshotConnectionContext(provider, log)
        with ctx:
            pass
        debug_msgs = [str(c) for c in log.debug.call_args_list]
        assert any("completed" in m or "connection" in m.lower() for m in debug_msgs)

    def test_exit_handles_exception_in_cleanup(self):
        """Lines 69-70: exception in __exit__ is caught only for the inner try block.

        The __exit__ method has a try/except, but if log.debug itself raises,
        it propagates. We verify __exit__ runs without raising when log works normally
        but _something else_ in cleanup fails. Here we just test normal exit flow.
        """
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        provider.is_connected.return_value = True
        log = MagicMock()
        ctx = SnapshotConnectionContext(provider, log)
        ctx.__enter__()
        # Normal exit: must not raise
        ctx.__exit__(None, None, None)
        # Verify debug was called in __exit__
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("completed" in c or "connection" in c.lower() for c in debug_calls)


# ---------------------------------------------------------------------------
# SchemaSnapshotService.__init__
# ---------------------------------------------------------------------------


class TestSchemaSnapshotServiceInitCoverage(unittest.TestCase):
    def test_init_with_string_schema(self):
        """Lines 88-95: schema is a string."""
        from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

        config = _make_config(schema="myschema")
        provider = MagicMock()
        hm = MagicMock()
        with patch(
            "core.migration.snapshots.schema_snapshot_service.SchemaSnapshotRepository"
        ) as MockRepo:
            svc = SchemaSnapshotService(config=config, provider=provider, history_manager=hm)
            MockRepo.assert_called_once_with(
                provider=provider,
                schema="myschema",
                table_name=None,
                logger=svc._logger,
            )

    def test_init_with_none_schema(self):
        """Lines 88-89: schema is None → empty string passed."""
        from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

        config = _make_config()
        config.database.schema = None
        provider = MagicMock()
        hm = MagicMock()
        with patch(
            "core.migration.snapshots.schema_snapshot_service.SchemaSnapshotRepository"
        ) as MockRepo:
            svc = SchemaSnapshotService(config=config, provider=provider, history_manager=hm)
            call_kwargs = MockRepo.call_args[1]
            self.assertEqual(call_kwargs["schema"], "")

    def test_init_with_snapshot_table(self):
        """Line 93: snapshot_table is passed through."""
        from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

        config = _make_config()
        config.snapshot_table = "my_snapshot_table"
        provider = MagicMock()
        hm = MagicMock()
        with patch(
            "core.migration.snapshots.schema_snapshot_service.SchemaSnapshotRepository"
        ) as MockRepo:
            SchemaSnapshotService(config=config, provider=provider, history_manager=hm)
            call_kwargs = MockRepo.call_args[1]
            self.assertEqual(call_kwargs["table_name"], "my_snapshot_table")


# ---------------------------------------------------------------------------
# capture_snapshot
# ---------------------------------------------------------------------------


class TestCaptureSnapshot(unittest.TestCase):
    def test_capture_snapshot_calls_build_and_save(self):
        """Lines 105-110: full capture flow."""
        svc, config, provider = _make_service()
        mock_payload = MagicMock()
        mock_snapshot = MagicMock()
        svc._ensure_clean_connection_state = MagicMock()
        svc._build_payload = MagicMock(return_value=mock_payload)
        svc.save_payload = MagicMock(return_value=mock_snapshot)

        result = svc.capture_snapshot(reason="test", extra_metadata={"k": "v"})

        svc._ensure_clean_connection_state.assert_called_once()
        svc._build_payload.assert_called_once()
        svc.save_payload.assert_called_once_with(
            mock_payload, reason="test", extra_metadata={"k": "v"}
        )
        self.assertIs(result, mock_snapshot)

    def test_capture_snapshot_no_args(self):
        """Minimal call with no arguments."""
        svc, config, provider = _make_service()
        mock_payload = MagicMock()
        mock_snapshot = MagicMock()
        svc._ensure_clean_connection_state = MagicMock()
        svc._build_payload = MagicMock(return_value=mock_payload)
        svc.save_payload = MagicMock(return_value=mock_snapshot)

        result = svc.capture_snapshot()
        self.assertIs(result, mock_snapshot)


# ---------------------------------------------------------------------------
# build_live_payload
# ---------------------------------------------------------------------------


class TestBuildLivePayload(unittest.TestCase):
    def test_calls_ensure_clean_and_build_payload(self):
        """Lines 119-120."""
        svc, config, provider = _make_service()
        mock_payload = MagicMock()
        svc._ensure_clean_connection_state = MagicMock()
        svc._build_payload = MagicMock(return_value=mock_payload)

        result = svc.build_live_payload()

        svc._ensure_clean_connection_state.assert_called_once()
        svc._build_payload.assert_called_once()
        self.assertIs(result, mock_payload)


# ---------------------------------------------------------------------------
# save_payload - migration metadata paths
# ---------------------------------------------------------------------------


class TestSavePayloadMigrationMeta(unittest.TestCase):
    def test_migration_meta_extracted_from_payload(self):
        """Lines 129-153: save_payload reads migration metadata."""
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        svc, config, _ = _make_service()
        payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        payload.metadata["migration"] = {"last_version": "2.0", "installed_rank": 42}
        mock_snap = MagicMock()
        mock_snap.snapshot_id = "snap-001"
        svc.repository.save_snapshot_with_limit.return_value = mock_snap

        result = svc.save_payload(payload)

        call_kwargs = svc.repository.save_snapshot_with_limit.call_args[1]
        self.assertEqual(call_kwargs["migration_version"], "2.0")
        self.assertEqual(call_kwargs["installed_rank"], 42)
        self.assertIs(result, mock_snap)

    def test_save_payload_logs_debug(self):
        """Line 150-152: debug log after save."""
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        svc, config, _ = _make_service()
        payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        mock_snap = MagicMock()
        mock_snap.snapshot_id = "snap-xyz"
        svc.repository.save_snapshot_with_limit.return_value = mock_snap

        svc.save_payload(payload)

        debug_calls = [str(c) for c in svc.log.debug.call_args_list]
        assert any("snap-xyz" in c for c in debug_calls)

    def test_save_payload_no_reason(self):
        """Line 130: reason empty → no reason key in snapshot meta."""
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        svc, config, _ = _make_service()
        payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        svc.repository.save_snapshot_with_limit.return_value = MagicMock()

        svc.save_payload(payload, reason="")
        self.assertNotIn("reason", payload.metadata.get("snapshot", {}))


# ---------------------------------------------------------------------------
# load_snapshot_payload_from_path - non-JSON branch
# ---------------------------------------------------------------------------


class TestLoadSnapshotPayloadFromPath(unittest.TestCase):
    def test_non_json_uses_decode_payload(self):
        """Line 166: non-JSON content uses decode_payload."""
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        svc, *_ = _make_service()
        mock_payload = MagicMock(spec=SchemaSnapshotPayload)

        with patch(
            "core.migration.snapshots.schema_snapshot_service.decode_payload",
            return_value=mock_payload,
        ) as mock_decode:
            with NamedTemporaryFile(suffix=".bin", mode="w", delete=False) as f:
                f.write("not-a-json-payload")
                path = f.name
            try:
                result = svc.load_snapshot_payload_from_path(Path(path))
                mock_decode.assert_called_once()
                self.assertIs(result, mock_payload)
            finally:
                os.unlink(path)

    def test_decode_payload_exception_raises_value_error(self):
        """Lines 167-168: decode_payload exception → ValueError."""
        svc, *_ = _make_service()
        with patch(
            "core.migration.snapshots.schema_snapshot_service.decode_payload",
            side_effect=ValueError("bad data"),
        ):
            with NamedTemporaryFile(suffix=".bin", mode="w", delete=False) as f:
                f.write("some-encoded-content")
                path = f.name
            try:
                with self.assertRaises(ValueError):
                    svc.load_snapshot_payload_from_path(Path(path))
            finally:
                os.unlink(path)


# ---------------------------------------------------------------------------
# validate_snapshot_quality - quality_metrics paths
# ---------------------------------------------------------------------------


class TestValidateSnapshotQualityMetrics(unittest.TestCase):
    def _make_snap_with_validation(self, error_count=0, completeness_score=1.0):
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        snap = MagicMock()
        snap.payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        snap.metadata = {
            "validation": {
                "introspection_quality": {
                    "completeness_score": completeness_score,
                    "confidence_level": "HIGH",
                    "error_count": error_count,
                    "warning_count": 0,
                }
            }
        }
        return snap

    def test_quality_metrics_populated_from_metadata(self):
        """Lines 236-245: quality_metrics extracted from snapshot metadata."""
        svc, *_ = _make_service()
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        snap = self._make_snap_with_validation()
        svc.build_live_payload = MagicMock(
            return_value=SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        )

        result = svc.validate_snapshot_quality(snap)
        self.assertIn("quality_metrics", result)
        self.assertIn("completeness_score", result["quality_metrics"])
        self.assertIn("confidence_level", result["quality_metrics"])

    def test_error_count_marks_invalid(self):
        """Lines 248-252: introspection error_count > 0 → invalid."""
        svc, *_ = _make_service()
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        snap = self._make_snap_with_validation(error_count=2)
        svc.build_live_payload = MagicMock(
            return_value=SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        )

        result = svc.validate_snapshot_quality(snap)
        self.assertFalse(result["valid"])
        issues_text = " ".join(result["issues"])
        self.assertIn("2 errors", issues_text)

    def test_low_completeness_adds_issue(self):
        """Lines 254-258: completeness_score < 1.0 adds issue."""
        svc, *_ = _make_service()
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        snap = self._make_snap_with_validation(completeness_score=0.8)
        svc.build_live_payload = MagicMock(
            return_value=SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        )

        result = svc.validate_snapshot_quality(snap)
        issues_text = " ".join(result["issues"])
        self.assertIn("0.8", issues_text)

    def test_no_introspection_quality_key_skips_metrics(self):
        """Lines 239: empty introspection_quality → skip metrics section."""
        svc, *_ = _make_service()
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        snap = MagicMock()
        snap.payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        snap.metadata = {}
        svc.build_live_payload = MagicMock(
            return_value=SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        )

        result = svc.validate_snapshot_quality(snap)
        self.assertEqual(result["quality_metrics"], {})


# ---------------------------------------------------------------------------
# _build_payload
# ---------------------------------------------------------------------------


class _FakeIntrospectorBase:
    """Minimal introspector for _build_payload tests."""

    def get_tables(self, schema):
        return []

    def get_views(self, schema):
        return []

    def get_sequences(self, schema):
        return []

    def get_triggers(self, schema):
        return []

    def get_all_indexes(self, schema):
        return []


class TestBuildPayload(unittest.TestCase):
    def _patch_factory(self, introspector):
        return patch(
            "core.migration.snapshots.schema_snapshot_service.IntrospectorFactory.create",
            return_value=introspector,
        )

    def _patch_provider_capabilities(self):
        return patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        )

    def test_build_payload_returns_schema_snapshot_payload(self):
        """Lines 264-416: full _build_payload path with minimal introspector."""
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        svc, config, provider = _make_service()
        svc._ensure_clean_connection_state = MagicMock()
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        introspector = _FakeIntrospectorBase()

        with self._patch_factory(introspector):
            payload = svc._build_payload()

        self.assertIsInstance(payload, SchemaSnapshotPayload)

    def test_build_payload_with_result_tracking(self):
        """Lines 273-274: introspector.enable_result_tracking called when available."""
        svc, config, provider = _make_service()
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        introspector = _FakeIntrospectorBase()
        introspector.enable_result_tracking = MagicMock(return_value=None)

        with self._patch_factory(introspector):
            svc._build_payload()

        introspector.enable_result_tracking.assert_called_once()

    def test_build_payload_logs_warning_when_no_result_tracking(self):
        """Lines 276-279: warning logged when enable_result_tracking missing."""
        svc, config, provider = _make_service()
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        introspector = _FakeIntrospectorBase()
        # no enable_result_tracking attribute

        with self._patch_factory(introspector):
            svc._build_payload()

        svc.log.warning.assert_called()

    def test_build_payload_db2_rollback_via_provider(self):
        """Lines 421-428: DB2 dialect triggers rollback_transaction in finally."""
        svc, config, provider = _make_service(dialect="db2")
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        introspector = _FakeIntrospectorBase()
        provider.rollback_transaction = MagicMock()

        with self._patch_factory(introspector):
            svc._build_payload()

        provider.rollback_transaction.assert_called_once()

    def test_build_payload_mysql_rollback_via_provider(self):
        """Lines 421-428: MySQL dialect triggers rollback_transaction in finally."""
        svc, config, provider = _make_service(dialect="mysql")
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        introspector = _FakeIntrospectorBase()
        provider.rollback_transaction = MagicMock()

        with self._patch_factory(introspector):
            svc._build_payload()

        provider.rollback_transaction.assert_called_once()

    def test_build_payload_db2_direct_connection_rollback(self):
        """Lines 430-441: DB2 uses direct connection rollback when no rollback_transaction."""
        svc, config, provider = _make_service(dialect="db2")
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        conn = MagicMock()
        conn.getAutoCommit.return_value = False

        # provider has connection but no rollback_transaction
        del provider.rollback_transaction
        provider.connection = conn

        introspector = _FakeIntrospectorBase()

        with self._patch_factory(introspector):
            svc._build_payload()

        conn.rollback.assert_called_once()

    def test_build_payload_db2_autocommit_skips_rollback(self):
        """Lines 433: autocommit=True → skip direct rollback."""
        svc, config, provider = _make_service(dialect="db2")
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        conn = MagicMock()
        conn.getAutoCommit.return_value = True

        del provider.rollback_transaction
        provider.connection = conn

        introspector = _FakeIntrospectorBase()

        with self._patch_factory(introspector):
            svc._build_payload()

        conn.rollback.assert_not_called()

    def test_build_payload_db2_rollback_exception_non_fatal(self):
        """Lines 442-446: exception in rollback block is caught."""
        svc, config, provider = _make_service(dialect="db2")
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        provider.rollback_transaction = MagicMock(side_effect=RuntimeError("rollback failed"))

        introspector = _FakeIntrospectorBase()

        with self._patch_factory(introspector):
            payload = svc._build_payload()  # must not raise

        self.assertIsNotNone(payload)

    def test_build_payload_with_validation_metadata(self):
        """Lines 335-374: introspection_result triggers validation."""
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        svc, config, provider = _make_service()
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        introspection_result = MagicMock()
        introspection_result.get_completeness_score.return_value = 0.9
        introspection_result.get_confidence_level.return_value = "MEDIUM"
        introspection_result.errors = ["err1"]
        introspection_result.warnings = ["warn1"]
        introspection_result.object_statuses = []

        introspector = _FakeIntrospectorBase()
        introspector.enable_result_tracking = MagicMock(return_value=introspection_result)

        with self._patch_factory(introspector):
            payload = svc._build_payload()

        self.assertIn("introspection_quality", payload.metadata)
        svc.log.warning.assert_called()


# ---------------------------------------------------------------------------
# _collect_migration_metadata
# ---------------------------------------------------------------------------


class TestCollectMigrationMetadata(unittest.TestCase):
    def test_basic_versioned_migrations(self):
        """Lines 449-490: versioned migrations build metadata."""
        from datetime import datetime, timezone

        from core.migration.migration import MigrationType

        svc, config, provider = _make_service()

        m1 = MagicMock()
        m1.type = MigrationType.SQL
        m1.version = "1.0"
        m1.installed_rank = 1

        m2 = MagicMock()
        m2.type = MigrationType.SQL
        m2.version = "2.0"
        m2.installed_rank = 2

        svc.history_manager.get_applied_migrations.return_value = [m1, m2]

        meta = svc._collect_migration_metadata()

        self.assertEqual(meta["last_version"], "2.0")
        self.assertEqual(meta["installed_rank"], 2)
        self.assertIn("1.0", meta["applied_versions"])
        self.assertIn("2.0", meta["applied_versions"])

    def test_empty_migrations(self):
        """Lines 463-464: no versioned migrations → last_version=None."""
        svc, config, provider = _make_service()
        svc.history_manager.get_applied_migrations.return_value = []

        meta = svc._collect_migration_metadata()

        self.assertIsNone(meta["last_version"])
        self.assertIsNone(meta["installed_rank"])
        self.assertEqual(meta["applied_versions"], [])
        self.assertEqual(meta["repeatables"], [])

    def test_repeatable_migrations(self):
        """Lines 466-480: repeatable migrations collected."""
        from datetime import datetime, timezone

        from core.migration.migration import MigrationType

        svc, config, provider = _make_service()

        r1 = MagicMock()
        r1.type = MigrationType.REPEATABLE
        r1.script_name = "R__seed.sql"
        r1.checksum = "abc123"
        r1.installed_rank = 5
        r1.installed_on = datetime(2024, 1, 1, tzinfo=timezone.utc)

        svc.history_manager.get_applied_migrations.return_value = [r1]

        meta = svc._collect_migration_metadata()

        self.assertEqual(len(meta["repeatables"]), 1)
        rep = meta["repeatables"][0]
        self.assertEqual(rep["script"], "R__seed.sql")
        self.assertIsInstance(rep["installed_on"], str)

    def test_repeatable_with_non_datetime_installed_on(self):
        """Line 471: installed_on is not datetime → kept as-is."""
        from core.migration.migration import MigrationType

        svc, config, provider = _make_service()

        r1 = MagicMock()
        r1.type = MigrationType.REPEATABLE
        r1.script_name = "R__seed.sql"
        r1.checksum = "def456"
        r1.installed_rank = 3
        r1.installed_on = "2024-01-01T00:00:00"

        svc.history_manager.get_applied_migrations.return_value = [r1]

        meta = svc._collect_migration_metadata()

        rep = meta["repeatables"][0]
        self.assertEqual(rep["installed_on"], "2024-01-01T00:00:00")

    def test_exception_returns_empty_metadata(self):
        """Lines 452-454: exception → empty dict returned."""
        svc, config, provider = _make_service()
        svc.history_manager.get_applied_migrations.side_effect = RuntimeError("DB down")

        meta = svc._collect_migration_metadata()

        self.assertEqual(meta, {})

    def test_migration_without_version_excluded_from_applied_versions(self):
        """Line 486: migration.version is None → excluded from applied_versions list."""
        from core.migration.migration import MigrationType

        svc, config, provider = _make_service()

        m1 = MagicMock()
        m1.type = MigrationType.SQL
        m1.version = None
        m1.installed_rank = 1

        svc.history_manager.get_applied_migrations.return_value = [m1]

        meta = svc._collect_migration_metadata()

        self.assertEqual(meta["applied_versions"], [])


# ---------------------------------------------------------------------------
# _validate_snapshot_accuracy
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _filter_tables
# ---------------------------------------------------------------------------


class TestFilterTablesCoverage(unittest.TestCase):
    def _make_table(self, name, schema="public"):
        t = SimpleNamespace(name=name, schema=schema)
        return t

    def test_excludes_migration_lock_table(self):
        """Line 620: MIGRATION_LOCK_TABLE excluded."""
        svc, config, provider = _make_service()
        provider.MIGRATION_LOCK_TABLE = "dblift_lock"
        svc.provider = provider
        tables = [
            self._make_table("users"),
            self._make_table("dblift_lock"),
        ]
        result, keys = svc._filter_tables(tables, "public")
        names = [t.name for t in result]
        self.assertNotIn("dblift_lock", names)
        self.assertIn("users", names)

    def test_excludes_snapshot_table(self):
        """Line 621-622: snapshot_table excluded."""
        svc, config, provider = _make_service()
        config.snapshot_table = "my_snapshots"
        tables = [
            self._make_table("users"),
            self._make_table("my_snapshots"),
        ]
        result, keys = svc._filter_tables(tables, "public")
        names = [t.name for t in result]
        self.assertNotIn("my_snapshots", names)

    def test_returns_table_keys(self):
        """Lines 636-640: table_keys set populated correctly."""
        svc, *_ = _make_service()
        tables = [self._make_table("orders"), self._make_table("customers")]
        _, keys = svc._filter_tables(tables, "public")
        self.assertEqual(len(keys), 2)
        for key in keys:
            self.assertIn(".", key)

    def test_none_table_schema_uses_default(self):
        """Line 633: table.schema = None → default_schema used."""
        svc, *_ = _make_service()
        t = SimpleNamespace(name="products", schema=None)
        result, keys = svc._filter_tables([t], "myschema")
        self.assertEqual(len(result), 1)
        key = next(iter(keys))
        self.assertIn("myschema", key)


# ---------------------------------------------------------------------------
# _filter_views
# ---------------------------------------------------------------------------


class TestFilterViewsCoverage(unittest.TestCase):
    def test_excludes_history_table_name_from_views(self):
        """Line 644-653: history_table name excluded from views."""
        svc, config, provider = _make_service()
        v_internal = SimpleNamespace(name="dblift_schema_history", schema="public")
        v_user = SimpleNamespace(name="v_active_users", schema="public")
        result = svc._filter_views([v_internal, v_user], "public")
        names = [v.name for v in result]
        self.assertNotIn("dblift_schema_history", names)
        self.assertIn("v_active_users", names)

    def test_excludes_snapshot_table_from_views(self):
        """Lines 644-645: snapshot_table excluded."""
        svc, config, provider = _make_service()
        config.snapshot_table = "snap_view"
        v = SimpleNamespace(name="snap_view", schema="public")
        result = svc._filter_views([v], "public")
        self.assertEqual(result, [])

    def test_empty_views_list(self):
        svc, *_ = _make_service()
        result = svc._filter_views([], "public")
        self.assertEqual(result, [])

    def test_none_views_list(self):
        svc, *_ = _make_service()
        result = svc._filter_views(None, "public")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _filter_indexes
# ---------------------------------------------------------------------------


class TestFilterIndexesCoverage(unittest.TestCase):
    def _make_index(self, name, table_name="users", schema="public"):
        return SimpleNamespace(
            name=name,
            table_name=table_name,
            schema=schema,
            table_schema=schema,
        )

    def _make_table_with_constraint(self, name, constraint_name, ctype):
        from core.sql_model.base import ConstraintType

        c = SimpleNamespace(name=constraint_name, constraint_type=ctype)
        return SimpleNamespace(name=name, schema="public", constraints=[c])

    def test_index_on_allowed_table_included(self):
        """Lines 668-678: index on allowed table included."""
        svc, *_ = _make_service()
        idx = self._make_index("idx_users_email", "users")
        table = SimpleNamespace(name="users", schema="public", constraints=[])
        _, keys = svc._filter_tables([table], "public")
        result = svc._filter_indexes([idx], keys, [table])
        self.assertEqual(len(result), 1)

    def test_index_on_disallowed_table_excluded(self):
        """Lines 672: index table_key not in allowed_table_keys → excluded."""
        svc, *_ = _make_service()
        idx = self._make_index("idx_other_col", "other_table")
        result = svc._filter_indexes([idx], {"public.users"}, [])
        self.assertEqual(result, [])

    def test_pk_constraint_index_excluded(self):
        """Lines 660-666: PK constraint names excluded from indexes."""
        from core.sql_model.base import ConstraintType

        svc, *_ = _make_service()
        table = self._make_table_with_constraint("users", "pk_users", ConstraintType.PRIMARY_KEY)
        idx = self._make_index("pk_users", "users")
        _, keys = svc._filter_tables([table], "public")
        result = svc._filter_indexes([idx], keys, [table])
        self.assertEqual(result, [])

    def test_unique_constraint_index_excluded(self):
        """Lines 660-666: UNIQUE constraint names excluded from indexes."""
        from core.sql_model.base import ConstraintType

        svc, *_ = _make_service()
        table = self._make_table_with_constraint("users", "uq_email", ConstraintType.UNIQUE)
        idx = self._make_index("uq_email", "users")
        _, keys = svc._filter_tables([table], "public")
        result = svc._filter_indexes([idx], keys, [table])
        self.assertEqual(result, [])

    def test_regular_index_not_excluded(self):
        """Lines 668-678: regular index not in constraints is included."""
        from core.sql_model.base import ConstraintType

        svc, *_ = _make_service()
        table = self._make_table_with_constraint("users", "pk_users", ConstraintType.PRIMARY_KEY)
        idx = self._make_index("idx_name", "users")
        _, keys = svc._filter_tables([table], "public")
        result = svc._filter_indexes([idx], keys, [table])
        self.assertEqual(len(result), 1)

    def test_index_uses_table_schema_fallback(self):
        """Line 670: table_schema fallback used when schema attr missing."""
        svc, *_ = _make_service()
        idx = SimpleNamespace(
            name="idx_col",
            table_name="users",
            table_schema="public",
        )
        result = svc._filter_indexes([idx], {"public.users"}, [])
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# _filter_triggers
# ---------------------------------------------------------------------------


class TestFilterTriggersCoverage(unittest.TestCase):
    def test_trigger_on_allowed_table_included(self):
        """Lines 682-689: trigger matching table_key included."""
        svc, *_ = _make_service()
        t = SimpleNamespace(
            name="trg_audit", schema="public", table_name="orders", table_schema="public"
        )
        result = svc._filter_triggers([t], {"public.orders"})
        self.assertEqual(len(result), 1)

    def test_trigger_on_disallowed_table_excluded(self):
        svc, *_ = _make_service()
        t = SimpleNamespace(
            name="trg_x", schema="public", table_name="hidden", table_schema="public"
        )
        result = svc._filter_triggers([t], {"public.orders"})
        self.assertEqual(result, [])

    def test_trigger_uses_table_schema_fallback(self):
        """Line 683-684: table_schema attribute used as fallback."""
        svc, *_ = _make_service()
        # trigger has no 'schema' attr → use table_schema
        t = SimpleNamespace(name="trg_b", table_name="users", table_schema="myschema")
        result = svc._filter_triggers([t], {"myschema.users"})
        self.assertEqual(len(result), 1)

    def test_empty_triggers_list(self):
        svc, *_ = _make_service()
        result = svc._filter_triggers([], set())
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _filter_user_defined_types
# ---------------------------------------------------------------------------


class TestFilterUserDefinedTypesCoverage(unittest.TestCase):
    def test_udt_not_matching_reserved_included(self):
        """Lines 704-709: UDT not in reserved names is kept."""
        svc, *_ = _make_service()
        udt = SimpleNamespace(name="my_enum")
        table = SimpleNamespace(name="users")
        view = SimpleNamespace(name="v_users")
        result = svc._filter_user_defined_types([udt], [table], [view])
        self.assertEqual(len(result), 1)

    def test_udt_matching_table_name_excluded(self):
        """Lines 695: UDT matching table name excluded."""
        svc, *_ = _make_service()
        udt = SimpleNamespace(name="users")
        table = SimpleNamespace(name="users")
        result = svc._filter_user_defined_types([udt], [table], [])
        self.assertEqual(result, [])

    def test_udt_matching_view_name_excluded(self):
        """Lines 696: UDT matching view name excluded."""
        svc, *_ = _make_service()
        udt = SimpleNamespace(name="v_users")
        view = SimpleNamespace(name="v_users")
        result = svc._filter_user_defined_types([udt], [], [view])
        self.assertEqual(result, [])

    def test_udt_matching_history_table_excluded(self):
        """Lines 697-700: UDT matching history_table excluded."""
        svc, *_ = _make_service()
        svc.history_manager.history_table = "dblift_schema_history"
        udt = SimpleNamespace(name="dblift_schema_history")
        result = svc._filter_user_defined_types([udt], [], [])
        self.assertEqual(result, [])

    def test_empty_udts(self):
        svc, *_ = _make_service()
        result = svc._filter_user_defined_types(None, [], [])
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _filter_sequences
# ---------------------------------------------------------------------------


class TestFilterSequencesCoverage(unittest.TestCase):
    def test_regular_sequence_kept(self):
        """Lines 719-732: regular sequence included."""
        svc, *_ = _make_service()
        seq = SimpleNamespace(name="order_seq")
        result = svc._filter_sequences([seq], [])
        self.assertEqual(len(result), 1)

    def test_oracle_identity_sequence_excluded(self):
        """Line 725-727: iseq$$_ prefix excluded."""
        svc, *_ = _make_service()
        seq = SimpleNamespace(name="iseq$$_1234")
        result = svc._filter_sequences([seq], [])
        self.assertEqual(result, [])

    def test_id_seq_suffix_with_matching_table_excluded(self):
        """Lines 728-731: _id_seq suffix matching table name excluded."""
        svc, *_ = _make_service()
        table = SimpleNamespace(name="orders")
        seq = SimpleNamespace(name="orders_id_seq")
        result = svc._filter_sequences([seq], [table])
        self.assertEqual(result, [])

    def test_id_seq_suffix_no_matching_table_kept(self):
        """Lines 728-731: _id_seq suffix without matching table kept."""
        svc, *_ = _make_service()
        seq = SimpleNamespace(name="invoices_id_seq")
        result = svc._filter_sequences([seq], [])
        self.assertEqual(len(result), 1)

    def test_sequence_with_history_prefix_excluded(self):
        """Lines 723-724: sequence starting with history_table name excluded."""
        svc, *_ = _make_service()
        svc.history_manager.history_table = "dblift_schema_history"
        seq = SimpleNamespace(name="dblift_schema_history_seq")
        result = svc._filter_sequences([seq], [])
        self.assertEqual(result, [])

    def test_none_name_sequence_excluded(self):
        """Line 721: sequence with None name excluded."""
        svc, *_ = _make_service()
        seq = SimpleNamespace(name=None)
        result = svc._filter_sequences([seq], [])
        self.assertEqual(result, [])

    def test_empty_sequences(self):
        svc, *_ = _make_service()
        result = svc._filter_sequences([], [])
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _is_connection_error
# ---------------------------------------------------------------------------


class TestIsConnectionErrorCoverage(unittest.TestCase):
    def test_ora_17002_is_connection_error(self):
        """Line 747-759: ORA-17002 pattern recognized."""
        svc, config, provider = _make_service()
        del provider.error_handler
        err = Exception("ORA-17002: IO exception")
        result = svc._is_connection_error(err)
        self.assertTrue(result)

    def test_connection_reset_is_connection_error(self):
        svc, config, provider = _make_service()
        del provider.error_handler
        err = Exception("connection reset by peer")
        result = svc._is_connection_error(err)
        self.assertTrue(result)

    def test_generic_error_not_connection(self):
        svc, config, provider = _make_service()
        del provider.error_handler
        err = Exception("syntax error near SELECT")
        result = svc._is_connection_error(err)
        self.assertFalse(result)

    def test_uses_error_handler_when_available(self):
        """Lines 737-744: error_handler.categorize_error used."""
        svc, config, provider = _make_service()

        handler = MagicMock()
        handler.ErrorCategory = MagicMock()
        handler.ErrorCategory.NETWORK = "NETWORK"
        handler.ErrorCategory.TIMEOUT = "TIMEOUT"
        handler.ErrorCategory.AUTHENTICATION = "AUTH"
        handler.categorize_error.return_value = "NETWORK"
        provider.error_handler = handler

        err = Exception("some error")
        result = svc._is_connection_error(err)
        self.assertTrue(result)


# ---------------------------------------------------------------------------
# _try_bulk_indexes
# ---------------------------------------------------------------------------


class TestTryBulkIndexesCoverage(unittest.TestCase):
    def test_uses_get_all_indexes_when_available(self):
        """Lines 784-789: get_all_indexes called and result returned."""
        svc, *_ = _make_service()
        introspector = MagicMock()
        idx = SimpleNamespace(name="idx_col")
        introspector.get_all_indexes.return_value = [idx]

        result = svc._try_bulk_indexes(introspector, "public", [])
        self.assertEqual(result, [idx])

    def test_falls_back_to_per_table_when_non_list_returned(self):
        """Lines 791-793: non-list result → per-table fallback."""
        svc, *_ = _make_service()
        introspector = MagicMock()
        introspector.get_all_indexes.return_value = "not-a-list"

        table = SimpleNamespace(name="users")
        idx = SimpleNamespace(name="idx_users_id")
        introspector.get_indexes.return_value = [idx]

        result = svc._try_bulk_indexes(introspector, "public", [table])
        self.assertIn(idx, result)

    def test_falls_back_to_per_table_on_exception(self):
        """Lines 794-797: exception in get_all_indexes → per-table fallback."""
        svc, *_ = _make_service()
        introspector = MagicMock()
        introspector.get_all_indexes.side_effect = RuntimeError("query failed")

        table = SimpleNamespace(name="orders")
        idx = SimpleNamespace(name="idx_orders")
        introspector.get_indexes.return_value = [idx]

        result = svc._try_bulk_indexes(introspector, "public", [table])
        self.assertIn(idx, result)

    def test_no_get_all_indexes_method_uses_per_table(self):
        """Lines 783: no get_all_indexes → per-table loop."""
        svc, *_ = _make_service()
        introspector = MagicMock(spec=["get_indexes"])
        idx = SimpleNamespace(name="idx_x")
        introspector.get_indexes.return_value = [idx]
        table = SimpleNamespace(name="products")

        result = svc._try_bulk_indexes(introspector, "public", [table])
        self.assertIn(idx, result)

    def test_per_table_skips_tables_without_name(self):
        """Line 803: table without name attribute skipped."""
        svc, *_ = _make_service()
        introspector = MagicMock(spec=["get_indexes"])
        introspector.get_indexes.return_value = []
        table_no_name = SimpleNamespace(name=None)

        result = svc._try_bulk_indexes(introspector, "public", [table_no_name])
        introspector.get_indexes.assert_not_called()
        self.assertEqual(result, [])

    def test_connection_error_propagated(self):
        """Lines 795-796: connection error in get_all_indexes is re-raised."""
        svc, config, provider = _make_service()
        # Make _is_connection_error return True
        del provider.error_handler
        introspector = MagicMock()
        introspector.get_all_indexes.side_effect = Exception("ORA-17002 connection lost")

        with self.assertRaises(Exception):
            svc._try_bulk_indexes(introspector, "public", [])


# ---------------------------------------------------------------------------
# _ensure_clean_connection_state
# ---------------------------------------------------------------------------


class TestEnsureCleanConnectionState(unittest.TestCase):
    def test_calls_rollback_transaction_when_available(self):
        """Lines 863-868: rollback_transaction called."""
        svc, config, provider = _make_service()
        provider.rollback_transaction = MagicMock()

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        ):
            svc._ensure_clean_connection_state()

        provider.rollback_transaction.assert_called_once()

    def test_uses_direct_connection_rollback_as_fallback(self):
        """Lines 872-877: direct connection rollback via provider.connection."""
        svc, config, provider = _make_service()

        conn = MagicMock()
        conn.isClosed.return_value = False
        conn.getAutoCommit.return_value = False
        provider.connection = conn
        del provider.rollback_transaction

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        ):
            svc._ensure_clean_connection_state()

        conn.rollback.assert_called_once()

    def test_reconnects_when_connection_closed(self):
        """Lines 883-886: isClosed() → True triggers _ensure_valid_connection."""
        svc, config, provider = _make_service()

        conn = MagicMock()
        conn.isClosed.return_value = True
        provider.connection = conn
        del provider.rollback_transaction

        svc._ensure_valid_connection = MagicMock()

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        ):
            svc._ensure_clean_connection_state()

        # _ensure_valid_connection should be called (from closed-connection branch)
        svc._ensure_valid_connection.assert_called()

    def test_handles_exception_during_connection_check(self):
        """Lines 887-891: isClosed() raises → _ensure_valid_connection called."""
        svc, config, provider = _make_service()

        conn = MagicMock()
        conn.isClosed.side_effect = RuntimeError("closed")
        provider.connection = conn
        del provider.rollback_transaction

        svc._ensure_valid_connection = MagicMock()

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        ):
            svc._ensure_clean_connection_state()

        svc._ensure_valid_connection.assert_called()

    def test_uses_query_executor_connection_fallback(self):
        """Lines 874-877: connection from query_executor when no provider.connection."""
        svc, config, provider = _make_service()

        conn = MagicMock()
        conn.isClosed.return_value = False
        conn.getAutoCommit.return_value = False

        qe = MagicMock(spec=["connection"])
        qe.connection = conn
        # remove connection from provider, add query_executor
        del provider.connection
        provider.query_executor = qe
        del provider.rollback_transaction

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        ):
            svc._ensure_clean_connection_state()

        conn.rollback.assert_called_once()

    def test_autocommit_on_skips_rollback(self):
        """Line 895: autocommit=True → rollback not called."""
        svc, config, provider = _make_service()

        conn = MagicMock()
        conn.isClosed.return_value = False
        conn.getAutoCommit.return_value = True
        provider.connection = conn
        del provider.rollback_transaction

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        ):
            svc._ensure_clean_connection_state()

        conn.rollback.assert_not_called()

    def test_outer_exception_non_fatal(self):
        """Lines 904-906: outer exception is caught."""
        svc, config, provider = _make_service()

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            side_effect=RuntimeError("cannot connect"),
        ):
            svc._ensure_clean_connection_state()  # must not raise


# ---------------------------------------------------------------------------
# _ensure_valid_connection
# ---------------------------------------------------------------------------


class TestEnsureValidConnection(unittest.TestCase):
    def test_uses_ensure_provider_connection(self):
        """Lines 912-913: ensure_provider_connection called."""
        svc, config, provider = _make_service()

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        ) as mock_ensure:
            svc._ensure_valid_connection()

        mock_ensure.assert_called_once_with(provider)

    def test_fallback_to_query_executor_when_provider_not_connected(self):
        """Lines 914-917: fallback to query_executor._ensure_connection."""
        svc, config, provider = _make_service()

        qe = MagicMock()
        provider.query_executor = qe

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=False,
        ):
            svc._ensure_valid_connection()

        qe._ensure_connection.assert_called_once()

    def test_exception_in_ensure_connection_non_fatal(self):
        """Lines 919-920: exception is caught."""
        svc, config, provider = _make_service()

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            side_effect=RuntimeError("boom"),
        ):
            svc._ensure_valid_connection()  # must not raise


# ---------------------------------------------------------------------------
# _safe_introspect - connection error propagation
# ---------------------------------------------------------------------------


class TestSafeIntrospectConnectionError(unittest.TestCase):
    def test_connection_error_is_propagated(self):
        """Lines 775-776: connection error in _safe_introspect is re-raised."""
        svc, config, provider = _make_service()
        del provider.error_handler

        func = MagicMock(side_effect=Exception("ORA-17002 broken pipe"))
        with self.assertRaises(Exception):
            svc._safe_introspect(func, "schema")

    def test_attribute_error_returns_empty(self):
        """Lines 770-773: AttributeError returns []."""
        svc, *_ = _make_service()
        func = MagicMock(side_effect=AttributeError("no attr"))
        result = svc._safe_introspect(func, "schema")
        self.assertEqual(result, [])

    def test_returns_empty_list_when_result_is_none(self):
        """Line 769: result is falsy → [] returned."""
        svc, *_ = _make_service()
        func = MagicMock(return_value=None)
        result = svc._safe_introspect(func)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# _call_optional
# ---------------------------------------------------------------------------


class TestCallOptionalCoverage(unittest.TestCase):
    def test_not_callable_logs_debug(self):
        """Lines 812-814: non-callable attr logged."""
        svc, *_ = _make_service()
        obj = SimpleNamespace(get_tables="not-callable")
        result = svc._call_optional(obj, "get_tables")
        self.assertEqual(result, [])
        debug_calls = [str(c) for c in svc.log.debug.call_args_list]
        assert any("not callable" in c or "not found" in c.lower() for c in debug_calls)

    def test_missing_attr_logs_debug(self):
        """Lines 812-814: missing attr logged."""
        svc, *_ = _make_service()
        obj = SimpleNamespace()
        result = svc._call_optional(obj, "nonexistent")
        self.assertEqual(result, [])

    def test_callable_with_no_args(self):
        """Line 817: callable with no args."""
        svc, *_ = _make_service()
        obj = MagicMock()
        obj.get_extensions.return_value = ["ext1"]
        result = svc._call_optional(obj, "get_extensions")
        self.assertEqual(result, ["ext1"])


# ---------------------------------------------------------------------------
# _deep_update
# ---------------------------------------------------------------------------


class TestDeepUpdateCoverage(unittest.TestCase):
    def test_deep_nested_merge(self):
        """Lines 839-844: nested dict merged recursively."""
        svc, *_ = _make_service()
        target = {"a": {"x": 1, "y": 2}}
        source = {"a": {"y": 99, "z": 3}}
        svc._deep_update(target, source)
        self.assertEqual(target["a"]["x"], 1)
        self.assertEqual(target["a"]["y"], 99)
        self.assertEqual(target["a"]["z"], 3)

    def test_overwrite_non_dict_value(self):
        """Line 843: non-dict value overwritten."""
        svc, *_ = _make_service()
        target = {"key": "old"}
        source = {"key": "new"}
        svc._deep_update(target, source)
        self.assertEqual(target["key"], "new")

    def test_new_key_added(self):
        svc, *_ = _make_service()
        target = {}
        source = {"fresh": "value"}
        svc._deep_update(target, source)
        self.assertEqual(target["fresh"], "value")


# ---------------------------------------------------------------------------
# _get_snapshot_connection
# ---------------------------------------------------------------------------


class TestGetSnapshotConnection(unittest.TestCase):
    def test_returns_snapshot_connection_context(self):
        """Line 922-924: returns SnapshotConnectionContext."""
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        svc, config, provider = _make_service()
        ctx = svc._get_snapshot_connection()
        self.assertIsInstance(ctx, SnapshotConnectionContext)
        self.assertIs(ctx.provider, provider)


# ---------------------------------------------------------------------------
# Additional targeted coverage for remaining missing lines
# ---------------------------------------------------------------------------


class TestSnapshotConnectionContextExitException(unittest.TestCase):
    """Cover lines 69-70: log.debug raises in __exit__ except block."""

    def test_exit_exception_handled_in_finally_clause(self):
        """Lines 69-70: test that the except branch in __exit__ is reachable.

        The except branch fires when log.debug("Snapshot connection context completed")
        raises. We trigger that to cover line 69-70.
        """
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        provider.is_connected.return_value = True
        log = MagicMock()

        ctx = SnapshotConnectionContext(provider, log)
        ctx.__enter__()

        # Make the first log.debug call (line 68) raise → triggers except at 69-70
        # We set side_effect on the mock's debug method to raise on the next call
        log.debug.side_effect = RuntimeError("log failure")

        # __exit__ must survive even if log.debug raises
        # (the except catches it and calls log.debug again, which also raises but
        # that will propagate — so we verify the except path is reached at all by
        # checking the side_effect call count; the second raise IS expected here)
        try:
            ctx.__exit__(None, None, None)
        except RuntimeError:
            pass  # Expected: second log.debug also raises, propagates out

        # The except branch (lines 69-70) was triggered if debug was called ≥2 times
        self.assertGreaterEqual(log.debug.call_count, 2)


class TestBuildPayloadDirectConnectionRollbackException(unittest.TestCase):
    """Cover lines 439-441: connection.rollback() raises in the try block."""

    def _patch_factory(self, introspector):
        return patch(
            "core.migration.snapshots.schema_snapshot_service.IntrospectorFactory.create",
            return_value=introspector,
        )

    def test_build_payload_db2_direct_rollback_raises(self):
        """Lines 439-441: connection.rollback() raises → exception silently swallowed."""
        svc, config, provider = _make_service(dialect="db2")
        svc._collect_migration_metadata = MagicMock(return_value={})
        svc._validate_snapshot_accuracy = MagicMock()

        conn = MagicMock()
        conn.getAutoCommit.return_value = False
        conn.rollback.side_effect = RuntimeError("dead connection")

        del provider.rollback_transaction
        provider.connection = conn

        introspector = _FakeIntrospectorBase()

        with self._patch_factory(introspector):
            payload = svc._build_payload()  # must not raise

        # rollback was attempted and raised
        conn.rollback.assert_called_once()
        # payload was still returned
        self.assertIsNotNone(payload)


class TestEnsureCleanConnectionStateRollbackException(unittest.TestCase):
    """Cover lines 867-868: rollback_transaction raises → debug logged."""

    def test_rollback_transaction_exception_logged(self):
        """Lines 867-868: provider.rollback_transaction raises → log.debug called."""
        svc, config, provider = _make_service()
        provider.rollback_transaction = MagicMock(side_effect=RuntimeError("tx failed"))
        provider.connection = MagicMock()
        provider.connection.isClosed.return_value = False
        provider.connection.getAutoCommit.return_value = True

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        ):
            svc._ensure_clean_connection_state()  # must not raise

        debug_calls = [str(c) for c in svc.log.debug.call_args_list]
        assert any("Could not rollback" in c or "tx failed" in c for c in debug_calls)


class TestEnsureCleanConnectionStateGetAutoCommitException(unittest.TestCase):
    """Cover lines 902-903: getAutoCommit raises in inner try block."""

    def test_get_auto_commit_exception_logged(self):
        """Lines 902-903: getAutoCommit() raises → except branch logs debug."""
        svc, config, provider = _make_service()

        conn = MagicMock()
        conn.isClosed.return_value = False
        conn.getAutoCommit.side_effect = RuntimeError("auto-commit check failed")
        provider.connection = conn
        del provider.rollback_transaction

        with patch(
            "core.migration.snapshots.schema_snapshot_service.ensure_provider_connection",
            return_value=True,
        ):
            svc._ensure_clean_connection_state()  # must not raise

        debug_calls = [str(c) for c in svc.log.debug.call_args_list]
        assert any(
            "Could not check/rollback" in c or "auto-commit" in c.lower() for c in debug_calls
        )


class TestEnsureCleanConnectionStateOuterException(unittest.TestCase):
    """Cover lines 904-906: outer exception handler."""

    def test_outer_exception_from_ensure_valid_logs_debug(self):
        """Lines 904-906: _ensure_valid_connection raises → outer except logs."""
        svc, config, provider = _make_service()
        svc._ensure_valid_connection = MagicMock(side_effect=RuntimeError("no conn"))

        svc._ensure_clean_connection_state()  # must not raise

        debug_calls = [str(c) for c in svc.log.debug.call_args_list]
        assert any("Could not ensure clean" in c or "no conn" in c for c in debug_calls)


if __name__ == "__main__":
    unittest.main()
