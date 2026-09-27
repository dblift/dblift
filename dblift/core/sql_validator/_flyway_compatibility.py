"""Pure Flyway compatibility rules over HistoryManager table snapshots."""

from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from dblift.core.sql_validator.migration_validator import ValidationResult

from dblift.core.migration.history.migration_history_manager import FlywayCompatibilitySnapshot
from dblift.core.migration.migration import MigrationType, normalize_migration_checksum

# Maps Flyway's ``flyway_schema_history.type`` vocabulary to the Dblift
# ``MigrationType`` member name it corresponds to. ``JDBC``, ``SPRING_JDBC``
# and ``SCRIPT`` are Flyway's Java-based/generic migration resolvers; they
# still describe a versioned migration, so they map to ``SQL`` rather than
# being treated as unsupported.
#
# ``UNDO_SQL`` was renamed to ``UNDO_SCRIPT`` in Flyway 9.0; every Flyway
# version from 9.x through the current 12.x writes ``UNDO_SCRIPT`` for undo
# migrations. Both keys are kept so rows written by Flyway 8.x and earlier
# still map correctly.
#
# ``DELETE`` marks a script-removal audit-trail entry and matches
# ``MigrationType.DELETE`` exactly.
FLYWAY_TYPE_TO_MIGRATION_TYPE: Dict[str, str] = {
    "SQL": MigrationType.SQL.name,
    "JDBC": MigrationType.SQL.name,
    "SPRING_JDBC": MigrationType.SQL.name,
    "SCRIPT": MigrationType.SQL.name,
    "BASELINE": MigrationType.BASELINE.name,
    "UNDO_SQL": MigrationType.UNDO_SQL.name,
    "UNDO_SCRIPT": MigrationType.UNDO_SQL.name,
    "DELETE": MigrationType.DELETE.name,
}


def dblift_type_for_flyway_row(flyway_type: str, version: object) -> Optional[str]:
    """Return the Dblift ``MigrationType`` name a Flyway history row maps to.

    ``import-flyway`` writes imported rows with this mapping and the
    compatibility check compares against it, so the two cannot disagree.
    Flyway records a repeatable migration as a versionless ``SQL`` row, which
    Dblift stores as ``REPEATABLE``. Returns ``None`` for a Flyway type with
    no Dblift equivalent (Flyway never writes ``PYTHON``, for instance).
    """
    mapped = FLYWAY_TYPE_TO_MIGRATION_TYPE.get(flyway_type)
    if mapped == MigrationType.SQL.name and not version:
        return MigrationType.REPEATABLE.name
    return mapped


def validate_flyway_compatibility(snapshot: FlywayCompatibilitySnapshot) -> Dict[str, object]:
    """Compare the supplied histories without database access or caching verdicts."""
    result: Dict[str, object] = {
        "flyway_exists": snapshot.flyway_exists,
        "Dblift_exists": snapshot.dblift_exists,
        "compatible": True,
        "error_message": "",
        "flyway_count": len(snapshot.flyway_migrations),
        "Dblift_count": len(snapshot.dblift_migrations),
    }
    if snapshot.collection_error:
        result["compatible"] = False
        result["error_message"] = (
            f"Error checking Flyway compatibility: {snapshot.collection_error}"
        )
        return result
    if not snapshot.flyway_exists or not snapshot.dblift_exists:
        return result
    flyway_migrations = snapshot.flyway_migrations
    Dblift_migrations = snapshot.dblift_migrations
    try:
        # Compare migration counts
        if len(flyway_migrations) != len(Dblift_migrations):
            result["compatible"] = False
            result["error_message"] = (
                f"Flyway has {len(flyway_migrations)} migrations but Dblift has "
                f"{len(Dblift_migrations)} migrations."
            )
            return result

        # Compare each migration (excluding checksums)
        for i, flyway_migration in enumerate(flyway_migrations):
            Dblift_migration = Dblift_migrations[i]

            # Check version
            if flyway_migration.get("version") != Dblift_migration.get("version"):
                result["compatible"] = False
                result["error_message"] = (
                    f"Migration version mismatch at position {i+1}: "
                    f"Flyway version '{flyway_migration.get('version')}' vs "
                    f"Dblift version '{Dblift_migration.get('version')}'."
                )
                break

            # Check type
            flyway_type = flyway_migration.get("type", "").upper()
            Dblift_type = Dblift_migration.get("type", "").upper()

            expected_type = dblift_type_for_flyway_row(flyway_type, flyway_migration.get("version"))
            if expected_type is None:
                result["compatible"] = False
                result["error_message"] = (
                    f"Unsupported migration type at position {i+1}: "
                    f"Flyway type '{flyway_type}'."
                )
                break
            # Dblift stores a versioned script in a non-SQL format as
            # ``PYTHON`` (``MigrationType.SQL`` means "versioned", not "SQL
            # format"), so it stands in for a versioned Flyway row.
            accepted_types = {expected_type}
            if expected_type == MigrationType.SQL.name:
                accepted_types.add(MigrationType.PYTHON.name)
            if Dblift_type not in accepted_types:
                result["compatible"] = False
                result["error_message"] = (
                    f"Migration type mismatch at position {i+1}: "
                    f"Flyway type '{flyway_type}' (Dblift '{expected_type}') vs "
                    f"Dblift type '{Dblift_type}'."
                )
                break
            # Check script name (both Flyway and Dblift now use 'script')
            if flyway_migration.get("script") != Dblift_migration.get("script"):
                result["compatible"] = False
                result["error_message"] = (
                    f"Migration script name mismatch at position {i+1}: "
                    f"Flyway script '{flyway_migration.get('script')}' vs "
                    f"Dblift script '{Dblift_migration.get('script')}'."
                )
                break

            flyway_checksum = normalize_migration_checksum(flyway_migration.get("checksum"))
            dblift_checksum = normalize_migration_checksum(Dblift_migration.get("checksum"))
            if flyway_checksum != dblift_checksum:
                result["compatible"] = False
                result["error_message"] = (
                    f"Migration checksum mismatch at position {i+1}: "
                    f"Flyway checksum '{flyway_migration.get('checksum')}' vs "
                    f"Dblift checksum '{Dblift_migration.get('checksum')}'."
                )
                break

            # Skip checking success as Flyway might use 1/0 while Dblift uses true/false
    except Exception as error:
        result["compatible"] = False
        result["error_message"] = f"Error checking Flyway compatibility: {error}"

    return result


def check_flyway_history_table(snapshot: FlywayCompatibilitySnapshot) -> "ValidationResult":
    """Apply the 4.x import and compatibility result semantics."""
    from dblift.core.sql_validator.migration_validator import ValidationResult

    result = ValidationResult()
    if snapshot.collection_error:
        result.success = False
        context = (
            "compatibility"
            if snapshot.flyway_exists and snapshot.dblift_exists
            else "history table"
        )
        result.error_message = f"Error checking Flyway {context}: {snapshot.collection_error}"
    elif snapshot.flyway_exists and not snapshot.dblift_exists:
        result.success = False
        result.error_message = (
            "A Flyway schema history table exists but the Dblift schema history "
            "table does not. Run import-flyway to import the Flyway history."
        )
    elif snapshot.flyway_exists:
        comparison = validate_flyway_compatibility(snapshot)
        if not comparison["compatible"]:
            result.success = False
            result.error_message = str(comparison["error_message"])
    return result
