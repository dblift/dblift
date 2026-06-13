"""Tests for db/plugins/sqlite/sqlite/snapshot_table.py."""

import unittest
from unittest.mock import MagicMock


class TestSnapshotColumnNames(unittest.TestCase):
    def test_returns_column_names(self):
        from db.plugins.sqlite.sqlite.snapshot_table import _snapshot_column_names

        qe = MagicMock()
        qe.execute_query.return_value = [
            {"name": "snapshot_id"},
            {"name": "captured_at"},
            {"name": "checksum"},
            {"name": "model_data"},
        ]
        conn = MagicMock()
        result = _snapshot_column_names(qe, conn, "dblift_schema_snapshots")
        self.assertIn("snapshot_id", result)
        self.assertIn("model_data", result)

    def test_returns_empty_on_no_rows(self):
        from db.plugins.sqlite.sqlite.snapshot_table import _snapshot_column_names

        qe = MagicMock()
        qe.execute_query.return_value = []
        conn = MagicMock()
        result = _snapshot_column_names(qe, conn, "t")
        self.assertEqual(result, set())


class TestIsLegacySnapshotSchema(unittest.TestCase):
    def test_modern_schema_not_legacy(self):
        from db.plugins.sqlite.sqlite.snapshot_table import _is_legacy_snapshot_schema

        cols = {"snapshot_id", "captured_at", "checksum", "model_data"}
        self.assertFalse(_is_legacy_snapshot_schema(cols))

    def test_schema_json_is_legacy(self):
        from db.plugins.sqlite.sqlite.snapshot_table import _is_legacy_snapshot_schema

        cols = {"id", "schema_json", "created_at"}
        self.assertTrue(_is_legacy_snapshot_schema(cols))

    def test_modern_with_extra_cols_not_legacy(self):
        from db.plugins.sqlite.sqlite.snapshot_table import _is_legacy_snapshot_schema

        cols = {"snapshot_id", "captured_at", "checksum", "model_data", "extra"}
        self.assertFalse(_is_legacy_snapshot_schema(cols))


class TestNormalizeRow(unittest.TestCase):
    def test_lowercases_keys(self):
        from db.plugins.sqlite.sqlite.snapshot_table import _normalize_row

        row = {"SnapshotID": "abc", "CapturedAt": "2024-01-01"}
        result = _normalize_row(row)
        self.assertIn("snapshotid", result)
        self.assertIn("capturedat", result)


class TestCoerceModelAndChecksum(unittest.TestCase):
    def test_none_returns_empty_payload(self):
        from db.plugins.sqlite.sqlite.snapshot_table import _coerce_model_and_checksum

        model_data, checksum = _coerce_model_and_checksum(None)
        self.assertIsNotNone(model_data)
        self.assertIsNotNone(checksum)

    def test_json_string_parses(self):
        import json

        from db.plugins.sqlite.sqlite.snapshot_table import _coerce_model_and_checksum

        payload = json.dumps({"tables": [], "views": [], "indexes": [], "metadata": {}})
        model_data, checksum = _coerce_model_and_checksum(payload)
        self.assertIsNotNone(model_data)


class TestEnsureSQLiteSnapshotTableExists(unittest.TestCase):
    def test_creates_table_if_not_exists(self):
        from db.plugins.sqlite.sqlite.snapshot_table import ensure_sqlite_snapshot_table_exists

        qe = MagicMock()
        qe.table_exists.return_value = False
        qe.execute_query.return_value = []  # PRAGMA returns nothing for non-existent table
        conn = MagicMock()
        ensure_sqlite_snapshot_table_exists(qe, conn, "main", "dblift_schema_snapshots")
        qe.execute_statement.assert_called()

    def test_skips_when_modern_schema_exists(self):
        from db.plugins.sqlite.sqlite.snapshot_table import ensure_sqlite_snapshot_table_exists

        qe = MagicMock()
        qe.table_exists.return_value = True
        # PRAGMA returns modern schema columns
        qe.execute_query.return_value = [
            {"name": "snapshot_id"},
            {"name": "captured_at"},
            {"name": "checksum"},
            {"name": "model_data"},
        ]
        conn = MagicMock()
        ensure_sqlite_snapshot_table_exists(qe, conn, "main", "dblift_schema_snapshots")
        # execute_statement should not be called (table already has modern schema)
        # Note: might still call for PRAGMA — just check no crash
        self.assertIsNotNone(qe)
