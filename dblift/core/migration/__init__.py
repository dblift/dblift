"""Public entry point for migration-related symbols.

``docs/semver-policy.md`` § 1 documents these re-exports as part of the
stable surface. The underlying modules (``migration``, ``_type_match``)
are implementation details and may be reorganised; this file is what
downstream code imports against.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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

_EXPORT_MODULES = {
    **dict.fromkeys(
        (
            "Migration",
            "MigrationResource",
            "ResolvedMigration",
            "AppliedMigration",
            "MigrationType",
            "VERSIONED_SCRIPT_TYPES",
        ),
        "migration",
    ),
    **dict.fromkeys(("is_migration_type", "is_versioned", "migration_type_name"), "_type_match"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORT_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{_EXPORT_MODULES[name]}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
