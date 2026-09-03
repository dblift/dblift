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

    def test_has_pending_with_pending(self):
        from dblift.core.migration.state.migration_state import MigrationEntry, MigrationState

        state = MigrationState()
        pending = MigrationEntry("V2.sql", "2", "test", "SQL", "Pending", None)
        state.pending.append(pending)
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

    def test_checksum_change_count(self):
        from dblift.core.migration.state.migration_state import ChecksumChange, MigrationState

        state = MigrationState()
        state.checksum_changes = [
            ChecksumChange("V1.sql", "old", "new"),
            ChecksumChange("V2.sql", "a", "b"),
        ]
        self.assertEqual(state.checksum_change_count, 2)

    def _entry(self, script, version, status, type_="SQL"):
        from dblift.core.migration.state.migration_state import MigrationEntry

        return MigrationEntry(script, version, "test", type_, status, None)

    def test_executable_pending_objects_returns_only_pending_status(self):
        from dblift.core.migration.state.migration_display_state import MigrationDisplayState
        from dblift.core.migration.state.migration_state import MigrationState

        below = SimpleNamespace(script_name="V1__a.sql")
        pending_obj = SimpleNamespace(script_name="V3__b.sql")
        above = SimpleNamespace(script_name="V5__c.sql")
        available = SimpleNamespace(script_name="U3__b.sql")
        state = MigrationState(
            pending=[
                self._entry("V1__a.sql", "1", MigrationDisplayState.BELOW_BASELINE.value),
                self._entry("V3__b.sql", "3", MigrationDisplayState.PENDING.value),
                self._entry("V5__c.sql", "5", MigrationDisplayState.ABOVE_TARGET.value),
                self._entry("U3__b.sql", "3", MigrationDisplayState.AVAILABLE.value, "UNDO_SQL"),
            ],
            pending_objects=[below, pending_obj, above, available],
        )

        self.assertEqual(state.executable_pending_objects(), [pending_obj])
        self.assertTrue(state.has_pending)

    def test_has_pending_false_when_only_non_executable_statuses(self):
        from dblift.core.migration.state.migration_display_state import MigrationDisplayState
        from dblift.core.migration.state.migration_state import MigrationState

        state = MigrationState(
            pending=[
                self._entry("V1__a.sql", "1", MigrationDisplayState.BELOW_BASELINE.value),
                self._entry("V5__c.sql", "5", MigrationDisplayState.ABOVE_TARGET.value),
                self._entry("U3__b.sql", "3", MigrationDisplayState.AVAILABLE.value, "UNDO_SQL"),
            ],
            pending_objects=[
                SimpleNamespace(script_name="V1__a.sql"),
                SimpleNamespace(script_name="V5__c.sql"),
                SimpleNamespace(script_name="U3__b.sql"),
            ],
        )

        self.assertFalse(state.has_pending)
        self.assertEqual(state.executable_pending_objects(), [])
