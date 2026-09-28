"""Migration rules — ordering/validation helpers shared across migration logic."""

from functools import cmp_to_key
from typing import TYPE_CHECKING, Any, List, Mapping, Optional, Tuple

if TYPE_CHECKING:
    from dblift.core.migration.state.rank_wins import VersionRankState

from dblift.core.logger import Log
from dblift.core.migration._type_match import is_versioned
from dblift.core.migration.migration import Migration
from dblift.core.migration.version_utils import (
    compare_versions,
    is_migration_success,
)

#: Prefix that marks a filename tag (``strip_migration_tags``) as a group
#: marker rather than an ordinary user tag. Migrations written as one group
#: carry a tag ``f"{GROUP_TAG_PREFIX}<key>"`` with the same ``<key>``; the
#: prefix makes it vanishingly unlikely to collide with a tag a user picked
#: for filtering (``--tags prod``, ``--tags nightly``, ...). Filename-safe by
#: construction -- no ``<>:"/\|?*`` -- since a tag lives inside the migration
#: filename itself (``[tag]``) and those characters are illegal in a Windows
#: filename (a colon in particular is also a drive-letter separator there, so
#: an earlier ``dblift:group:V9`` form could not even be checked out on
#: Windows -- ``dblift-group-V9`` is the corrected, filename-safe form).
#: This is the one place that defines the convention -- every reader of a
#: migration's group membership goes through :func:`group_tag_of` instead of
#: re-deriving it.
GROUP_TAG_PREFIX = "dblift-group-"


def group_tag_of(migration: Migration) -> Optional[str]:
    """Return the group tag carried by *migration*, or ``None``.

    A migration belongs to a group when one of its filename tags starts with
    :data:`GROUP_TAG_PREFIX`; two migrations with the same such tag were
    written as one unit.
    """
    for tag in migration.tags:
        if tag.startswith(GROUP_TAG_PREFIX):
            return tag
    return None


class MigrationRules:
    """Migration business rules implementation - handles execution logic."""

    def __init__(self, logger: Log) -> None:
        """Initialize migration rules.

        Args:
            logger: Logger for logging events
        """
        self.logger = logger

    def is_success(self, migration: Any) -> bool:
        """Determine if a migration was successful using consistent logic.

        Args:
            migration: Migration object or any object with a 'success' attribute

        Returns:
            bool: True if the migration was successful, False otherwise
        """
        success_value = getattr(migration, "success", False)
        return is_migration_success(success_value)

    def should_undo_version(
        self,
        version: str,
        applied_migrations: List[Migration],
        *,
        version_ranks: Optional[Mapping[str, "VersionRankState"]] = None,
    ) -> Tuple[bool, str]:
        """Determine if a version should be undone.

        This checks if the version has already been undone and not reapplied,
        and provides guidance on which version to undo next if this one cannot be undone.

        Args:
            version: The version to check
            applied_migrations: List of applied migrations
            version_ranks: Precomputed rank state, when available

        Returns:
            Tuple[bool, str]: (can_undo, message)
                - can_undo: True if the version can be undone, False otherwise
                - message: Empty string if can_undo is True, otherwise an error message
        """
        if not applied_migrations:
            return True, ""
        if version_ranks is None:
            from dblift.core.migration.state.rank_wins import latest_successful_ranks

            version_ranks = latest_successful_ranks(applied_migrations)

        if not self._is_currently_undone(version, applied_migrations, version_ranks=version_ranks):
            return True, ""

        self.logger.warning(
            f"Version {version} has already been undone - cannot undo multiple times without reapplying"
        )

        next_version_to_undo = self._next_version_to_undo(
            version, applied_migrations, version_ranks=version_ranks
        )
        if next_version_to_undo:
            return (
                False,
                f"Version {version} has already been undone. Please specify version {next_version_to_undo} to undo it.",
            )
        return (
            False,
            f"Version {version} has already been undone and no other versions are available to undo.",
        )

    def _is_currently_undone(
        self,
        version: Any,
        applied_migrations: List[Migration],
        *,
        version_ranks: Optional[Mapping[str, "VersionRankState"]] = None,
    ) -> bool:
        """Return True if `version` has an undo that no later re-apply supersedes.

        A version undone and then migrated again is applied, so it is undoable
        again; ranks decide which of the two happened last. Every versioned
        format counts as a re-apply — the history records versioned Python
        scripts as PYTHON, not SQL.
        """
        if version is None or version == "":
            return False
        # Imported here to avoid a rules ↔ state package cycle: state/__init__
        # loads MigrationStateManager, which imports MigrationRules.
        from dblift.core.migration.state.rank_wins import latest_successful_ranks

        if version_ranks is None:
            version_ranks = latest_successful_ranks(applied_migrations)
        state = version_ranks.get(str(version))
        return bool(state and state.currently_undone)

    def _next_version_to_undo(
        self,
        version: Any,
        applied_migrations: List[Migration],
        *,
        version_ranks: Optional[Mapping[str, "VersionRankState"]] = None,
    ) -> Optional[Any]:
        """Return the highest still-applied version other than `version`, or None.

        Mirrors what ``undo`` without a target version would pick: successful
        versioned migrations, newest first by semantic version, skipping any
        version whose undo has not been superseded by a re-apply.
        """
        candidates: List[Any] = []
        seen = set()
        for m in applied_migrations:
            if not is_versioned(getattr(m, "type", None)):
                continue
            if not is_migration_success(getattr(m, "success", False)):
                continue
            m_version = getattr(m, "version", None)
            if m_version is None or m_version == version or str(m_version) in seen:
                continue
            seen.add(str(m_version))
            candidates.append(m_version)

        candidates.sort(
            key=cmp_to_key(lambda a, b: compare_versions(str(a), str(b))),
            reverse=True,
        )

        for candidate in candidates:
            if self._is_currently_undone(
                candidate, applied_migrations, version_ranks=version_ranks
            ):
                continue
            self.logger.info(f"Found next version to undo: {candidate}")
            return candidate

        return None


