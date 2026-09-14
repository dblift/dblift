"""Pure version and tag selection shared by state and validation."""

from typing import List, Optional, Sequence

from dblift.core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration, MigrationType
from dblift.core.migration.version_utils import compare_versions


def normalize_filter(value: Optional[Sequence[str]]) -> Optional[List[str]]:
    """Normalise a CLI filter value (str or sequence) to a clean list."""
    if value is None:
        return None
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def passes_filters(
    migration: Migration,
    target_version: Optional[str],
    tags: Optional[List[str]],
    exclude_tags: Optional[List[str]],
    versions: Optional[List[str]],
    exclude_versions: Optional[List[str]],
) -> bool:
    """Return True iff *migration* passes the version + tag filters."""
    version = getattr(migration, "version", None)
    migration_tags = getattr(migration, "tags", []) or []

    if target_version and version:
        if compare_versions(str(version), str(target_version)) > 0:
            return False

    if versions and version and str(version) not in versions:
        return False

    if exclude_versions and version and str(version) in exclude_versions:
        return False

    if tags:
        normalized_migration_tags = [
            str(tag).strip().lower() for tag in migration_tags if str(tag).strip()
        ]
        normalized_filter_tags = [str(tag).strip().lower() for tag in tags if str(tag).strip()]
        if not normalized_migration_tags or not any(
            tag in normalized_migration_tags for tag in normalized_filter_tags
        ):
            return False

    if exclude_tags:
        normalized_migration_tags = [
            str(tag).strip().lower() for tag in migration_tags if str(tag).strip()
        ]
        normalized_exclude_tags = [
            str(tag).strip().lower() for tag in exclude_tags if str(tag).strip()
        ]
        if normalized_migration_tags and any(
            tag in normalized_migration_tags for tag in normalized_exclude_tags
        ):
            return False

    return True


def select_migrations(
    migrations: List[Migration],
    target_version: Optional[str] = None,
    tags: Optional[Sequence[str]] = None,
    exclude_tags: Optional[Sequence[str]] = None,
    versions: Optional[Sequence[str]] = None,
    exclude_versions: Optional[Sequence[str]] = None,
) -> List[Migration]:
    """Apply ``passes_filters`` to a list of migrations."""
    normalized_tags = normalize_filter(tags)
    normalized_exclude_tags = normalize_filter(exclude_tags)
    normalized_versions = normalize_filter(versions)
    normalized_exclude_versions = normalize_filter(exclude_versions)

    return [
        migration
        for migration in migrations
        if passes_filters(
            migration,
            target_version,
            normalized_tags,
            normalized_exclude_tags,
            normalized_versions,
            normalized_exclude_versions,
        )
    ]


def prune_baseline_migrations(migrations: List[Migration]) -> List[Migration]:
    """Keep versioned scripts above the highest baseline and all other roles."""
    highest = None
    for migration in migrations:
        if migration.type == MigrationType.BASELINE and migration.version:
            if highest is None or compare_versions(migration.version, highest) > 0:
                highest = migration.version
    if highest is None:
        return migrations
    return [
        m
        for m in migrations
        if getattr(m.type, "name", m.type) not in VERSIONED_SCRIPT_TYPES
        or compare_versions(m.version, highest) > 0
    ]
