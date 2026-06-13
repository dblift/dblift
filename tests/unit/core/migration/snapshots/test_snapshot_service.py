"""Tests for core/migration/snapshots/schema_snapshot_service.py."""

import unittest
from unittest.mock import MagicMock, patch


def _make_config(dialect="postgresql", schema="public"):
    config = MagicMock()
    config.database.type = dialect
    config.database.schema = schema
    config.max_snapshots = 1
    config.snapshot_table = None
    return config


def _make_service(dialect="postgresql"):
    from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

    config = _make_config(dialect)
    provider = MagicMock()
    provider.config = config
    provider.get_normalized_object_name.side_effect = lambda n: n.lower()
    provider.get_schema_qualified_name.side_effect = lambda s, t: f"{s}.{t}"
    provider.get_parameter_placeholders.return_value = "?, ?, ?, ?"
    history_manager = MagicMock()
    log = MagicMock()
    with patch("core.migration.snapshots.schema_snapshot_service.SchemaSnapshotRepository"):
        svc = SchemaSnapshotService(
            config=config, provider=provider, history_manager=history_manager, log=log
        )
    svc.repository = MagicMock()
    return svc, config, provider


class TestSnapshotConnectionContext(unittest.TestCase):
    def test_enter_when_not_connected(self):
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        provider.is_connected.return_value = False
        ctx = SnapshotConnectionContext(provider, MagicMock())
        with ctx:
            provider.create_connection.assert_called_once()

    def test_enter_when_already_connected(self):
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        provider.is_connected.return_value = True
        ctx = SnapshotConnectionContext(provider, MagicMock())
        with ctx:
            provider.create_connection.assert_not_called()

    def test_enter_suppresses_errors(self):
        from core.migration.snapshots.schema_snapshot_service import SnapshotConnectionContext

        provider = MagicMock()
        provider.is_connected.side_effect = Exception("conn err")
        ctx = SnapshotConnectionContext(provider, MagicMock())
        with ctx:  # should not raise
            pass


class TestSchemaSnapshotServiceInit(unittest.TestCase):
    def test_init_stores_config(self):
        svc, config, _ = _make_service()
        self.assertIs(svc.config, config)

    def test_init_null_log(self):
        from core.logger import NullLog
        from core.migration.snapshots.schema_snapshot_service import SchemaSnapshotService

        config = _make_config()
        provider = MagicMock()
        provider.get_normalized_object_name.side_effect = lambda n: n
        with patch("core.migration.snapshots.schema_snapshot_service.SchemaSnapshotRepository"):
            svc = SchemaSnapshotService(
                config=config, provider=provider, history_manager=MagicMock(), log=None
            )
        self.assertIsInstance(svc.log, NullLog)


class TestSchemaSnapshotServiceLoadLatest(unittest.TestCase):
    def test_delegates_to_repository(self):
        svc, *_ = _make_service()
        mock_snap = MagicMock()
        svc.repository.get_latest_snapshot.return_value = mock_snap
        result = svc.load_latest_snapshot()
        self.assertIs(result, mock_snap)

    def test_returns_none_when_no_snapshot(self):
        svc, *_ = _make_service()
        svc.repository.get_latest_snapshot.return_value = None
        self.assertIsNone(svc.load_latest_snapshot())


class TestSchemaSnapshotServiceSavePayload(unittest.TestCase):
    def test_save_payload_calls_repository(self):
        svc, config, _ = _make_service()
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        mock_snap = MagicMock()
        svc.repository.save_snapshot_with_limit.return_value = mock_snap
        result = svc.save_payload(payload)
        svc.repository.save_snapshot_with_limit.assert_called_once()
        self.assertIs(result, mock_snap)

    def test_save_payload_with_reason(self):
        svc, *_ = _make_service()
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        svc.repository.save_snapshot_with_limit.return_value = MagicMock()
        svc.save_payload(payload, reason="test reason")
        self.assertEqual(payload.metadata["snapshot"]["reason"], "test reason")

    def test_save_payload_with_extra_metadata(self):
        svc, *_ = _make_service()
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        svc.repository.save_snapshot_with_limit.return_value = MagicMock()
        svc.save_payload(payload, extra_metadata={"custom": "value"})
        self.assertEqual(payload.metadata["custom"], "value")


class TestSchemaSnapshotServiceLoadFromPath(unittest.TestCase):
    def test_load_json_file(self):
        svc, *_ = _make_service()
        import json
        from pathlib import Path
        from tempfile import NamedTemporaryFile

        data = {"tables": [], "views": [], "indexes": [], "metadata": {}}
        with NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            payload = svc.load_snapshot_payload_from_path(Path(path))
            self.assertIsNotNone(payload)
        finally:
            import os

            os.unlink(path)

    def test_empty_file_raises(self):
        svc, *_ = _make_service()
        from pathlib import Path
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("   ")
            path = f.name
        try:
            with self.assertRaises(ValueError):
                svc.load_snapshot_payload_from_path(Path(path))
        finally:
            import os

            os.unlink(path)

    def test_invalid_json_raises(self):
        svc, *_ = _make_service()
        from pathlib import Path
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("{not valid json")
            path = f.name
        try:
            with self.assertRaises(ValueError):
                svc.load_snapshot_payload_from_path(Path(path))
        finally:
            import os

            os.unlink(path)


class TestValidateSnapshotQuality(unittest.TestCase):
    def test_none_snapshot_returns_invalid(self):
        svc, *_ = _make_service()
        result = svc.validate_snapshot_quality(None)
        self.assertFalse(result["valid"])

    def test_valid_snapshot_with_matching_counts(self):
        svc, *_ = _make_service()
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        snap = MagicMock()
        snap.payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        snap.metadata = {}
        svc.build_live_payload = MagicMock(
            return_value=SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        )
        result = svc.validate_snapshot_quality(snap)
        self.assertTrue(result["valid"])

    def test_mismatched_table_count_invalid(self):
        svc, *_ = _make_service()
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        snap = MagicMock()
        snap.payload = SchemaSnapshotPayload(tables=[MagicMock()], views=[], indexes=[])
        snap.metadata = {}
        svc.build_live_payload = MagicMock(
            return_value=SchemaSnapshotPayload(tables=[], views=[], indexes=[])
        )
        result = svc.validate_snapshot_quality(snap)
        self.assertFalse(result["valid"])

    def test_build_live_payload_error(self):
        svc, *_ = _make_service()
        snap = MagicMock()
        snap.payload = MagicMock()
        svc.build_live_payload = MagicMock(side_effect=Exception("DB error"))
        result = svc.validate_snapshot_quality(snap)
        self.assertFalse(result["valid"])
