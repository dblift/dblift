"""Tests for _validate_checksums same-version collision detection (BUG-04)."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.checksum_drift import find_checksum_drift
from dblift.core.migration.state.missing_scripts import missing_applied
from dblift.core.sql_validator.migration_validator import MigrationValidator, ValidationResult


def _make_validator():
    script_manager = MagicMock()
    history_manager = MagicMock()
    history_manager.provider = MagicMock()
    history_manager.provider.config = None
    log = MagicMock()
    v = MigrationValidator.__new__(MigrationValidator)
    v.script_manager = script_manager
    v.history_manager = history_manager
    v.log = log
    v.placeholders = {}
    v._flyway_compatibility_cache = None
    return v


def _make_migration(script_name, version, migration_type=MigrationType.SQL):
    m = MagicMock()
    m.script_name = script_name
    m.version = version
    m.type = migration_type
    m.success = True
    return m


@pytest.mark.unit
class TestValidateChecksumsVersionCollision:
    def test_same_version_different_name_warning_mentions_alt_script(self):
        """When applied V1__create_containers.sql is absent but V1__initial_containers.sql
        exists in scripts with the same version, the warning must name the alt script."""
        validator = _make_validator()

        applied = _make_migration("V1__create_containers.sql", "1")
        alt_script = _make_migration("V1__initial_containers.sql", "1")

        result = ValidationResult()
        issues = []

        validator._validate_checksums(
            scripts=[alt_script],
            applied_migrations=[applied],
            result=result,
            issues=issues,
            strict_mode=False,
            drift=find_checksum_drift([alt_script], [applied]),
            missing=missing_applied([alt_script], [applied]),
        )

        warning_calls = [str(c) for c in validator.log.warning.call_args_list]
        assert any(
            "V1__initial_containers.sql" in w for w in warning_calls
        ), f"Warning must mention the alt script name. Got: {warning_calls}"


@pytest.mark.unit
class TestValidateChecksumsTagVersionScope:
    def test_applied_migration_filtered_out_of_scope_is_skipped_silently(self):
        """An applied migration whose script is present on disk (``all_scripts``)
        but excluded from the current --tags/--versions filtered ``scripts`` is
        merely out of scope, not missing: no warning/issue should be raised, and
        a debug log should note it was skipped."""
        validator = _make_validator()

        in_scope_script = _make_migration("V1__create_containers.sql", "1")
        filtered_out_script = _make_migration("V2__add_index.sql", "2")
        applied_filtered_out = _make_migration("V2__add_index.sql", "2")

        result = ValidationResult()
        issues = []

        validator._validate_checksums(
            scripts=[in_scope_script],
            applied_migrations=[applied_filtered_out],
            result=result,
            issues=issues,
            strict_mode=False,
            drift=find_checksum_drift([in_scope_script], [applied_filtered_out]),
            missing=missing_applied([in_scope_script, filtered_out_script], [applied_filtered_out]),
        )

        assert issues == []
        assert validator.log.warning.call_args_list == []

        debug_calls = [str(c) for c in validator.log.debug.call_args_list]
        assert any(
            "V2__add_index.sql" in c and "out of scope" in c for c in debug_calls
        ), f"Expected an out-of-scope debug log for V2__add_index.sql. Got: {debug_calls}"


@pytest.mark.unit
class TestValidateChecksumsMissingScripts:
    def _validate(self, validator, scripts, applied, *, strict):
        result = ValidationResult()
        issues = []
        validator._validate_checksums(
            scripts,
            applied,
            result,
            issues,
            strict_mode=strict,
            drift=find_checksum_drift(scripts, applied),
            missing=missing_applied(scripts, applied),
        )
        return result, issues

    def test_script_applied_twice_is_reported_once(self):
        validator = _make_validator()
        rows = [_make_migration("V1__gone.sql", "1"), _make_migration("V1__gone.sql", "1")]

        result, issues = self._validate(validator, [], rows, strict=True)

        assert len(issues) == 1
        assert result.failed_scripts == ["V1__gone.sql"]

    def test_deleted_script_logs_the_deleted_marker_and_raises_nothing(self):
        validator = _make_validator()
        rows = [
            _make_migration("V1__gone.sql", "1"),
            _make_migration("V1__gone.sql", "1", MigrationType.DELETE),
        ]

        result, issues = self._validate(validator, [], rows, strict=True)

        assert issues == []
        assert result.failed_scripts == []
        debug_calls = [str(c) for c in validator.log.debug.call_args_list]
        assert any("V1__gone.sql" in c and "marked as deleted" in c for c in debug_calls)

    def test_script_with_only_a_failed_row_is_not_reported_missing(self):
        validator = _make_validator()
        failed = _make_migration("V1__gone.sql", "1")
        failed.success = False

        result, issues = self._validate(validator, [], [failed], strict=True)

        assert issues == []
        assert result.failed_scripts == []
