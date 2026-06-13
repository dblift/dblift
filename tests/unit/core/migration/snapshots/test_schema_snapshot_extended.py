"""Extended tests for core/migration/snapshots/schema_snapshot.py."""

import datetime
import json
import unittest
from unittest.mock import MagicMock


class TestSnapshotUtilFunctions(unittest.TestCase):
    def test_to_utc_naive_datetime(self):
        from core.migration.snapshots.schema_snapshot import _to_utc

        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        result = _to_utc(dt)
        self.assertIsNotNone(result.tzinfo)

    def test_to_utc_aware_datetime(self):
        from core.migration.snapshots.schema_snapshot import _to_utc

        dt = datetime.datetime(2024, 1, 15, 10, 30, 0, tzinfo=datetime.timezone.utc)
        result = _to_utc(dt)
        self.assertEqual(result.tzinfo, datetime.timezone.utc)

    def test_isoformat_ends_with_z(self):
        from core.migration.snapshots.schema_snapshot import _isoformat

        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        result = _isoformat(dt)
        self.assertTrue(result.endswith("Z"))

    def test_parse_iso_with_z(self):
        from core.migration.snapshots.schema_snapshot import _parse_iso

        result = _parse_iso("2024-01-15T10:30:00Z")
        self.assertIsInstance(result, datetime.datetime)

    def test_parse_iso_with_offset(self):
        from core.migration.snapshots.schema_snapshot import _parse_iso

        result = _parse_iso("2024-01-15T10:30:00+00:00")
        self.assertIsInstance(result, datetime.datetime)

    def test_json_default_datetime(self):
        from core.migration.snapshots.schema_snapshot import _json_default

        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        result = _json_default(dt)
        self.assertIsInstance(result, str)

    def test_json_default_other(self):
        from core.migration.snapshots.schema_snapshot import _json_default

        result = _json_default(42)
        self.assertEqual(result, "42")


class TestSchemaSnapshotPayload(unittest.TestCase):
    def _make(self):
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        return SchemaSnapshotPayload()

    def test_default_empty_lists(self):
        payload = self._make()
        self.assertEqual(payload.tables, [])
        self.assertEqual(payload.views, [])

    def test_from_dict(self):
        from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

        data = {"tables": [], "views": [], "indexes": [], "metadata": {"key": "val"}}
        payload = SchemaSnapshotPayload.from_dict(data)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.metadata.get("key"), "val")

    def test_to_dict(self):
        payload = self._make()
        d = payload.to_dict()
        self.assertIn("tables", d)
        self.assertIn("views", d)


class TestSchemaSnapshot(unittest.TestCase):
    def _make(self):
        import uuid

        from core.migration.snapshots.schema_snapshot import SchemaSnapshot, SchemaSnapshotPayload

        payload = SchemaSnapshotPayload()
        return SchemaSnapshot(
            snapshot_id=str(uuid.uuid4()),
            captured_at=datetime.datetime.now(datetime.timezone.utc),
            payload=payload,
        )

    def test_basic_creation(self):
        snap = self._make()
        self.assertIsNotNone(snap.snapshot_id)
        self.assertIsNotNone(snap.checksum)

    def test_to_record_values(self):
        snap = self._make()
        values = snap.to_record_values()
        self.assertIsInstance(values, (list, tuple))
        self.assertEqual(len(values), 4)  # snapshot_id, captured_at, checksum, model_data

    def test_to_record_values_uses_datetime_for_database_timestamp(self):
        import uuid

        from core.migration.snapshots.schema_snapshot import SchemaSnapshot, SchemaSnapshotPayload

        captured_at = datetime.datetime(
            2026, 6, 5, 16, 27, 55, 783877, tzinfo=datetime.timezone.utc
        )
        snap = SchemaSnapshot(
            snapshot_id=str(uuid.uuid4()),
            captured_at=captured_at,
            payload=SchemaSnapshotPayload(),
        )

        values = snap.to_record_values()

        self.assertIsInstance(values[1], datetime.datetime)
        self.assertEqual(values[1], captured_at.replace(tzinfo=None))

    def test_from_record(self):
        from core.migration.snapshots.schema_snapshot import SchemaSnapshot

        snap = self._make()
        values = snap.to_record_values()
        row = {
            "snapshot_id": values[0],
            "captured_at": values[1],
            "checksum": values[2],
            "model_data": values[3],
        }
        reconstructed = SchemaSnapshot.from_record(row)
        self.assertEqual(reconstructed.snapshot_id, snap.snapshot_id)


class TestComputePayloadChecksum(unittest.TestCase):
    def test_returns_string(self):
        from core.migration.snapshots.schema_snapshot import (
            SchemaSnapshotPayload,
            compute_payload_checksum,
        )

        payload = SchemaSnapshotPayload()
        checksum = compute_payload_checksum(payload)
        self.assertIsInstance(checksum, str)

    def test_deterministic(self):
        from core.migration.snapshots.schema_snapshot import (
            SchemaSnapshotPayload,
            compute_payload_checksum,
        )

        payload = SchemaSnapshotPayload()
        c1 = compute_payload_checksum(payload)
        c2 = compute_payload_checksum(payload)
        self.assertEqual(c1, c2)


class TestEncodeDecodePayload(unittest.TestCase):
    def test_roundtrip(self):
        from core.migration.snapshots.schema_snapshot import (
            SchemaSnapshotPayload,
            decode_payload,
            encode_payload,
        )

        payload = SchemaSnapshotPayload()
        payload.metadata["test"] = "value"
        encoded = encode_payload(payload)
        decoded = decode_payload(encoded)
        self.assertEqual(decoded.metadata.get("test"), "value")
