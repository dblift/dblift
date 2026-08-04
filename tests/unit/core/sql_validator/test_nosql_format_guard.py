"""`validate`, `migrate --validate-only`, and `migrate --dry-run` must reject a
``.sql`` migration aimed at a NoSQL dialect (Cosmos DB), not report success.

The real, non-dry-run ``migrate`` already refuses a ``.sql`` migration on a
dialect that declares ``supports_sql_migrations = False`` — see
``tests/unit/core/migration/executors/test_nosql_sql_migration_guard.py``.
That guard lives inside ``ExecutionEngine.execute_migration``, on the
statement-execution path, so ``--dry-run``, ``--validate-only``, and plain
``validate`` never reached it — none of them execute anything.

All three resolve their migrations through
``MigrationValidator.validate_migrations``:

* plain ``validate`` -> ``ValidateCommand.execute`` ->
  ``self.validator.validate_migrations(scripts_dir, "validate", ...)``
* ``migrate --validate-only`` -> ``cli/handlers/migrate.py`` calls
  ``ctx.client.validate(...)``, i.e. the exact same ``ValidateCommand`` path
* ``migrate --dry-run`` -> ``MigrateCommand.execute`` runs
  ``MigrationHelpers.validate_migrations_for_migrate``, which calls
  ``validate_migrations(scripts_dir, "migrate", ...)`` as a pre-flight,
  before ``_handle_dry_run`` ever lists a migration as "would execute".

So a single check inside ``validate_migrations`` — reusing the same pure
``check_format_supported`` predicate the real execution path calls — fixes
all three call sites at once.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from core.migration.migration import Migration
from core.sql_validator.migration_validator import MigrationValidator


def _validator(dialect: str) -> MigrationValidator:
    """A MigrationValidator wired to *dialect* through the real quirks registry."""
    script_manager = MagicMock()
    history_manager = MagicMock()
    history_manager.has_history_table = False
    history_manager.provider.config.database.type = dialect
    history_manager.provider.config.strict_mode = False
    with patch("core.sql_validator.migration_validator.SqlAnalyzer"):
        validator = MigrationValidator(
            script_manager=script_manager, history_manager=history_manager, log=MagicMock()
        )
    validator._load_and_filter_migrations = MagicMock()
    validator._handle_baseline_filtering = MagicMock(side_effect=lambda scripts: scripts)
    return validator


def _sql_migration(tmp_path: Path, name: str) -> Migration:
    script = tmp_path / name
    script.write_text("CREATE TABLE t (id INT);", encoding="utf-8")
    return Migration(script_path=script)


def _python_migration(tmp_path: Path, name: str) -> Migration:
    script = tmp_path / name
    script.write_text("def migrate(context):\n    pass\n", encoding="utf-8")
    return Migration(script_path=script)


def test_plain_validate_rejects_sql_migration_on_cosmosdb(tmp_path):
    validator = _validator("cosmosdb")
    validator._load_and_filter_migrations.return_value = [
        _sql_migration(tmp_path, "V1_0_0__create.sql")
    ]

    result = validator.validate_migrations(tmp_path, command="validate")

    assert result.success is False
    assert "DBLIFT-NOSQL-001" in result.error_message
    assert "V1_0_0__create.sql" in result.error_message


def test_validate_only_rejects_sql_migration_on_cosmosdb(tmp_path):
    """``migrate --validate-only`` calls ``ValidateCommand.execute`` too — same
    ``validate_migrations(..., "validate", ...)`` call as plain ``validate``.
    """
    validator = _validator("cosmosdb")
    validator._load_and_filter_migrations.return_value = [
        _sql_migration(tmp_path, "V1_0_1__seed.sql")
    ]

    result = validator.validate_migrations(tmp_path, command="validate")

    assert result.success is False
    assert "DBLIFT-NOSQL-001" in result.error_message
    assert "V1_0_1__seed.sql" in result.error_message


def test_migrate_dry_run_preflight_rejects_sql_migration_on_cosmosdb(tmp_path):
    """``migrate --dry-run``'s pre-flight calls ``validate_migrations(..., "migrate", ...)``."""
    validator = _validator("cosmosdb")
    validator._load_and_filter_migrations.return_value = [
        _sql_migration(tmp_path, "V1_0_2__index.sql")
    ]

    result = validator.validate_migrations(tmp_path, command="migrate")

    assert result.success is False
    assert "DBLIFT-NOSQL-001" in result.error_message
    assert "V1_0_2__index.sql" in result.error_message


def test_python_migration_on_cosmosdb_is_unaffected(tmp_path):
    validator = _validator("cosmosdb")
    validator._load_and_filter_migrations.return_value = [
        _python_migration(tmp_path, "V1_0_0__create.py")
    ]

    result = validator.validate_migrations(tmp_path, command="validate")

    assert result.success is True


def test_sql_migration_on_relational_dialect_is_unaffected(tmp_path):
    validator = _validator("postgresql")
    validator._load_and_filter_migrations.return_value = [
        _sql_migration(tmp_path, "V1_0_0__create.sql")
    ]

    result = validator.validate_migrations(tmp_path, command="validate")

    assert result.success is True
