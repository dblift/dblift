"""Regression tests for migration-type comparisons in the migration validator.

``Migration.type`` is always a :class:`MigrationType` member — ``Migration.__init__``
rejects anything else — so comparing it against a bare type name such as
``"REPEATABLE"`` is permanently ``False``. These tests pin the *observable*
validation outcomes that those comparisons were meant to produce.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_validator(dialect="postgresql"):
    from core.sql_validator.migration_validator import MigrationValidator

    sm = MagicMock()
    hm = MagicMock()
    hm.schema = "public"
    hm.history_table = "dblift_schema_history"
    hm.normalized_history_table = "dblift_schema_history"
    hm.provider = MagicMock()
    hm.provider.config.database.type = dialect
    hm.provider.config.strict_mode = False
    log = MagicMock()
    with patch("core.sql_validator.migration_validator.SqlAnalyzer"):
        v = MigrationValidator(script_manager=sm, history_manager=hm, log=log)
    return v, sm, hm, log


def _script(mtype, name, version=None, checksum=100):
    return SimpleNamespace(
        type=mtype, script_name=name, version=version, checksum=checksum, path=None, tags=[]
    )


def _history_row(mtype, name, version=None, checksum=100, success=True, execution_time=0, rank=1):
    return SimpleNamespace(
        type=mtype,
        script_name=name,
        version=version,
        checksum=checksum,
        success=success,
        execution_time=execution_time,
        installed_rank=rank,
        tags=[],
        path=None,
    )


class TestFailedRepeatableFiltering(unittest.TestCase):
    """``_validate_failed_migrations`` must not block on an already-scheduled repeatable."""

    def _run(self, scripts, history):
        v, sm, hm, _ = _make_validator()
        hm.has_history_table = True
        sm.has_script_changed.return_value = False
        hm.get_applied_migrations.return_value = history
        return v.validate_resolved_migrations(scripts)

    def test_failed_repeatable_scheduled_for_reapply_does_not_block_validation(self):
        """A repeatable that failed but has since changed is reapplied, not a blocking failure."""
        from core.migration.migration import MigrationType

        result = self._run(
            scripts=[
                _script(MigrationType.SQL, "V1__a.sql", version="1", checksum=100),
                _script(MigrationType.REPEATABLE, "R__x.sql", checksum=200),
            ],
            history=[
                _history_row(MigrationType.SQL, "V1__a.sql", version="1", checksum=100, rank=1),
                _history_row(
                    MigrationType.REPEATABLE,
                    "R__x.sql",
                    checksum=999,
                    success=False,
                    execution_time=5,
                    rank=2,
                ),
            ],
        )
        self.assertTrue(
            result.success,
            f"expected success, got error_message={result.error_message!r} issues={result.issues!r}",
        )
        self.assertEqual(result.issues, [])

    def test_scheduled_repeatable_is_excluded_from_the_failed_migration_list(self):
        """Only the genuinely blocking failure is reported, not the scheduled repeatable."""
        from core.migration.migration import MigrationType

        result = self._run(
            scripts=[
                _script(MigrationType.SQL, "V1__a.sql", version="1", checksum=100),
                _script(MigrationType.SQL, "V2__b.sql", version="2", checksum=300),
                _script(MigrationType.REPEATABLE, "R__x.sql", checksum=200),
            ],
            history=[
                _history_row(MigrationType.SQL, "V1__a.sql", version="1", checksum=100, rank=1),
                _history_row(
                    MigrationType.REPEATABLE,
                    "R__x.sql",
                    checksum=999,
                    success=False,
                    execution_time=5,
                    rank=2,
                ),
                _history_row(
                    MigrationType.SQL,
                    "V2__b.sql",
                    version="2",
                    checksum=300,
                    success=False,
                    execution_time=5,
                    rank=3,
                ),
            ],
        )
        self.assertFalse(result.success)
        self.assertIn("Found 1 failed migration(s): V2__b.sql", result.error_message)
        self.assertNotIn("R__x.sql", result.error_message)

    def test_unscheduled_failed_repeatable_reports_the_fix_the_script_error(self):
        """A repeatable that failed without executing and has not changed keeps its own message."""
        from core.migration.migration import MigrationType

        result = self._run(
            scripts=[
                _script(MigrationType.SQL, "V1__a.sql", version="1", checksum=100),
                _script(MigrationType.REPEATABLE, "R__x.sql", checksum=200),
            ],
            history=[
                _history_row(MigrationType.SQL, "V1__a.sql", version="1", checksum=100, rank=1),
                _history_row(
                    MigrationType.REPEATABLE,
                    "R__x.sql",
                    checksum=200,
                    success=False,
                    execution_time=0,
                    rank=2,
                ),
            ],
        )
        self.assertFalse(result.success)
        self.assertIn("previously failed and has not changed", result.error_message)
        self.assertNotIn("Found 1 failed migration(s)", result.error_message)


class TestCallbackHistoryRowsAreNotFatal(unittest.TestCase):
    """A CALLBACK row in history must not abort validation.

    ``MigrationStateManager._build_history_facts`` deliberately accepts a
    successful CALLBACK history row and records the script as executed, so the
    validator must not treat the same row as a fatal integrity error.
    """

    def test_callback_row_in_history_does_not_fail_validation(self):
        from core.migration.migration import MigrationType

        v, sm, hm, _ = _make_validator()
        hm.has_history_table = True
        sm.has_script_changed.return_value = False
        hm.get_applied_migrations.return_value = [
            _history_row(MigrationType.CALLBACK, "afterMigrate__log.sql", version=None)
        ]
        result = v.validate_resolved_migrations(
            [_script(MigrationType.SQL, "V1__a.sql", version="1")]
        )
        self.assertTrue(result.success, f"error_message={result.error_message!r}")

    def test_callback_row_in_history_does_not_fail_validate_migrations(self):
        import tempfile
        from pathlib import Path

        from core.migration.migration import MigrationType

        v, sm, hm, _ = _make_validator()
        hm.has_history_table = True
        sm.has_script_changed.return_value = False
        hm.get_applied_migrations.return_value = [
            _history_row(MigrationType.CALLBACK, "afterMigrate__log.sql", version=None)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            sm.get_migration_scripts.return_value = [
                _script(MigrationType.SQL, "V1__a.sql", version="1")
            ]
            result = v.validate_migrations(Path(tmpdir))
        self.assertTrue(result.success, f"error_message={result.error_message!r}")


if __name__ == "__main__":
    unittest.main()
