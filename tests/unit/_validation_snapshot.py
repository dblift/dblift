"""Run the validator the way the commands do: state manager snapshot, then ``validate_snapshot``."""

from pathlib import Path
from typing import Any, List, Optional

from dblift.core.migration.migration import Migration
from dblift.core.sql_validator.migration_validator import MigrationValidator, ValidationResult


def validate_snapshot_for(
    validator: MigrationValidator,
    scripts_dir: Optional[Path] = None,
    command: str = "migrate",
    *,
    resolved_migrations: Optional[List[Migration]] = None,
    **snapshot_args: Any,
) -> ValidationResult:
    """Build the validation snapshot from ``validator.state_manager`` and validate it.

    ``scripts_dir`` and ``resolved_migrations`` choose where the catalog comes from, as in
    ``ValidateCommand`` (directory) and the executor (already-resolved list); the remaining
    keyword arguments are passed to ``MigrationStateManager.build_validation_snapshot``.
    """
    snapshot = validator.state_manager.build_validation_snapshot(
        scripts_dir, command, resolved_migrations=resolved_migrations, **snapshot_args
    )
    return validator.validate_snapshot(snapshot, command)