def expand_undo_set_to_groups(
    migration_rules: "MigrationRules",
    seed_migrations: List[Migration],
    candidate_pool: List[Migration],
    applied_migrations: List[Migration],
    *,
    version_ranks: Mapping[str, "VersionRankState"],
) -> Tuple[List[Migration], List[Migration]]:
    """Extend *seed_migrations* so every group it touches is undone whole.

    Migrations written as one group (:func:`group_tag_of`) are undone or kept
    applied together, never left half-reverted. When any migration in
    *seed_migrations* carries a group tag, every other still-applied
    migration in *candidate_pool* carrying the same tag is pulled in too --
    this is the single function both the no-target-version and the
    ``--target-version`` branches of ``undo`` call to stay consistent with
    each other. *migration_rules* is used only for its ``_is_currently_undone``
    check, matching how both callers already determine "still applied".
    *version_ranks* is the same precomputed state both callers already build
    (``latest_successful_ranks(applied_migrations)``); passing it in avoids a
    second pass over history here.

    Returns ``(full_set, added)``: *full_set* is highest version first (the
    order ``undo`` already executes a multi-version plan in), and *added* is
    what was pulled in beyond the seed, for callers that want to tell the
    user the scope was widened.
    """
    seed_tags = {group_tag_of(m) for m in seed_migrations}
    seed_tags.discard(None)
    if not seed_tags:
        return list(seed_migrations), []

    by_version = {str(m.version): m for m in seed_migrations}
    added: List[Migration] = []
    for migration in candidate_pool:
        tag = group_tag_of(migration)
        if tag not in seed_tags:
            continue
        version = str(migration.version)
        if version in by_version:
            continue
        if migration_rules._is_currently_undone(
            version, applied_migrations, version_ranks=version_ranks
        ):
            continue
        by_version[version] = migration
        added.append(migration)

    full_set = list(by_version.values())
    full_set.sort(
        key=cmp_to_key(lambda a, b: compare_versions(str(a.version), str(b.version))),
        reverse=True,
    )
    return full_set, added
