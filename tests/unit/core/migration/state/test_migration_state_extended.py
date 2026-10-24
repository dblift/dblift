"""Tests for core/migration/state/migration_state.py."""

import datetime
import unittest
from types import SimpleNamespace


class TestChecksumChange(unittest.TestCase):
    def test_to_dict(self):
        from dblift.core.migration.state.migration_state import ChecksumChange

        cc = ChecksumChange("V1__test.sql", "old_checksum", "new_checksum")
        d = cc.to_dict()
        self.assertEqual(d["script"], "V1__test.sql")
        self.assertEqual(d["previous"], "old_checksum")
        self.assertEqual(d["current"], "new_checksum")

    def test_to_dict_none_values(self):
        from dblift.core.migration.state.migration_state import ChecksumChange

        cc = ChecksumChange("V1.sql", None, None)
        d = cc.to_dict()
        self.assertIsNone(d["previous"])
        self.assertIsNone(d["current"])


class TestMigrationEntry(unittest.TestCase):
    def test_basic_to_dict(self):
        from dblift.core.migration.state.migration_state import MigrationEntry

        entry = MigrationEntry(
            script="V1__test.sql",
            version="1",
            description="test",
            type="SQL",
            status="SUCCESS",
            checksum="abc123",
        )
        d = entry.to_dict()
        self.assertEqual(d["script"], "V1__test.sql")
        self.assertEqual(d["version"], "1")
        self.assertEqual(d["status"], "SUCCESS")

    def test_format_datetime_none(self):
        from dblift.core.migration.state.migration_state import MigrationEntry

        result = MigrationEntry._format_datetime(None)
        self.assertIsNone(result)

    def test_format_datetime_string(self):
        from dblift.core.migration.state.migration_state import MigrationEntry

        result = MigrationEntry._format_datetime("2024-01-15 10:30:00")
        self.assertIsInstance(result, str)

    def test_format_datetime_object(self):
        from dblift.core.migration.state.migration_state import MigrationEntry

        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        result = MigrationEntry._format_datetime(dt)
        self.assertIsInstance(result, str)

    def test_from_migration_basic(self):
        from dblift.core.migration.state.migration_state import MigrationEntry

        m = SimpleNamespace(
            script_name="V1__test.sql",
            version="1",
            description="test",
            type="SQL",
            success=True,
            checksum="abc",
            installed_on=None,
            installed_by="user",
            execution_time=100,
        )
        entry = MigrationEntry.from_migration(m, "SUCCESS")
        self.assertEqual(entry.script, "V1__test.sql")
        self.assertEqual(entry.status, "SUCCESS")

    def test_from_migration_no_status(self):
        from dblift.core.migration.state.migration_state import MigrationEntry

        m = SimpleNamespace(
            script_name="V2.sql",
            version="2",
            description=None,
            type=None,
            success=False,
            checksum=None,
            installed_on=None,
            installed_by=None,
            execution_time=0,
        )
        entry = MigrationEntry.from_migration(m)
        self.assertEqual(entry.script, "V2.sql")


