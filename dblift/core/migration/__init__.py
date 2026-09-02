"""Public entry point for migration-related symbols.

``docs/semver-policy.md`` § 1 documents these re-exports as part of the
stable surface. The underlying modules (``migration``, ``_type_match``)
are implementation details and may be reorganised; this file is what
downstream code imports against.
"""

from dblift.core.migration._type_match import (
    is_migration_type,
    is_versioned,
    migration_type_name,
)
from dblift.core.migration.migration import (
    VERSIONED_SCRIPT_TYPES,
    AppliedMigration,
    Migration,
    MigrationResource,
    MigrationType,
    ResolvedMigration,
)

__all__ = [
    "Migration",
    "MigrationResource",
    "ResolvedMigration",
    "AppliedMigration",
    "MigrationType",
    "VERSIONED_SCRIPT_TYPES",
    "is_migration_type",
    "is_versioned",
    "migration_type_name",
]
