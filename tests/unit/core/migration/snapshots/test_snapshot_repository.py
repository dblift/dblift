"""Tests for core/migration/snapshots/schema_snapshot_repository.py."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _make_provider(dialect="postgresql"):
    provider = MagicMock()
    provider.config.database.type = dialect
    provider.config.snapshot_table = "dblift_schema_snapshot"
    provider.get_normalized_object_name.side_effect = lambda name: name.lower()
    provider.get_schema_qualified_name.side_effect = lambda s, t: f"{s}.{t}"
    provider.get_parameter_placeholders.return_value = "?, ?, ?, ?"
    return provider


def _make_repo(dialect="postgresql", schema="public"):
    from core.migration.snapshots.schema_snapshot_repository import SchemaSnapshotRepository

    provider = _make_provider(dialect)
    return SchemaSnapshotRepository(provider=provider, schema=schema), provider


def _make_payload():
    from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

    payload = SchemaSnapshotPayload(tables=[], views=[], indexes=[])
    return payload


class TestSchemaSnapshotRepositoryInit(unittest.TestCase):
    def test_stores_schema(self):
        repo, _ = _make_repo()
        self.assertEqual(repo.schema, "public")

    def test_table_name_from_config(self):
        repo, _ = _make_repo()
        self.assertIsNotNone(repo.table_name)

    def test_logger_default(self):
        repo, _ = _make_repo()
        self.assertIsNotNone(repo.logger)


class TestSnapshotRepositoryQualifiedName(unittest.TestCase):
    def test_non_oracle_uses_provider(self):
        repo, provider = _make_repo(dialect="postgresql")
        name = repo._get_snapshot_table_qualified_name()
        self.assertIn("public", name.lower())

    def test_oracle_uses_uppercase(self):
        repo, _ = _make_repo(dialect="oracle", schema="myschema")
        name = repo._get_snapshot_table_qualified_name()
        self.assertIn("MYSCHEMA", name)


class TestSnapshotRepositoryEnsureConnection(unittest.TestCase):
    def test_ensure_connection_no_error(self):
        repo, provider = _make_repo()
        # Should not raise
        repo._ensure_valid_connection()

    def test_ensure_connection_suppresses_error(self):
        from db.provider_capabilities import ensure_provider_connection

        repo, provider = _make_repo()
        with patch(
            "core.migration.snapshots.schema_snapshot_repository.ensure_provider_connection",
            side_effect=Exception("conn err"),
        ):
            repo._ensure_valid_connection()  # no raise


class TestSnapshotRepositoryEnsureTable(unittest.TestCase):
    def test_ensure_table_calls_provider(self):
        repo, provider = _make_repo()
        repo.ensure_table()
        provider.create_snapshot_table_if_not_exists.assert_called_once()


class TestSnapshotRepositorySave(unittest.TestCase):
    def test_save_snapshot_success(self):
        repo, provider = _make_repo()
        payload = _make_payload()
        provider.table_exists.return_value = True
        provider.execute_statement.return_value = None
        snapshot = repo.save_snapshot(payload)
        self.assertIsNotNone(snapshot.snapshot_id)
        provider.execute_statement.assert_called()

    def test_save_snapshot_with_version(self):
        repo, provider = _make_repo()
        payload = _make_payload()
        provider.table_exists.return_value = True
        snapshot = repo.save_snapshot(payload, migration_version="1.0")
        self.assertIn("last_version", snapshot.payload.metadata.get("migration", {}))

    def test_save_snapshot_with_rank(self):
        repo, provider = _make_repo()
        payload = _make_payload()
        provider.table_exists.return_value = True
        snapshot = repo.save_snapshot(payload, installed_rank=5)
        self.assertEqual(snapshot.payload.metadata["migration"]["installed_rank"], 5)

    def test_save_snapshot_rollback_on_error(self):
        repo, provider = _make_repo()
        payload = _make_payload()
        provider.table_exists.return_value = True
        provider.execute_statement.side_effect = Exception("DB error")
        with self.assertRaises(Exception):
            repo.save_snapshot(payload)
        provider.rollback_transaction.assert_called()

    def test_save_snapshot_commits_transaction(self):
        repo, provider = _make_repo()
        payload = _make_payload()
        provider.table_exists.return_value = True
        provider.execute_statement.return_value = None
        repo.save_snapshot(payload)
        provider.commit_transaction.assert_called()

    def test_save_with_autocommit_false_rolls_back_existing(self):
        repo, provider = _make_repo()
        payload = _make_payload()
        provider.table_exists.return_value = True
        # Simulate connection with autocommit=False
        provider.connection = MagicMock()
        provider.connection.getAutoCommit.return_value = False
        repo.save_snapshot(payload)
        provider.connection.rollback.assert_called()


class TestSnapshotRepositorySnapshotTableExists(unittest.TestCase):
    def test_returns_true_when_table_exists(self):
        repo, provider = _make_repo()
        provider.table_exists.return_value = True
        self.assertTrue(repo._snapshot_table_exists())

    def test_returns_false_when_not_exists(self):
        repo, provider = _make_repo()
        provider.table_exists.return_value = False
        self.assertFalse(repo._snapshot_table_exists())


class TestSnapshotRepositoryGetLatest(unittest.TestCase):
    def test_returns_none_when_no_table(self):
        repo, provider = _make_repo()
        provider.table_exists.return_value = False
        self.assertIsNone(repo.get_latest_snapshot())

    def test_returns_none_when_no_rows(self):
        repo, provider = _make_repo()
        provider.table_exists.return_value = True
        provider.execute_query.return_value = []
        self.assertIsNone(repo.get_latest_snapshot())

    def test_returns_snapshot_from_row(self):
        from unittest.mock import patch

        from core.migration.snapshots.schema_snapshot import SchemaSnapshot

        repo, provider = _make_repo()
        provider.table_exists.return_value = True
        import uuid

        sid = str(uuid.uuid4())
        mock_snap = MagicMock(spec=SchemaSnapshot)
        provider.execute_query.return_value = [{"snapshot_id": sid}]
        with patch.object(SchemaSnapshot, "from_record", return_value=mock_snap):
            result = repo.get_latest_snapshot()
        self.assertIs(result, mock_snap)


class TestSnapshotRepositoryListSnapshots(unittest.TestCase):
    def test_returns_empty_when_no_table(self):
        repo, provider = _make_repo()
        provider.table_exists.return_value = False
        self.assertEqual(repo.list_snapshots(), [])

    def test_applies_limit(self):
        import uuid
        from unittest.mock import patch

        from core.migration.snapshots.schema_snapshot import SchemaSnapshot

        repo, provider = _make_repo()
        provider.table_exists.return_value = True
        rows = [{"snapshot_id": str(uuid.uuid4())} for _ in range(3)]
        provider.execute_query.return_value = rows
        mock_snap = MagicMock(spec=SchemaSnapshot)
        with patch.object(SchemaSnapshot, "from_record", return_value=mock_snap):
            result = repo.list_snapshots(limit=2)
        self.assertEqual(len(result), 2)


class TestSnapshotRepositoryDeleteOld(unittest.TestCase):
    def test_delete_none_when_within_limit(self):
        repo, provider = _make_repo()
        provider.table_exists.return_value = True
        import datetime as dt
        import json
        import uuid

        def make_row(ts):
            return {
                "snapshot_id": str(uuid.uuid4()),
                "captured_at": ts,
                "checksum": "x",
                "model_data": json.dumps(
                    {"tables": [], "views": [], "indexes": [], "metadata": {}}
                ),
            }

        provider.execute_query.return_value = [make_row("2024-01-01"), make_row("2024-01-02")]
        count = repo.delete_old_snapshots(5)
        self.assertEqual(count, 0)

    def test_delete_zero_deletes_all(self):
        repo, provider = _make_repo()
        provider.table_exists.return_value = True
        provider.execute_statement.return_value = None
        repo.delete_old_snapshots(0)
        provider.execute_statement.assert_called()
