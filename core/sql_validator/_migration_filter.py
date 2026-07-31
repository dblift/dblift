"""Migration loading + filtering helpers extracted from :class:`MigrationValidator`.

Seven small helpers handle script discovery, baseline-version pruning,
filter-flag normalisation and the pre-validation early-exit case. None
of them carry any logic specific to validation per se — they just shape
the input lists that ``validate_resolved_migrations`` then iterates
over.

Pulled into a dedicated module as standalone functions taking the
validator instance as their first parameter (``mv``).
``MigrationValidator`` keeps thin wrapper methods so existing
direct-access tests
(``v._load_and_filter_migrations(...)``, ``v._handle_baseline_filtering(...)``,
``v._passes_filters(...)``, ``v._validate_no_scripts_case(...)``)
continue to work.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple

from packaging.version import parse as parse_version

from core.migration import is_versioned
from core.migration.migration import Migration, MigrationType

if TYPE_CHECKING:
    from core.sql_validator.migration_validator import MigrationValidator


def load_and_filter_migrations(
    mv: "MigrationValidator",
    scripts_dir: Path,
    recursive: bool,
    additional_dirs: List[Path],
    issues: List[str],
) -> List[Migration]:
    """Load all migration scripts and drop unsupported types."""
    # Load all migrations from script files - use our existing logger
    all_scripts = mv.script_manager.get_migration_scripts(
        scripts_dir, recursive=recursive, additional_dirs=additional_dirs
    )

    # Filter out ignored/malformed scripts (e.g., not versioned/repeatable/callback/baseline/undo)
    valid_scripts = []
    for script in all_scripts:
        if script.type in (
            MigrationType.SQL,
            MigrationType.REPEATABLE,
            MigrationType.CALLBACK,
            MigrationType.BASELINE,
            MigrationType.UNDO_SQL,
            MigrationType.PYTHON,
        ):
            valid_scripts.append(script)
        else:
            mv.log.debug(f"Ignoring script with type: {script.type}: {script.script_name}")

    return valid_scripts


def handle_baseline_filtering(
    mv: "MigrationValidator", valid_scripts: List[Migration]
) -> List[Migration]:
    """If a BASELINE migration exists, drop versioned scripts ≤ baseline version."""
    baseline_migrations = [s for s in valid_scripts if s.type == MigrationType.BASELINE]
    if baseline_migrations:
        # Use the highest baseline version if multiple
        highest_baseline = max(baseline_migrations, key=lambda m: parse_version(str(m.version)))
        baseline_version = highest_baseline.version

        # Filter out versioned migrations <= baseline version
        filtered_scripts = []
        for script in valid_scripts:
            # Role, not format: MigrationType.SQL means "versioned", and a
            # versioned .py script carries MigrationType.PYTHON instead.
            if is_versioned(script.type):
                if parse_version(str(script.version)) > parse_version(str(baseline_version)):
                    filtered_scripts.append(script)
            else:
                # Keep all non-versioned migrations (repeatable, callback, baseline, undo)
                filtered_scripts.append(script)

        return filtered_scripts

    return valid_scripts


def normalize_filter(value: Optional[Sequence[str]]) -> Optional[List[str]]:
    """Normalise a CLI filter value (str or sequence) to a clean list."""
    if value is None:
        return None
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def passes_filters(
    mv: "MigrationValidator",
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
        if mv.script_manager.compare_versions(str(version), str(target_version)) > 0:
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


def apply_filters(
    mv: "MigrationValidator",
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
            mv,
            migration,
            target_version,
            normalized_tags,
            normalized_exclude_tags,
            normalized_versions,
            normalized_exclude_versions,
        )
    ]


def scope_applied_migrations_for_validation(
    mv: "MigrationValidator",
    applied_migrations: List[Migration],
    target_version: Optional[str] = None,
    versions: Optional[Sequence[str]] = None,
    exclude_versions: Optional[Sequence[str]] = None,
) -> List[Migration]:
    """Apply version-scope filters to history rows for validation checks.

    Applied history rows may not carry filesystem metadata such as tags, so
    only version-based filters are used here. Repeatables and callbacks have
    no version and remain in scope.
    """
    return apply_filters(
        mv,
        applied_migrations,
        target_version=target_version,
        tags=None,
        exclude_tags=None,
        versions=versions,
        exclude_versions=exclude_versions,
    )


def validate_no_scripts_case(
    mv: "MigrationValidator", valid_scripts: List[Migration], issues: List[str]
) -> Tuple[bool, bool]:
    """Validate the case where there are no valid scripts.

    Returns ``(should_return_early, validation_success)``.
    """
    if not valid_scripts:
        # If there are no valid scripts, validation should succeed
        # (never fail for empty/ignored input)
        mv.log.debug("No valid migration scripts found.")

        # If there are applied migrations and strict mode is on, fail validation
        config = getattr(mv.history_manager, "provider", {})
        config = getattr(config, "config", None)
        if getattr(config, "strict_mode", False):
            applied_migrations = mv.history_manager.get_applied_migrations()
            if applied_migrations:
                return True, False

        # Otherwise, succeed
        return True, True

    return False, True
