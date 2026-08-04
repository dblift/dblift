"""BUG-01: post-lock history re-read filters concurrently-applied migrations.

Verifies ``MigrateCommand._filter_already_applied`` drops VERSIONED pending
migrations whose ``(version, type)`` matches a SUCCESSFUL applied history
row, and REPEATABLE pending migrations whose script_name matches a
SUCCESSFUL applied history row with the same checksum (see
``test_migrate_command_repeatable_lock_race.py`` for the checksum-based
repeatable re-check added for issue #811). Failed rows must NOT cause a
skip.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.migration.commands.migrate_command import MigrateCommand
from core.migration.migration import AppliedMigration, MigrationType


def _cmd(log=None):
    _log = log or MagicMock()
    return MigrateCommand(
        config=MagicMock(),
        log=_log,
        provider=MagicMock(),
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=None,
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )


def _pending(version, script_name, type_=MigrationType.SQL):
    return SimpleNamespace(script_name=script_name, version=version, type=type_)


def _applied(version, script_name, type_=MigrationType.SQL, success=True, installed_rank=1):
    return AppliedMigration(
        script_name=script_name,
        version=version,
        description=None,
        type=type_,
        checksum=None,
        success=success,
        installed_rank=installed_rank,
    )


class TestFilterAlreadyApplied(unittest.TestCase):
    def test_all_pending_already_applied_returns_empty(self):
        cmd = _cmd()
        pending = [_pending("1", "V1__a.sql"), _pending("2", "V2__b.sql")]
        applied = [_applied("1", "V1__a.sql"), _applied("2", "V2__b.sql")]
        self.assertEqual(cmd._filter_already_applied(pending, applied), [])

    def test_subset_applied_returns_unapplied_subset(self):
        cmd = _cmd()
        pending = [_pending("1", "V1__a.sql"), _pending("2", "V2__b.sql")]
        applied = [_applied("1", "V1__a.sql")]
        out = cmd._filter_already_applied(pending, applied)
        self.assertEqual([m.version for m in out], ["2"])

    def test_no_overlap_returns_pending_unchanged(self):
        cmd = _cmd()
        pending = [_pending("1", "V1__a.sql")]
        applied = [_applied("9", "V9__x.sql")]
        out = cmd._filter_already_applied(pending, applied)
        self.assertEqual([m.version for m in out], ["1"])

    def test_failed_applied_row_does_not_skip(self):
        cmd = _cmd()
        pending = [_pending("1", "V1__a.sql")]
        applied = [_applied("1", "V1__a.sql", success=False)]
        out = cmd._filter_already_applied(pending, applied)
        self.assertEqual(len(out), 1)

    def test_undone_versioned_row_does_not_skip_reapply(self):
        cmd = _cmd()
        pending = [_pending("1", "V1__a.sql")]
        applied = [
            _applied("1", "V1__a.sql", installed_rank=1),
            _applied("1", "U1__a.sql", type_=MigrationType.UNDO_SQL, installed_rank=2),
        ]

        out = cmd._filter_already_applied(pending, applied)

        self.assertEqual(len(out), 1)

    def test_reapplied_after_undo_skips_again(self):
        cmd = _cmd()
        pending = [_pending("1", "V1__a.sql")]
        applied = [
            _applied("1", "V1__a.sql", installed_rank=1),
            _applied("1", "U1__a.sql", type_=MigrationType.UNDO_SQL, installed_rank=2),
            _applied("1", "V1__a.sql", installed_rank=3),
        ]

        out = cmd._filter_already_applied(pending, applied)

        self.assertEqual(out, [])

    def test_repeatable_without_checksum_not_filtered(self):
        cmd = _cmd()
        pending = [
            _pending(None, "R__view.sql", type_=MigrationType.REPEATABLE),
        ]
        # Repeatable history rows would have version=NULL — should not match
        # on the versioned (version, type) key. Neither side carries a
        # checksum here, so the repeatable checksum re-check (issue #811)
        # can't match either — it must not be skipped.
        applied = [
            AppliedMigration(
                script_name="R__view.sql",
                version=None,
                description=None,
                type=MigrationType.REPEATABLE,
                checksum=None,
                success=True,
            )
        ]
        out = cmd._filter_already_applied(pending, applied)
        self.assertEqual(len(out), 1)

    def test_skip_emits_info_log(self):
        log = MagicMock()
        cmd = _cmd(log=log)
        pending = [_pending("1", "V1__a.sql")]
        applied = [_applied("1", "V1__a.sql")]
        cmd._filter_already_applied(pending, applied)
        info_calls = " ".join(str(c) for c in log.info.call_args_list)
        self.assertIn("V1__a.sql", info_calls)
        self.assertIn("concurrent", info_calls)


if __name__ == "__main__":
    unittest.main()
