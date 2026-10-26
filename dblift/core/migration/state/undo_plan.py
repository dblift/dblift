"""Select what ``undo`` would revert, and find the undo script for each migration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.rules.migration_rules import (
    MigrationRules,
    expand_undo_set_to_groups,
    group_tag_of,
)
from dblift.core.migration.scripting.filename_parser import parse_migration_filename
from dblift.core.migration.state.migration_selector import normalize_filter
from dblift.core.migration.state.migration_state import (
    MigrationEligibility,
    MigrationReadSnapshot,
    MigrationState,
)
from dblift.core.migration.state.rank_wins import (
    VersionRankState,
    installed_rank,
    latest_successful_ranks,
)
from dblift.core.migration.version_utils import compare_versions, is_migration_success

if TYPE_CHECKING:
    from dblift.core.migration.state.migration_state_manager import MigrationStateManager


@dataclass(frozen=True)
class UndoStep:
    """One applied migration to revert, and the catalog undo script that reverts it."""

    migration: Migration
    undo_script: Migration


@dataclass(frozen=True)
class UndoPlan:
    """What ``undo`` would revert: the state it was read from and the ordered steps.

    ``refusal`` is the message ``undo`` stops with: the migration rules' reason
    for refusing a version, or the missing-undo-script message (then
    ``missing_undo_script`` names that migration). ``selected`` is every
    migration chosen to revert, in execution order, before undo scripts were
    looked up; ``steps`` pairs each with its script and is empty on a refusal.
    ``group_additions`` and ``target_boundary_in_group`` describe a widening to
    a whole group of migrations written as one unit.
    """

    state: MigrationState
    current_version: Optional[str]
    steps: Tuple[UndoStep, ...]
    refusal: Optional[str] = None
    group_additions: Tuple[Migration, ...] = ()
    target_boundary_in_group: bool = False
    selected: Tuple[Migration, ...] = ()
    missing_undo_script: Optional[Migration] = None


_PART_HEADER = re.compile(
    r"^-- Part (\d+) of (\d+); (?:transactional|autocommit-only \(.+\)|"
    r"no statements; keeps every sync part paired with an undo part)\.$"
)
_PART_NAME = re.compile(r"^V(.+)_(\d+)__(.+)\.sql$")
_PART_SIGNATURE = (
    "-- Split because dblift migrate refuses a file that mixes autocommit-only "
    "and transactional statements; "
)
_PART_ORDERS = (
    _PART_SIGNATURE + "apply them in order.",
    _PART_SIGNATURE + "dblift undo applies them from the highest part down.",
)


def _generated_part_groups(
    state: MigrationState,
) -> Dict[str, Tuple[int, Dict[int, Migration], bool]]:
    """Read generated part identity from resolved files, including older untagged files.

    The old writer records part/count in a two-line header. Its filename is
    checked against that header before being used as a group key; an ordinary
    migration with an ``_n`` version is never treated as a generated part.
    """
    groups: Dict[str, Tuple[int, Dict[int, Migration], bool]] = {}
    for migration in state.resolved_objects or ():
        content = migration.content
        name = migration.script_name
        if not isinstance(content, str) or not isinstance(name, str):
            continue
        lines = content.splitlines()
        if len(lines) < 2 or lines[1] not in _PART_ORDERS:
            continue
        header = _PART_HEADER.match(lines[0])
        filename = _PART_NAME.match(name)
        if header is None or filename is None:
            continue
        number, count = int(header[1]), int(header[2])
        if number != int(filename[2]) or not 1 <= number <= count:
            continue
        tag = group_tag_of(migration)
        parent = str(Path(migration.path or name).parent)
        key = tag or f"legacy:{parent}:{filename[1]}:{filename[3]}"
        expected, parts, invalid = groups.setdefault(key, (count, {}, False))
        invalid = invalid or count != expected or number in parts
        if number not in parts:
            parts[number] = migration
        groups[key] = (expected, parts, invalid)
    return groups


def _expected_part_names(parts: Dict[int, Migration], count: int) -> Dict[str, str]:
    """Expected history names, derived only from a validated generated header."""
    seed = next(iter(parts.values()))
    filename = _PART_NAME.match(seed.script_name)
    if filename is None:
        return {}
    names: Dict[str, str] = {}
    for number in range(1, count + 1):
        name = f"V{filename[1]}_{number}__{filename[3]}.sql"
        version = parse_migration_filename(name).version
        if version is not None:
            names[version] = name
    return names


def _include_generated_part_groups(
    state: MigrationState,
    selected: List[Migration],
    applied: List[Migration],
    migration_rules: MigrationRules,
    version_ranks: Dict[str, VersionRankState],
) -> Tuple[List[Migration], Optional[str]]:
    """Refuse incomplete generated sets and widen complete ones before SQL runs."""
    groups = _generated_part_groups(state)
    if not groups or not selected:
        return selected, None
    versions_seen: Dict[Tuple[str, str], int] = {}
    for _, parts, _ in groups.values():
        for part in parts.values():
            identity = (str(part.version), part.script_name)
            versions_seen[identity] = versions_seen.get(identity, 0) + 1
    if any(versions_seen.get((str(m.version), m.script_name), 0) > 1 for m in selected):
        return (
            selected,
            "Cannot undo an ambiguous generated part set: a version exists in multiple groups.",
        )
    current = {
        str(m.version): m
        for m in applied
        if m.version
        and installed_rank(m) == version_ranks[str(m.version)].versioned
        and not migration_rules._is_currently_undone(
            str(m.version), applied, version_ranks=version_ranks
        )
    }
    expanded = list(selected)
    touched = False
    for count, parts, invalid in groups.values():
        expected = _expected_part_names(parts, count)
        if not any(expected.get(str(m.version)) == m.script_name for m in expanded):
            continue
        touched = True
        missing = [
            name
            for version, name in expected.items()
            if version not in current
            or current[version].script_name != name
            or not any(part.script_name == name for part in parts.values())
        ]
        if invalid or len(parts) != count or missing:
            detail = (
                "a generated part file is missing"
                if len(parts) != count
                else "a generated part is absent from applied history"
            )
            if missing:
                detail += f": {', '.join(missing)}"
            return selected, (
                "Cannot undo a partially applied generated part set: "
                f"{detail}. Check migration history and recover this set manually."
            )
        members = [current[version] for version in expected]
        if [installed_rank(member) for member in members] != sorted(
            installed_rank(member) for member in members
        ):
            return selected, (
                "Cannot undo a generated part set applied out of part order. "
                "Check migration history and recover this set manually."
            )
        selected_versions = {str(m.version) for m in expanded}
        expanded.extend(
            member for member in members if str(member.version) not in selected_versions
        )
    if touched:
        expanded.sort(key=installed_rank, reverse=True)
    return expanded, None


def plan_undo(
    state_manager: MigrationStateManager,
    scripts_dir: Optional[Path],
    *,
    recursive: bool,
    additional_dirs: Optional[Sequence[Path]],
    dir_recursive_map: Optional[Dict[Path, bool]],
    target_version: Optional[str],
    tags: Optional[Sequence[str]],
    exclude_tags: Optional[Sequence[str]],
    versions: Optional[Sequence[str]],
    exclude_versions: Optional[Sequence[str]],
    migration_rules: MigrationRules,
    read_snapshot: Optional[MigrationReadSnapshot] = None,
) -> UndoPlan:
    """Read the state through ``read_snapshot`` and select what undo would revert.

    The catalog is unfiltered; undo selects applied Success rows, then the tag and
    version filters. ``target_version`` is rollback-to (undo versions above it),
    not an omit filter. Every undo script is resolved here so a missing script
    anywhere in the plan refuses the whole run.
    """
    tag_filter_active = bool(normalize_filter(tags) or normalize_filter(exclude_tags))

    state = state_manager.build_state(
        scripts_dir,
        recursive=recursive,
        additional_dirs=additional_dirs,
        dir_recursive_map=dir_recursive_map,
        target_version=target_version,
        read_snapshot=read_snapshot,
    )

    applied_migrations = list(state.all_applied_objects)

    current_version = state.current_version

    success_applied = [
        migration
        for migration in applied_migrations
        # type read defensively: history rows may carry an enum or a legacy string.
        if getattr(migration, "type", None) in (MigrationType.SQL, MigrationType.PYTHON)
        and is_migration_success(migration.success)
        and migration.version
    ]
    candidates = state_manager.apply_filters_to_migrations(
        success_applied,
        tags=tags,
        exclude_tags=exclude_tags,
        versions=versions,
        exclude_versions=exclude_versions,
    )
    version_ranks = latest_successful_ranks(applied_migrations)
    # A version undone and then re-applied has several successful rows;
    # only the latest one is currently applied, so plan that row alone.
    candidates = [
        migration
        for migration in candidates
        if installed_rank(migration) == version_ranks[str(migration.version)].versioned
    ]

    # Find migrations to undo using migration rules (based on state)
    migrations_to_undo: List[Migration] = []
    added: List[Migration] = []
    target_boundary_in_group = False

    if target_version is None:
        # No target version specified - find the latest migration that can be undone.
        # Walk applied migrations in reverse install-rank order (most recently
        # applied first) -- every provider's get_applied_migrations() query is
        # ORDER BY installed_rank, and the target-version branch below uses the
        # same reversed(applied_migrations) convention. Install rank, not version
        # number, determines what "most recent" means: migrations can be applied
        # out of version order.
        for migration in reversed(candidates):
            version = str(migration.version)
            # Auto-scan mode: silently skip candidates that are already
            # undone instead of routing through should_undo_version(),
            # which reports a refusal for an already-undone version.
            if migration_rules._is_currently_undone(
                version,
                applied_migrations,
                version_ranks=version_ranks,
            ):
                continue
            migrations_to_undo.append(migration)
            if not tag_filter_active:
                break  # Only undo the most recent undoable migration

        if migrations_to_undo:
            migrations_to_undo, added = expand_undo_set_to_groups(
                migration_rules,
                migrations_to_undo,
                candidates,
                applied_migrations,
                version_ranks=version_ranks,
            )
    else:
        # Target version specified - undo every installed version strictly
        # above the target, regardless of install rank. Out-of-order history
        # (e.g. V3 rank 1, V2 rank 2, --target-version 2) must still undo V3;
        # stopping at the first version ≤ target would skip a higher version
        # installed earlier.
        for migration in reversed(candidates):
            if compare_versions(str(migration.version), str(target_version)) <= 0:
                continue
            version = str(migration.version)
            if migration_rules._is_currently_undone(
                version, applied_migrations, version_ranks=version_ranks
            ):
                continue
            can_undo, message = migration_rules.should_undo_version(
                version,
                applied_migrations,
                version_ranks=version_ranks,
            )
            if can_undo:
                migrations_to_undo.append(migration)
            elif message:
                return UndoPlan(
                    state=state, current_version=current_version, steps=(), refusal=message
                )

        # --target-version undoes every version strictly above the
        # target; if that boundary lands in the middle of a group,
        # widen the plan to the whole group rather than leaving some
        # of its migrations applied and others undone (same rule the
        # no-target-version branch above applies).
        if migrations_to_undo:
            migrations_to_undo, added = expand_undo_set_to_groups(
                migration_rules,
                migrations_to_undo,
                candidates,
                applied_migrations,
                version_ranks=version_ranks,
            )
            target_boundary_in_group = bool(added)

    migrations_to_undo, part_refusal = _include_generated_part_groups(
        state, migrations_to_undo, applied_migrations, migration_rules, version_ranks
    )
    if part_refusal:
        return UndoPlan(
            state=state,
            current_version=current_version,
            steps=(),
            refusal=part_refusal,
            selected=tuple(migrations_to_undo),
        )

    # Resolve every undo script before any write so a missing script
    # anywhere in the plan refuses the real run exactly like the dry run,
    # instead of failing midway and leaving a partial rollback.
    steps: List[UndoStep] = []
    for migration in migrations_to_undo:
        undo_script = _find_undo_script(migration, state)
        if undo_script is None:
            return UndoPlan(
                state=state,
                current_version=current_version,
                steps=(),
                refusal=f"No undo script found for {migration.script_name}",
                group_additions=tuple(added),
                target_boundary_in_group=target_boundary_in_group,
                selected=tuple(migrations_to_undo),
                missing_undo_script=migration,
            )
        steps.append(UndoStep(migration=migration, undo_script=undo_script))
    return UndoPlan(
        state=state,
        current_version=current_version,
        steps=tuple(steps),
        group_additions=tuple(added),
        target_boundary_in_group=target_boundary_in_group,
        selected=tuple(migrations_to_undo),
    )


def _find_undo_script(migration: Any, state: MigrationState) -> Optional[Any]:
    """Return the Available catalog undo script matching the applied version."""
    version = migration.version
    if version is None:
        return None
    version_s = str(version)
    for record in state.catalog:
        if record.eligibility != MigrationEligibility.UNDO_AVAILABLE:
            continue
        if str(record.migration.version) == version_s:
            return record.migration
    return None
