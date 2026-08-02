"""Flyway compatibility checks extracted from :class:`MigrationValidator`.

Three methods (``validate_flyway_compatibility``,
``check_flyway_history_table``, ``_check_table_compatibility``) handle a
single isolated concern: detecting the presence of a Flyway-managed
``flyway_schema_history`` table and verifying it is consistent with the
Dblift-managed history table.

Pulled out as standalone functions taking the validator instance as
their first parameter (``mv``). ``MigrationValidator`` keeps thin
wrapper methods so existing tests (which call ``v.validate_flyway_*``,
``v.check_flyway_history_table()`` and ``v._check_table_compatibility()``
directly) continue to work.

The cache (``mv._flyway_compatibility_cache``) is read and written
through the validator instance — it is process-scoped state, not a
helper concern.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

from core.migration.migration import MigrationType, normalize_migration_checksum

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

if TYPE_CHECKING:
    from core.sql_validator.migration_validator import (
        MigrationValidator,
        ValidationResult,
    )


def validate_flyway_compatibility(mv: "MigrationValidator") -> Dict[str, object]:
    """Compare Flyway and Dblift schema history tables.

    Reads both tables (when present) and checks that they describe the
    same migration list with compatible checksums. Caches the result on
    the validator instance.
    """
    # Use cached result if available
    if mv._flyway_compatibility_cache is not None:
        return mv._flyway_compatibility_cache

    provider = mv.history_manager.provider

    result: Dict[str, object] = {
        "flyway_exists": False,
        "Dblift_exists": False,
        "compatible": True,
        "error_message": "",
        "flyway_count": 0,
        "Dblift_count": 0,
    }

    # Check if Flyway schema history table exists
    try:
        # Always use lowercase and unquoted table name for existence check
        flyway_exists = provider.table_exists(
            mv.history_manager.schema, "flyway_schema_history"
        )  # Always use lowercase
        result["flyway_exists"] = flyway_exists

        if not flyway_exists:
            mv.log.debug(
                f"No Flyway schema history table found in schema " f"[{mv.history_manager.schema}]"
            )
            mv._flyway_compatibility_cache = result
            return mv._flyway_compatibility_cache

        # Check if Dblift schema history table exists.
        # ADR-0015 (BUG-03): pass the normalized name so Oracle's
        # case-folded storage matches.
        Dblift_exists = provider.table_exists(
            mv.history_manager.schema, mv.history_manager.normalized_history_table
        )
        result["Dblift_exists"] = Dblift_exists

        if not Dblift_exists:
            mv.log.debug(
                f"No Dblift schema history table found in schema " f"[{mv.history_manager.schema}]"
            )
            mv._flyway_compatibility_cache = result
            return mv._flyway_compatibility_cache

        # Both tables exist, let's compare them
        mv.log.info(
            f"Both Flyway and Dblift schema history tables found in schema "
            f"[{mv.history_manager.schema}]"
        )

        # Query Flyway history table - always use lowercase table name and quoted column names
        flyway_query = f"""
        SELECT
            "version",
            "description",
            "type",
            "script",
            "installed_by",
            "installed_rank",
            "checksum",
            "success"
        FROM {mv.history_manager.schema}.flyway_schema_history
        ORDER BY "installed_rank"
        """

        flyway_migrations = provider.execute_query(flyway_query)
        result["flyway_count"] = len(flyway_migrations)

        # Query Dblift history table
        Dblift_query = f"""
        SELECT
            version,
            description,
            type,
            script,
            installed_by,
            installed_rank,
            checksum,
            success
        FROM {mv.history_manager.schema}.{mv.history_manager.history_table}
        ORDER BY installed_rank
        """

        Dblift_migrations = provider.execute_query(Dblift_query)
        result["Dblift_count"] = len(Dblift_migrations)

        # Compare migration counts
        if len(flyway_migrations) != len(Dblift_migrations):
            result["compatible"] = False
            result["error_message"] = (
                f"Flyway has {len(flyway_migrations)} migrations but Dblift has "
                f"{len(Dblift_migrations)} migrations. ."
            )
            mv.log.error(str(result["error_message"]))
            mv._flyway_compatibility_cache = result
            return mv._flyway_compatibility_cache

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
                mv.log.error(str(result["error_message"]))
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
                mv.log.error(str(result["error_message"]))
                break
            if Dblift_type not in DBLIFT_VALID_TYPES:
                result["compatible"] = False
                result["error_message"] = (
                    f"Migration type mismatch at position {i+1}: "
                    f"Flyway type '{flyway_type}' vs Dblift type '{Dblift_type}'.  ."
                )
                mv.log.error(str(result["error_message"]))
                break
            # Check script name (both Flyway and Dblift now use 'script')
            if flyway_migration.get("script") != Dblift_migration.get("script"):
                result["compatible"] = False
                result["error_message"] = (
                    f"Migration script name mismatch at position {i+1}: "
                    f"Flyway script '{flyway_migration.get('script')}' vs "
                    f"Dblift script '{Dblift_migration.get('script')}'. ."
                )
                mv.log.error(str(result["error_message"]))
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
                mv.log.error(str(result["error_message"]))
                break

            # Skip checking success as Flyway might use 1/0 while Dblift uses true/false

        if result["compatible"]:
            mv.log.info(
                f"Flyway and Dblift schema history tables are compatible, "
                f"containing {len(flyway_migrations)} migrations"
            )

        mv._flyway_compatibility_cache = result
        return mv._flyway_compatibility_cache

    except Exception as e:
        mv.log.error(f"Error checking Flyway compatibility: {str(e)}")
        result["compatible"] = False
        result["error_message"] = f"Error checking Flyway compatibility: {str(e)}"
        mv._flyway_compatibility_cache = result
        return mv._flyway_compatibility_cache


def check_flyway_history_table(mv: "MigrationValidator") -> "ValidationResult":
    """Validate Flyway↔Dblift state.

    1. Checks if the Flyway schema history table exists.
    2. If it exists but Dblift table doesn't, returns an error suggesting
       ``import-flyway``.
    3. If both tables exist, validates their compatibility.
    """
    from core.sql_validator.migration_validator import ValidationResult

    result = ValidationResult()
    provider = mv.history_manager.provider

    try:
        # Check if Flyway schema history table exists - always use lowercase
        flyway_table_exists = provider.table_exists(
            mv.history_manager.schema, "flyway_schema_history"
        )

        if not flyway_table_exists:
            # No Flyway table, so validation passes
            return result

        # Check if Dblift schema history table exists.
        # ADR-0015 (BUG-03): pass the normalized name so Oracle's
        # case-folded storage matches.
        dblift_table_exists = provider.table_exists(
            mv.history_manager.schema, mv.history_manager.normalized_history_table
        )

        # If Flyway table exists but Dblift table doesn't, prompt user to run import-flyway
        if flyway_table_exists and not dblift_table_exists:
            mv.log.warning(
                f"Detected Flyway schema history table in [{mv.history_manager.schema}] "
                "but no Dblift schema history table.  ."
            )
            result.success = False
            result.error_message = " " "."
            return result

        # If both tables exist, check for compatibility.
        # Call back through ``mv.validate_flyway_compatibility()`` (the wrapper
        # method) rather than the standalone function so test code that mocks
        # ``v.validate_flyway_compatibility`` on a per-instance basis still
        # intercepts the call.
        if flyway_table_exists and dblift_table_exists:
            flyway_check = mv.validate_flyway_compatibility()
            if not flyway_check["compatible"]:
                result.success = False
                result.error_message = str(flyway_check["error_message"])
                return result

        return result

    except Exception as e:
        mv.log.error(f"Error checking Flyway history table: {str(e)}")
        result.success = False
        result.error_message = f"Error checking Flyway history table: {str(e)}"
        return result


def check_table_compatibility(mv: "MigrationValidator", issues: List[str]) -> None:
    """Ensure the Dblift schema history table exists.

    Currently a thin orchestrator. Story 10-26 will extend this with
    actual Flyway/Dblift compatibility checks once the underlying
    ``BaseHistoryManager`` exposes ``has_flyway_history()`` and
    ``check_flyway_dblift_compatibility()``.
    """
    if not mv.history_manager.has_history_table:
        # Create schema history table if it doesn't exist
        mv.history_manager.create_schema_and_history_table()
    else:
        # BACKLOG P2 (story 10-26): Implémenter vérification compatibilité Flyway.
        # Raison: Méthodes has_flyway_history() et check_flyway_dblift_compatibility()
        # n'existent pas encore dans BaseHistoryManager ni ses sous-classes.
        # Impact: Pas de détection de conflit si flyway_schema_history et dblift coexistent
        # → risque de double-exécution de migrations ou incohérences de tracking.
        # Approche: 1) Ajouter has_flyway_history() dans BaseHistoryManager
        # (query flyway_schema_history) 2) Ajouter check_flyway_dblift_compatibility()
        # retournant {"compatible": bool, "message": str} 3) Implémenter la logique de
        # vérification ici (voir story 10-26 dev notes pour le code original).
        # Dépendances: BaseHistoryManager doit exposer les 2 méthodes ci-dessus.
        # Ref: voir _bmad-output/implementation-artifacts/10-26-todos-documenter-ou-implementer.md
        pass