class TestMigrationState(unittest.TestCase):
    def _make(self):
        from dblift.core.migration.state.migration_state import MigrationState

        return MigrationState()

    def test_default_has_no_failures(self):
        state = self._make()
        self.assertFalse(state.has_failures)  # property

    def test_default_has_no_pending(self):
        state = self._make()
        self.assertFalse(state.has_pending)  # property

    def test_checksum_change_count_empty(self):
        state = self._make()
        self.assertEqual(state.checksum_change_count, 0)  # property

    def test_has_failures_with_failed(self):
        from dblift.core.migration.state.migration_state import MigrationEntry, MigrationState

        state = MigrationState()
        failed = MigrationEntry("V1.sql", "1", "test", "SQL", "FAILED", None)
        state.failed.append(failed)  # attribute is 'failed' not 'failed_migrations'
        self.assertTrue(state.has_failures)

    def test_has_pending_with_eligible_catalog_record(self):
        from dblift.core.migration.state.migration_state import (
            CatalogMigration,
            MigrationEligibility,
            MigrationState,
        )

        state = MigrationState(
            catalog=(
                CatalogMigration(
                    SimpleNamespace(script_name="V2.sql", version="2"),
                    MigrationEligibility.PENDING,
                ),
            )
        )
        self.assertTrue(state.has_pending)

    def test_to_dict_keys(self):
        state = self._make()
        d = state.to_dict()
        self.assertIn("pending", d)
        self.assertIn("applied", d)
        self.assertIn("failed", d)

    def test_copy_is_independent(self):
        from dblift.core.migration.state.migration_state import MigrationEntry, MigrationState

        state = MigrationState()
        entry = MigrationEntry("V1.sql", "1", "test", "SQL", "SUCCESS", None)
        state.applied.append(entry)
        copy = state.copy()
        self.assertEqual(len(copy.applied), 1)
        # Modify original — copy should not be affected
        state.applied.append(entry)
        self.assertEqual(len(copy.applied), 1)

    def test_grouped_catalog_copy_preserves_order_and_independent_containers(self):
        from dblift.core.migration.state.migration_state import MigrationState

        migration = SimpleNamespace(script_name="V1__a.sql")
        state = MigrationState(grouped_objects={"UNDO_SQL": [], "SQL": [migration]})
        copied = state.copy()
        self.assertEqual(list(copied.grouped_objects), ["UNDO_SQL", "SQL"])
        self.assertIs(copied.grouped_objects["SQL"][0], migration)
        state.grouped_objects["SQL"].clear()
        state.grouped_objects.clear()
        self.assertEqual(copied.grouped_objects, {"UNDO_SQL": [], "SQL": [migration]})
        self.assertNotIn("grouped_objects", copied.to_dict())
        self.assertNotIn("grouped_objects", repr(copied))

    def test_grouped_catalog_copy_distinguishes_missing_and_empty(self):
        from dblift.core.migration.state.migration_state import MigrationState

        self.assertIsNone(MigrationState().copy().grouped_objects)
        state = MigrationState(grouped_objects={})
        self.assertEqual(state.copy().grouped_objects, {})
        self.assertIsNot(state.copy().grouped_objects, state.grouped_objects)

    def test_checksum_change_count(self):
        from dblift.core.migration.state.migration_state import ChecksumChange, MigrationState

        state = MigrationState()
        state.checksum_changes = [
            ChecksumChange("V1.sql", "old", "new"),
            ChecksumChange("V2.sql", "a", "b"),
        ]
        self.assertEqual(state.checksum_change_count, 2)

    def test_executable_pending_objects_returns_only_eligible_records(self):
        from dblift.core.migration.state.migration_state import (
            CatalogMigration,
            MigrationEligibility,
            MigrationState,
        )

        below = SimpleNamespace(script_name="V1__a.sql")
        pending_obj = SimpleNamespace(script_name="V3__b.sql")
        above = SimpleNamespace(script_name="V5__c.sql")
        available = SimpleNamespace(script_name="U3__b.sql")
        state = MigrationState(
            catalog=(
                CatalogMigration(below, MigrationEligibility.BELOW_BASELINE),
                CatalogMigration(pending_obj, MigrationEligibility.PENDING),
                CatalogMigration(above, MigrationEligibility.ABOVE_TARGET),
                CatalogMigration(available, MigrationEligibility.UNDO_AVAILABLE),
            )
        )

        self.assertEqual(state.executable_pending_objects(), [pending_obj])
        self.assertTrue(state.has_pending)

    def test_has_pending_false_when_only_non_executable_statuses(self):
        from dblift.core.migration.state.migration_state import (
            CatalogMigration,
            MigrationEligibility,
            MigrationState,
        )

        state = MigrationState(
            catalog=(
                CatalogMigration(
                    SimpleNamespace(script_name="V1__a.sql"), MigrationEligibility.BELOW_BASELINE
                ),
                CatalogMigration(
                    SimpleNamespace(script_name="V5__c.sql"), MigrationEligibility.ABOVE_TARGET
                ),
                CatalogMigration(
                    SimpleNamespace(script_name="U3__b.sql"), MigrationEligibility.UNDO_AVAILABLE
                ),
            )
        )

        self.assertFalse(state.has_pending)
        self.assertEqual(state.executable_pending_objects(), [])
