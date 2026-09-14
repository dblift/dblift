"""Public validation entry points return the same results for prepared inputs."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from dblift.core.logger import NullLog
from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.sql_validator.migration_validator import MigrationValidator, ValidationResult


def _validator(
    *,
    history=(),
    strict: bool = False,
    supports_sql: bool = True,
    history_table_exists=None,
) -> MigrationValidator:
    validator = MigrationValidator.__new__(MigrationValidator)
    validator.script_manager = MigrationScriptManager(NullLog())
    validator.history_manager = SimpleNamespace(
        has_history_table=(bool(history) if history_table_exists is None else history_table_exists),
        provider=SimpleNamespace(config=SimpleNamespace(strict_mode=strict)),
        get_applied_migrations=MagicMock(return_value=list(history)),
        schema="public",
        history_table="dblift_schema_history",
    )
    validator.log = MagicMock()
    validator._quirks = SimpleNamespace(
        dialect_name="test-document-store",
        supports_sql_migrations=supports_sql,
    )
    return validator


def _script(tmp_path, name, *, content="SELECT 1;\n", directory=None, tags=()):
    parent = tmp_path / directory if directory else tmp_path
    parent.mkdir(exist_ok=True)
    path = parent / name
    path.write_text(content, encoding="utf-8")
    script = Migration(path)
    script.tags = list(tags)
    return script


def _history(script, *, checksum=None, success=True, installed_rank=1):
    return SimpleNamespace(
        script_name=script.script_name,
        version=script.version,
        description=script.description,
        type=script.type,
        checksum=script.checksum if checksum is None else checksum,
        success=success,
        execution_time=10,
        installed_rank=installed_rank,
        path=None,
        tags=[],
    )


def _public_result(result: ValidationResult):
    return {
        "success": result.success,
        "error_message": result.error_message,
        "issues": result.issues,
        "failed_scripts": result.failed_scripts,
        "checked_scripts": result.checked_scripts,
        "repeatable_migrations_to_reapply": result.repeatable_migrations_to_reapply,
        "migrations": [migration.script_name for migration in result.migrations],
        "execution_time": result.execution_time,
    }


def _validate_both(
    tmp_path,
    scripts,
    *,
    history=(),
    strict=False,
    supports_sql=True,
    command="validate",
):
    directory_validator = _validator(history=history, strict=strict, supports_sql=supports_sql)
    directory_result = directory_validator.validate_migrations(
        tmp_path,
        command=command,
        resolved_migrations=scripts,
        preloaded_records=list(history),
    )

    resolved_validator = _validator(history=history, strict=strict, supports_sql=supports_sql)
    resolved_result = resolved_validator.validate_resolved_migrations(scripts, command=command)

    assert _public_result(directory_result) == _public_result(resolved_result)
    return directory_result, directory_validator


def test_entrypoints_reject_an_unsupported_sql_format(tmp_path):
    script = _script(tmp_path, "V1__create.sql")

    result, _ = _validate_both(tmp_path, [script], supports_sql=False)

    assert result.success is False
    assert result.error_message.startswith("DBLIFT-NOSQL-001:")
    assert result.issues == [result.error_message]
    assert result.failed_scripts == ["V1__create.sql"]
    assert result.migrations == []


def test_entrypoints_report_duplicate_versions_identically(tmp_path):
    first = _script(tmp_path, "V1__first.sql")
    second = _script(tmp_path, "V1__second.sql")

    result, _ = _validate_both(tmp_path, [first, second])

    assert result.success is False
    assert result.issues == [
        "Validation failed: Found migration scripts with duplicate versions",
        f"Version 1 is used by both {first.path} and {second.path}",
    ]
    assert result.failed_scripts == ["V1__first.sql", "V1__second.sql"]
    assert result.migrations == []
    assert result.execution_time == 0


def test_entrypoints_report_duplicate_repeatable_names_identically(tmp_path):
    first = _script(tmp_path, "R__refresh.sql", directory="primary")
    second = _script(tmp_path, "R__refresh.sql", directory="secondary")

    result, _ = _validate_both(tmp_path, [first, second])

    assert result.success is False
    assert result.issues == [
        "Validation failed: Found repeatable migration scripts with duplicate names",
        "Repeatable migration name R__refresh.sql is used by scripts in more than "
        f"one directory: {first.path} and {second.path}",
    ]
    assert result.migrations == []
    assert result.execution_time == 0


def test_entrypoints_report_failed_history_identically(tmp_path):
    script = _script(tmp_path, "V1__create.sql")
    failed = _history(script, success=False)

    result, _ = _validate_both(tmp_path, [script], history=[failed])

    assert result.success is False
    assert result.issues == [
        "Found 1 failed migration(s): V1__create.sql (version: 1)",
        "Run 'repair' command to update the status in the history table.",
    ]
    assert result.failed_scripts == ["V1__create.sql"]
    assert result.checked_scripts == ["V1__create.sql"]
    assert [migration.script_name for migration in result.migrations] == ["V1__create.sql"]


def test_entrypoints_report_strict_checksum_drift_identically(tmp_path):
    script = _script(tmp_path, "V1__create.sql")
    applied = _history(script, checksum=script.checksum + 1)

    result, _ = _validate_both(tmp_path, [script], history=[applied], strict=True)

    assert result.success is False
    assert result.issues == [
        "Migration script V1__create.sql has been modified since it was applied. "
        f"Database checksum: {script.checksum + 1}, Filesystem checksum: {script.checksum}",
        "Validation failed. Detected modified migration scripts.",
    ]
    assert result.failed_scripts == ["V1__create.sql"]
    assert result.checked_scripts == ["V1__create.sql"]


def test_changed_repeatable_only_keeps_early_return_result(tmp_path):
    repeatable = _script(tmp_path, "R__refresh.sql", content="SELECT 2;\n")
    applied = _history(repeatable, checksum=repeatable.checksum + 1)

    result, _ = _validate_both(tmp_path, [repeatable], history=[applied])

    assert result.success is True
    assert result.repeatable_migrations_to_reapply == [
        {
            "script": "R__refresh.sql",
            "database_checksum": str(repeatable.checksum + 1),
            "filesystem_checksum": repeatable.checksum,
        }
    ]
    assert result.checked_scripts == []
    assert [migration.script_name for migration in result.migrations] == ["R__refresh.sql"]
    assert result.execution_time > 0


def test_changed_repeatable_with_versioned_history_keeps_full_pipeline_result(tmp_path):
    versioned = _script(tmp_path, "V1__create.sql")
    repeatable = _script(tmp_path, "R__refresh.sql", content="SELECT 2;\n")
    applied_versioned = _history(versioned)
    applied_repeatable = _history(repeatable, checksum=repeatable.checksum + 1)

    result, _ = _validate_both(
        tmp_path,
        [versioned, repeatable],
        history=[applied_versioned, applied_repeatable],
    )

    assert result.success is True
    assert result.repeatable_migrations_to_reapply == [
        {
            "script": "R__refresh.sql",
            "database_checksum": str(repeatable.checksum + 1),
            "filesystem_checksum": repeatable.checksum,
        }
    ]
    assert result.checked_scripts == ["V1__create.sql", "R__refresh.sql"]
    assert [migration.script_name for migration in result.migrations] == [
        "V1__create.sql",
        "R__refresh.sql",
    ]
    assert result.execution_time == 0


def test_empty_preloaded_history_does_not_trigger_a_fresh_read(tmp_path):
    script = _script(tmp_path, "V1__create.sql")
    validator = _validator(history_table_exists=True)

    result = validator.validate_migrations(
        tmp_path,
        resolved_migrations=[script],
        preloaded_records=[],
    )

    assert result.success is True
    assert result.issues == []
    assert [migration.script_name for migration in result.migrations] == ["V1__create.sql"]
    validator.history_manager.get_applied_migrations.assert_not_called()


def test_tag_filtered_script_in_full_catalog_is_not_reported_missing(tmp_path):
    included = _script(tmp_path, "V1__included.sql", tags=["keep"])
    excluded = _script(tmp_path, "V2__excluded.sql", tags=["other"])
    applied = _history(excluded)
    validator = _validator(history=[applied])

    result = validator.validate_migrations(
        tmp_path,
        command="migrate",
        tags=["keep"],
        resolved_migrations=[included, excluded],
        preloaded_records=[applied],
    )

    assert result.success is True
    assert result.issues == []
    assert result.failed_scripts == []
    assert [migration.script_name for migration in result.migrations] == ["V1__included.sql"]
    warnings = [call.args[0] for call in validator.log.warning.call_args_list]
    assert not any("missing from the migration directory" in warning for warning in warnings)


def test_genuinely_missing_script_keeps_warning_behavior(tmp_path):
    included = _script(tmp_path, "V1__included.sql")
    missing = _script(tmp_path, "V2__missing.sql")
    applied = _history(missing)
    missing.path.unlink()
    validator = _validator(history=[applied])

    result = validator.validate_migrations(
        tmp_path,
        command="migrate",
        resolved_migrations=[included],
        preloaded_records=[applied],
    )

    assert result.success is True
    assert result.issues == []
    assert result.failed_scripts == []
    warnings = [call.args[0] for call in validator.log.warning.call_args_list]
    assert any("V2__missing.sql' is missing from the migration directory" in w for w in warnings)


def test_genuinely_missing_script_keeps_strict_failure_behavior(tmp_path):
    included = _script(tmp_path, "V1__included.sql")
    missing = _script(tmp_path, "V2__missing.sql")
    applied = _history(missing)
    missing.path.unlink()
    validator = _validator(history=[applied], strict=True)

    result = validator.validate_migrations(
        tmp_path,
        command="validate",
        resolved_migrations=[included],
        preloaded_records=[applied],
    )

    assert result.success is False
    assert result.failed_scripts == ["V2__missing.sql"]
    assert result.issues == [
        "Strict mode validation failed. Found 1 applied migration(s) without "
        "corresponding script files: V2__missing.sql (version: 2). ."
    ]


def test_strict_tag_scope_keeps_existing_missing_file_result(tmp_path):
    included = _script(tmp_path, "V1__included.sql", tags=["keep"])
    excluded = _script(tmp_path, "V2__excluded.sql", tags=["other"])
    applied = _history(excluded)
    validator = _validator(history=[applied], strict=True)

    result = validator.validate_migrations(
        tmp_path,
        command="validate",
        tags=["keep"],
        resolved_migrations=[included, excluded],
        preloaded_records=[applied],
    )

    assert result.success is False
    assert result.failed_scripts == ["V2__excluded.sql"]
    assert result.issues == [
        "Strict mode validation failed. Found 1 applied migration(s) without "
        "corresponding script files: V2__excluded.sql (version: 2). ."
    ]
