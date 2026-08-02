"""Extended tests for core/sql_validator/migration_validator.py."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_validator(dialect="postgresql"):
    from core.logger import NullLog
    from core.sql_validator.migration_validator import MigrationValidator

    sm = MagicMock()
    hm = MagicMock()
    hm.schema = "public"
    hm.history_table = "dblift_schema_history"
    hm.normalized_history_table = "dblift_schema_history"
    hm.provider = MagicMock()
    hm.provider.config.database.type = dialect
    log = MagicMock()
    with patch("core.sql_validator.migration_validator.SqlAnalyzer"):
        v = MigrationValidator(script_manager=sm, history_manager=hm, log=log)
    return v, sm, hm, log


class TestValidationResult(unittest.TestCase):
    def test_default_success(self):
        from core.sql_validator.migration_validator import ValidationResult

        r = ValidationResult()
        self.assertTrue(r.success)
        self.assertEqual(r.error_message, "")
        self.assertEqual(r.repeatable_migrations_to_reapply, [])

    def test_add_modified_repeatable(self):
        from core.sql_validator.migration_validator import ValidationResult

        r = ValidationResult()
        r.add_modified_repeatable("R__test.sql", 123, 456)
        self.assertEqual(len(r.repeatable_migrations_to_reapply), 1)
        entry = r.repeatable_migrations_to_reapply[0]
        self.assertEqual(entry["script"], "R__test.sql")
        self.assertEqual(entry["database_checksum"], 123)
        self.assertEqual(entry["filesystem_checksum"], 456)


class TestLastSuccessfulRecord(unittest.TestCase):
    def _make_migration(self, script_name, mtype, success=True):
        from types import SimpleNamespace

        return SimpleNamespace(script_name=script_name, type=mtype, success="1" if success else "0")

    def test_returns_none_on_empty(self):
        from core.sql_validator.migration_validator import _last_successful_non_delete_record

        self.assertIsNone(_last_successful_non_delete_record([], "V1__test.sql"))

    def test_finds_matching_successful_migration(self):
        from core.sql_validator.migration_validator import _last_successful_non_delete_record

        m = self._make_migration("V1__test.sql", "SQL")
        result = _last_successful_non_delete_record([m], "V1__test.sql")
        self.assertIs(result, m)

    def test_skips_non_matching_script(self):
        from core.sql_validator.migration_validator import _last_successful_non_delete_record

        m = self._make_migration("V2__other.sql", "SQL")
        result = _last_successful_non_delete_record([m], "V1__test.sql")
        self.assertIsNone(result)

    def test_skips_failed_migration(self):
        from core.sql_validator.migration_validator import _last_successful_non_delete_record

        m = self._make_migration("V1__test.sql", "SQL", success=False)
        result = _last_successful_non_delete_record([m], "V1__test.sql")
        self.assertIsNone(result)

    def test_returns_latest_when_multiple(self):
        from core.sql_validator.migration_validator import _last_successful_non_delete_record

        m1 = self._make_migration("V1__test.sql", "SQL")
        m2 = self._make_migration("V1__test.sql", "SQL")
        result = _last_successful_non_delete_record([m1, m2], "V1__test.sql")
        self.assertIs(result, m2)


class TestMigrationValidatorInit(unittest.TestCase):
    def test_init_with_config(self):
        v, sm, hm, log = _make_validator()
        self.assertIs(v.script_manager, sm)
        self.assertIs(v.history_manager, hm)

    def test_init_without_config(self):
        from core.sql_validator.migration_validator import MigrationValidator

        sm = MagicMock()
        hm = MagicMock()
        hm.provider = MagicMock(spec=[])  # no config
        log = MagicMock()
        with patch("core.sql_validator.migration_validator.SqlAnalyzer"):
            v = MigrationValidator(sm, hm, log)
        self.assertIsNotNone(v.sql_analyzer)

    def test_null_log_when_none(self):
        from core.logger import NullLog
        from core.sql_validator.migration_validator import MigrationValidator

        sm, hm = MagicMock(), MagicMock()
        hm.provider = MagicMock()
        hm.provider.config.database.type = "postgresql"
        with patch("core.sql_validator.migration_validator.SqlAnalyzer"):
            v = MigrationValidator(sm, hm, None)
        self.assertIsInstance(v.log, NullLog)


class TestMigrationValidatorReplacePlaceholders(unittest.TestCase):
    def test_replaces_placeholder(self):
        v, *_ = _make_validator()
        v.placeholders = {"env": "prod"}
        result = v._replace_placeholders("SELECT * FROM ${env}_table")
        self.assertIsInstance(result, str)

    def test_no_placeholders_returns_same(self):
        v, *_ = _make_validator()
        result = v._replace_placeholders("SELECT 1")
        self.assertIn("SELECT 1", result)


class TestValidateFlywayCaching(unittest.TestCase):
    def test_returns_cached_result(self):
        v, _, hm, _ = _make_validator()
        cached = {"flyway_exists": True, "compatible": True}
        v._flyway_compatibility_cache = cached
        result = v.validate_flyway_compatibility()
        self.assertIs(result, cached)
        # Provider should NOT be called since cache is hit
        hm.provider.table_exists.assert_not_called()

    def test_no_flyway_table(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.return_value = False
        result = v.validate_flyway_compatibility()
        self.assertFalse(result["flyway_exists"])
        self.assertTrue(result["compatible"])
        # Result is now cached
        self.assertIsNotNone(v._flyway_compatibility_cache)

    def test_flyway_exists_no_dblift(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.side_effect = [True, False]
        result = v.validate_flyway_compatibility()
        self.assertTrue(result["flyway_exists"])
        self.assertFalse(result["Dblift_exists"])

    def test_both_tables_compatible(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.return_value = True
        migration = {
            "version": "1",
            "description": "t",
            "type": "SQL",
            "script": "V1__t.sql",
            "installed_by": "u",
            "installed_rank": 1,
            "checksum": 123,
            "success": True,
        }
        hm.provider.execute_query.return_value = [migration]
        result = v.validate_flyway_compatibility()
        self.assertTrue(result["compatible"])

    def test_count_mismatch(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.return_value = True
        hm.provider.execute_query.side_effect = [
            [{"version": "1", "type": "SQL", "script": "V1.sql", "checksum": 1}],
            [],
        ]
        result = v.validate_flyway_compatibility()
        self.assertFalse(result["compatible"])

    def test_version_mismatch(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.return_value = True
        hm.provider.execute_query.side_effect = [
            [{"version": "1", "type": "SQL", "script": "V1.sql", "checksum": 1}],
            [{"version": "2", "type": "SQL", "script": "V2.sql", "checksum": 1}],
        ]
        result = v.validate_flyway_compatibility()
        self.assertFalse(result["compatible"])
        self.assertIn("version", result["error_message"].lower())

    def test_checksum_mismatch(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.return_value = True
        hm.provider.execute_query.side_effect = [
            [{"version": "1", "type": "SQL", "script": "V1.sql", "checksum": 100}],
            [{"version": "1", "type": "SQL", "script": "V1.sql", "checksum": 200}],
        ]
        result = v.validate_flyway_compatibility()
        self.assertFalse(result["compatible"])

    def test_exception_returns_error(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.side_effect = Exception("DB down")
        result = v.validate_flyway_compatibility()
        self.assertFalse(result["compatible"])
        self.assertIn("Error", result["error_message"])

    def test_invalid_type_in_flyway(self):
        # BOGUS_TYPE, not JDBC: JDBC is a legitimate Flyway vocabulary value
        # (Java-based migration resolver) and FLYWAY_VALID_TYPES now accepts
        # it, so it no longer exercises the "unsupported type" branch here.
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.return_value = True
        hm.provider.execute_query.side_effect = [
            [{"version": "1", "type": "BOGUS_TYPE", "script": "V1.sql", "checksum": 1}],
            [{"version": "1", "type": "SQL", "script": "V1.sql", "checksum": 1}],
        ]
        result = v.validate_flyway_compatibility()
        self.assertFalse(result["compatible"])


class TestCheckFlywaHistoryTable(unittest.TestCase):
    def test_no_flyway_table_passes(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.return_value = False
        result = v.check_flyway_history_table()
        self.assertTrue(result.success)

    def test_flyway_exists_no_dblift_fails(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.side_effect = [True, False]
        result = v.check_flyway_history_table()
        self.assertFalse(result.success)

    def test_both_compatible_passes(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.return_value = True
        v.validate_flyway_compatibility = MagicMock(
            return_value={"compatible": True, "error_message": ""}
        )
        result = v.check_flyway_history_table()
        self.assertTrue(result.success)

    def test_both_incompatible_fails(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.return_value = True
        v.validate_flyway_compatibility = MagicMock(
            return_value={"compatible": False, "error_message": "Mismatch"}
        )
        result = v.check_flyway_history_table()
        self.assertFalse(result.success)
        self.assertIn("Mismatch", result.error_message)

    def test_exception_returns_error(self):
        v, _, hm, _ = _make_validator()
        hm.provider.table_exists.side_effect = Exception("DB crash")
        result = v.check_flyway_history_table()
        self.assertFalse(result.success)


class TestCheckRepeatableMigrationsRankOrdering(unittest.TestCase):
    """BUG-03: _check_repeatable_migrations must use the MOST RECENT history entry
    (max installed_rank), not the oldest, to determine if a R__ is blocked."""

    def _make_script(self, script_name, checksum=42):
        from core.migration.migration import MigrationType

        return SimpleNamespace(
            type=MigrationType.REPEATABLE,
            script_name=script_name,
            checksum=checksum,
            path=None,
        )

    def _make_applied(self, script_name, success, installed_rank, checksum=42, execution_time=100):
        return SimpleNamespace(
            script_name=script_name,
            success=success,
            installed_rank=installed_rank,
            checksum=checksum,
            execution_time=execution_time,
        )

    def _run(self, scripts, applied):
        from core.sql_validator.migration_validator import MigrationValidator, ValidationResult

        v, _, _, _ = _make_validator()
        result = ValidationResult()
        v._check_repeatable_migrations(scripts, applied, result, command="migrate")
        return result

    def test_old_failure_newer_success_does_not_block(self):
        """R__ has old FAILED entry (rank 3) and newer SUCCESS (rank 7) → not blocked."""
        script = self._make_script("R__stats.sql", checksum=42)
        applied = [
            self._make_applied("R__stats.sql", success=False, installed_rank=3, checksum=42),
            self._make_applied("R__stats.sql", success=True, installed_rank=7, checksum=42),
        ]
        result = self._run([script], applied)
        self.assertTrue(result.success, result.error_message)

    def test_old_success_newer_failure_blocks(self):
        """R__ has old SUCCESS entry (rank 3) and newer FAILED (rank 7) → blocked."""
        script = self._make_script("R__stats.sql", checksum=42)
        applied = [
            self._make_applied("R__stats.sql", success=True, installed_rank=3, checksum=42),
            self._make_applied("R__stats.sql", success=False, installed_rank=7, checksum=42),
        ]
        result = self._run([script], applied)
        self.assertFalse(result.success)
        self.assertIn("previously failed", result.error_message)

    def test_no_history_does_not_block(self):
        """R__ with no history entries → applied_script is None → no block."""
        script = self._make_script("R__stats.sql", checksum=42)
        result = self._run([script], [])
        self.assertTrue(result.success)

    def test_single_success_entry_does_not_block(self):
        """Single SUCCESS entry → no regression from next() → max() change."""
        script = self._make_script("R__stats.sql", checksum=42)
        applied = [self._make_applied("R__stats.sql", success=True, installed_rank=1, checksum=42)]
        result = self._run([script], applied)
        self.assertTrue(result.success)
