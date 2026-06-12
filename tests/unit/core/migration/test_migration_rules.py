"""Tests for core/migration/rules/migration_rules.py."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock


class TestMigrationRulesIsSuccess(unittest.TestCase):
    def _make_rules(self):
        from core.migration.rules.migration_rules import MigrationRules

        return MigrationRules(logger=MagicMock())

    def test_is_success_true_string(self):
        rules = self._make_rules()
        m = SimpleNamespace(success="1")
        self.assertTrue(rules.is_success(m))

    def test_is_success_true_bool(self):
        rules = self._make_rules()
        m = SimpleNamespace(success=True)
        self.assertTrue(rules.is_success(m))

    def test_is_success_false(self):
        rules = self._make_rules()
        m = SimpleNamespace(success=False)
        self.assertFalse(rules.is_success(m))

    def test_is_success_no_attr(self):
        rules = self._make_rules()
        self.assertFalse(rules.is_success(object()))


class TestMigrationRulesShouldUndoVersion(unittest.TestCase):
    def _make_rules(self):
        from core.migration.rules.migration_rules import MigrationRules

        return MigrationRules(logger=MagicMock())

    def _make_migration(self, version, mtype, success=True, rank=1):
        m = SimpleNamespace(
            version=version,
            type=mtype,
            success="1" if success else "0",
            installed_rank=rank,
        )
        return m

    def test_empty_list_can_undo(self):
        rules = self._make_rules()
        can, msg = rules.should_undo_version("1.0", [])
        self.assertTrue(can)
        self.assertEqual(msg, "")

    def test_versioned_only_can_undo(self):
        rules = self._make_rules()
        m = self._make_migration("1.0", "SQL", rank=1)
        can, msg = rules.should_undo_version("1.0", [m])
        self.assertTrue(can)

    def test_undone_without_reapply_cannot_undo(self):
        rules = self._make_rules()
        applied = self._make_migration("1.0", "SQL", rank=1)
        undone = self._make_migration("1.0", "UNDO_SQL", rank=2)
        can, msg = rules.should_undo_version("1.0", [applied, undone])
        self.assertFalse(can)
        self.assertIn("already been undone", msg)

    def test_undone_reapplied_can_undo_again(self):
        rules = self._make_rules()
        applied1 = self._make_migration("1.0", "SQL", rank=1)
        undone = self._make_migration("1.0", "UNDO_SQL", rank=2)
        applied2 = self._make_migration("1.0", "SQL", rank=3)
        can, msg = rules.should_undo_version("1.0", [applied1, undone, applied2])
        self.assertTrue(can)

    def test_next_version_suggested_when_already_undone(self):
        rules = self._make_rules()
        v1_applied = self._make_migration("1.0", "SQL", rank=1)
        v1_undone = self._make_migration("1.0", "UNDO_SQL", rank=2)
        v2_applied = self._make_migration("2.0", "SQL", rank=3)
        can, msg = rules.should_undo_version("1.0", [v1_applied, v1_undone, v2_applied])
        self.assertFalse(can)
        self.assertIn("2.0", msg)

    def test_no_other_version_to_undo(self):
        rules = self._make_rules()
        applied = self._make_migration("1.0", "SQL", rank=1)
        undone = self._make_migration("1.0", "UNDO_SQL", rank=2)
        can, msg = rules.should_undo_version("1.0", [applied, undone])
        self.assertFalse(can)
        self.assertIn("no other versions", msg.lower())

    def test_failed_migration_not_counted_as_success(self):
        rules = self._make_rules()
        failed = self._make_migration("1.0", "SQL", success=False, rank=1)
        can, msg = rules.should_undo_version("1.0", [failed])
        self.assertTrue(can)

    def test_different_version_not_affected(self):
        rules = self._make_rules()
        m = self._make_migration("2.0", "SQL", rank=1)
        can, msg = rules.should_undo_version("1.0", [m])
        self.assertTrue(can)


class TestCoreStatus(unittest.TestCase):
    def test_enum_values(self):
        from core.migration.rules.migration_rules import CoreMigrationStatus

        self.assertEqual(CoreMigrationStatus.SUCCESS.value, "SUCCESS")
        self.assertEqual(CoreMigrationStatus.FAILED.value, "FAILED")
        self.assertEqual(CoreMigrationStatus.PENDING.value, "PENDING")
        self.assertEqual(CoreMigrationStatus.BASELINE.value, "BASELINE")
