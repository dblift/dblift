"""Strict-mode validation must be consistent between migrate and validate."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.sql_validator.migration_validator import MigrationValidator


def _validator(strict_result: bool) -> MigrationValidator:
    validator = MigrationValidator.__new__(MigrationValidator)
    validator.log = MagicMock()
    validator.history_manager = SimpleNamespace(
        has_history_table=True,
        provider=SimpleNamespace(config=SimpleNamespace(strict_mode=True)),
        get_applied_migrations=MagicMock(
            return_value=[
                SimpleNamespace(
                    script_name="V1__old.sql",
                    type="SQL",
                    version="1",
                    success=True,
                )
            ]
        ),
    )
    validator._load_and_filter_migrations = MagicMock(
        return_value=[
            SimpleNamespace(
                script_name="V2__new.sql",
                type=MigrationType.SQL,
                version="2",
                content="SELECT 1;",
            )
        ]
    )
    validator._handle_baseline_filtering = MagicMock(side_effect=lambda scripts: scripts)
    validator._validate_no_scripts_case = MagicMock(return_value=(False, True))
    validator._check_repeatable_migrations = MagicMock()
    validator._validate_duplicate_versions = MagicMock(return_value=True)
    validator._validate_sql_syntax = MagicMock()
    validator._validate_strict_mode_rules = MagicMock(return_value=strict_result)
    validator._validate_failed_migrations = MagicMock()
    validator._validate_checksums = MagicMock()
    validator._validate_reappeared_migrations = MagicMock()
    return validator


@pytest.mark.unit
def test_validate_command_runs_strict_mode_rules(tmp_path: Path):
    validator = _validator(strict_result=False)

    result = validator.validate_migrations(tmp_path, command="validate")

    assert result.success is True  # helper controls detailed mutation; this test pins invocation
    validator._validate_strict_mode_rules.assert_called_once()


@pytest.mark.unit
def test_non_migrate_validate_commands_do_not_run_strict_mode_rules(tmp_path: Path):
    validator = _validator(strict_result=True)

    validator.validate_migrations(tmp_path, command="info")

    validator._validate_strict_mode_rules.assert_not_called()


def _filtering_validator() -> MigrationValidator:
    validator = MigrationValidator.__new__(MigrationValidator)
    validator.log = MagicMock()
    validator.placeholders = {}
    validator.script_manager = SimpleNamespace(
        compare_versions=lambda left, right: int(left) - int(right)
    )
    validator.history_manager = SimpleNamespace(
        has_history_table=False,
        provider=SimpleNamespace(config=SimpleNamespace(strict_mode=False)),
        get_applied_migrations=MagicMock(return_value=[]),
    )
    validator._handle_baseline_filtering = MagicMock(side_effect=lambda scripts: scripts)
    validator._validate_no_scripts_case = MagicMock(
        side_effect=lambda scripts, issues: (not scripts, True)
    )
    validator._check_repeatable_migrations = MagicMock()
    validator._validate_duplicate_versions = MagicMock(return_value=True)
    validator._validate_failed_migrations = MagicMock()
    validator._validate_checksums = MagicMock()
    validator._validate_reappeared_migrations = MagicMock()

    validator._validate_sql_syntax = MagicMock()
    return validator


@pytest.mark.unit
def test_target_version_filter_skips_out_of_scope_placeholder_warnings(tmp_path: Path):
    validator = _filtering_validator()
    validator._load_and_filter_migrations = MagicMock(
        return_value=[
            SimpleNamespace(
                script_name="V1__init.sql",
                type=MigrationType.SQL,
                version="1",
                content="SELECT 1;",
            ),
            SimpleNamespace(
                script_name="V3__placeholder.sql",
                type=MigrationType.SQL,
                version="3",
                content="SELECT '${MY_LABEL}';",
            ),
        ]
    )

    result = validator.validate_migrations(tmp_path, command="validate", target_version="1")

    assert result.success is True
    warnings = [call.args[0] for call in validator.log.warning.call_args_list]
    assert not any("MY_LABEL" in warning for warning in warnings)


@pytest.mark.unit
def test_validate_does_not_parse_in_scope_placeholder_script(tmp_path: Path):
    validator = _filtering_validator()
    validator._load_and_filter_migrations = MagicMock(
        return_value=[
            SimpleNamespace(
                script_name="V3__placeholder.sql",
                type=MigrationType.SQL,
                version="3",
                content="SELECT '${MY_LABEL}';",
            )
        ]
    )

    result = validator.validate_migrations(tmp_path, command="validate", target_version="3")

    assert result.success is True
    validator._validate_sql_syntax.assert_not_called()
    warnings = [call.args[0] for call in validator.log.warning.call_args_list]
    assert not any("MY_LABEL" in warning for warning in warnings)


@pytest.mark.unit
def test_validate_ignores_unresolved_placeholder_outside_sql_literal(tmp_path: Path):
    validator = _filtering_validator()
    validator._load_and_filter_migrations = MagicMock(
        return_value=[
            SimpleNamespace(
                script_name="V5__placeholder.sql",
                type=MigrationType.SQL,
                version="5",
                content="CREATE TABLE ${TABLE_NAME} (id INT);",
            )
        ]
    )

    result = validator.validate_migrations(tmp_path, command="validate")

    assert result.success is True
    validator._validate_sql_syntax.assert_not_called()
    warnings = [call.args[0] for call in validator.log.warning.call_args_list]
    assert not any("TABLE_NAME" in warning for warning in warnings)


@pytest.mark.unit
def test_validate_resolved_migrations_does_not_parse_pending_sql():
    validator = _filtering_validator()
    scripts = [
        SimpleNamespace(
            script_name="V5__placeholder.sql",
            type=MigrationType.SQL,
            version="5",
            content="CREATE TABLE ${TABLE_NAME} (id INT);",
        )
    ]

    result = validator.validate_resolved_migrations(scripts, command="migrate")

    assert result.success is True
    validator._validate_sql_syntax.assert_not_called()


@pytest.mark.unit
def test_target_version_filter_keeps_applied_scripts_in_checksum_scope(tmp_path: Path):
    validator = _filtering_validator()
    validator.history_manager.has_history_table = True
    validator.history_manager.get_applied_migrations.return_value = [
        SimpleNamespace(script_name="V3__applied.sql", type=MigrationType.SQL, version="3"),
        SimpleNamespace(script_name="V5__future.sql", type=MigrationType.SQL, version="5"),
    ]
    validator._load_and_filter_migrations = MagicMock(
        return_value=[
            SimpleNamespace(
                script_name="V3__applied.sql",
                type=MigrationType.SQL,
                version="3",
                content="SELECT 3;",
            ),
            SimpleNamespace(
                script_name="V4__pending.sql",
                type=MigrationType.SQL,
                version="4",
                content="SELECT 4;",
            ),
            SimpleNamespace(
                script_name="V5__future.sql",
                type=MigrationType.SQL,
                version="5",
                content="SELECT 5;",
            ),
        ]
    )
    checksum_scope = []
    applied_scope = []

    def capture_checksum_scope(scripts, applied_migrations, *_args):
        checksum_scope.extend(script.script_name for script in scripts)
        applied_scope.extend(migration.script_name for migration in applied_migrations)

    validator._validate_checksums = MagicMock(side_effect=capture_checksum_scope)

    result = validator.validate_migrations(tmp_path, command="migrate", target_version="4")

    assert result.success is True
    assert "V3__applied.sql" in checksum_scope
    assert "V4__pending.sql" in checksum_scope
    assert "V5__future.sql" not in checksum_scope
    assert "V3__applied.sql" in applied_scope
    assert "V5__future.sql" not in applied_scope
