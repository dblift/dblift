"""Pure Flyway compatibility rules over HistoryManager table snapshots."""

from typing import TYPE_CHECKING, Dict

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

# The two histories accept different type vocabularies, so one set cannot serve
# both sides of the comparison.
#
# Flyway has no notion of a Python migration and never writes ``PYTHON``;
# accepting it here would weaken a real check.
FLYWAY_VALID_TYPES = frozenset(FLYWAY_TYPE_TO_MIGRATION_TYPE)

# Dblift additionally stores ``PYTHON`` for versioned scripts in a non-SQL
# format (``MigrationType.SQL`` means "versioned", not "SQL format"). Without
# it a single Python migration made a dblift history declare itself
# Flyway-incompatible.
DBLIFT_VALID_TYPES = FLYWAY_VALID_TYPES | {MigrationType.PYTHON.name}


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
                f"{len(Dblift_migrations)} migrations. ."
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
                    f"Dblift version '{Dblift_migration.get('version')}'. ."
                )
                break

            # Check type
            flyway_type = flyway_migration.get("type", "").upper()
            Dblift_type = Dblift_migration.get("type", "").upper()

            if flyway_type not in FLYWAY_VALID_TYPES:
                result["compatible"] = False
                result["error_message"] = (
                    f"Unsupported migration type at position {i+1}: "
                    f"Flyway type '{flyway_type}'.  ."
                )
                break
            if Dblift_type not in DBLIFT_VALID_TYPES:
                result["compatible"] = False
                result["error_message"] = (
                    f"Migration type mismatch at position {i+1}: "
                    f"Flyway type '{flyway_type}' vs Dblift type '{Dblift_type}'.  ."
                )
                break
            # Check script name (both Flyway and Dblift now use 'script')
            if flyway_migration.get("script") != Dblift_migration.get("script"):
                result["compatible"] = False
                result["error_message"] = (
                    f"Migration script name mismatch at position {i+1}: "
                    f"Flyway script '{flyway_migration.get('script')}' vs "
                    f"Dblift script '{Dblift_migration.get('script')}'. ."
                )
                break

            flyway_checksum = normalize_migration_checksum(flyway_migration.get("checksum"))
            dblift_checksum = normalize_migration_checksum(Dblift_migration.get("checksum"))
            if flyway_checksum != dblift_checksum:
                result["compatible"] = False
                result["error_message"] = (
                    f"Migration checksum mismatch at position {i+1}: "
                    f"Flyway checksum '{flyway_migration.get('checksum')}' vs "
                    f"Dblift checksum '{Dblift_migration.get('checksum')}'. ."
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
        result.error_message = " ."
    elif snapshot.flyway_exists:
        comparison = validate_flyway_compatibility(snapshot)
        if not comparison["compatible"]:
            result.success = False
            result.error_message = str(comparison["error_message"])
    return result
