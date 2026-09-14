"""Pure, authoritative migration filename grammar and callback matching."""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from dblift.core.migration.migration_types import MigrationType


@dataclass(frozen=True)
class FilenameMetadata:
    """Immutable classification of a migration filename."""

    migration_type: MigrationType
    version: Optional[str]
    description: str
    tags: tuple[str, ...]
    callback_event: Optional[str] = None


# Canonical list of callback event prefixes (camelCase).
_CALLBACK_PREFIXES = [
    "beforeMigrate",
    "afterMigrate",
    "afterMigrateError",
    "beforeEach",
    "afterEach",
    "beforeValidate",
    "afterValidate",
    "beforeClean",
    "afterClean",
    "afterCleanError",
    "beforeUndo",
    "afterUndo",
    "afterUndoError",
    "beforeEachMigrate",
    "afterEachMigrate",
    "beforeVersioned",
    "afterVersioned",
    "beforeRepeatable",
    "afterRepeatable",
]

# Separator between a callback's event prefix and its description. Mandatory:
# callback files are named ``<eventPrefix>__<description>.<ext>``.
_CALLBACK_SEPARATOR = "__"


def strip_migration_tags(filename: str) -> Tuple[str, List[str]]:
    """Split ``filename`` into its untagged form and its ``[tag1,tag2]`` tags.

    The single implementation of the tag syntax. Every path that reasons about
    a script name — ``MigrationScriptManager.parse_filename`` for classification,
    the callback helpers below for event matching — normalizes through this, so
    the two cannot disagree about what a name means. They did once: matching
    read the raw name while classification read the stripped one, so
    ``afterMigrate[prod]__notify.sql`` was filed as a callback and then
    dispatched to no event, running silently never.

    The pattern is deliberately positionless, matching the documented
    ``<name>__<description>[tag1,tag2].<ext>`` form and also the tag groups
    users have been able to place elsewhere in the name.
    """
    tag_match = re.search(r"\[(.*?)\]", filename)
    if not tag_match:
        return filename, []

    tags = [tag.strip() for tag in tag_match.group(1).split(",") if tag.strip()]
    return filename.replace(tag_match.group(0), ""), tags


def _callback_event_prefix(base_name: str) -> Optional[str]:
    """Return the callback event ``base_name`` is a well-formed file for, else None.

    Requires ``__`` right after the prefix, on the tag-stripped name. Without
    that boundary, five prefixes are literal substrings of others
    (``afterMigrate`` / ``afterMigrateError``, ``beforeEach`` /
    ``beforeEachMigrate``, ``afterEach`` / ``afterEachMigrate``, ``afterClean``
    / ``afterCleanError``, ``afterUndo`` / ``afterUndoError``) and a file for
    the longer event also answers to the shorter one.

    At most one prefix can match: every longer prefix continues with a letter
    where the shorter one requires ``__``.
    """
    lowered = strip_migration_tags(base_name)[0].lower()
    for prefix in _CALLBACK_PREFIXES:
        if lowered.startswith(prefix.lower() + _CALLBACK_SEPARATOR):
            return prefix
    return None


def _callback_prefix_missing_separator(base_name: str) -> Optional[str]:
    """Return the event ``base_name`` looks named for but is malformed for, else None.

    Catches ``afterMigrate.sql`` and ``afterMigrate_notify.sql``: named for an
    event, but with no ``__`` separator, so they are not callbacks. Reported to
    the user rather than silently ignored — such a file sits in the migrations
    directory looking like a callback and never runs.
    """
    if _callback_event_prefix(base_name) is not None:
        return None

    lowered = strip_migration_tags(base_name)[0].lower()
    candidates = [prefix for prefix in _CALLBACK_PREFIXES if lowered.startswith(prefix.lower())]
    # Longest wins, so "afterMigrateError.sql" is reported against the event it
    # was plainly meant to be, not against "afterMigrate".
    return max(candidates, key=len) if candidates else None


# A version must start with a digit. Later segments may mix letters and
# digits (``V3.2A``, ``V1.2.3RC1``) — dblift is deliberately looser than
# Flyway there, which stores versions as integers and rejects any
# non-numeric token. The leading digit is what makes the grammar decidable:
# without it ``VA__create.sql`` (version "A") and ``Users__seed.sql``
# (version "sers") are the same shape, and there is no rule that keeps the
# second from being loaded as a migration.
_VERSION_BODY = r"\d[A-Za-z0-9]*(?:[._][A-Za-z0-9]+)*"


def _versioned_pattern(prefix: str, extension_escaped: str) -> str:
    """Build the ``<prefix>{version}__{description}<ext>`` filename pattern."""
    return rf"^{prefix}({_VERSION_BODY})__(.+){extension_escaped}$"


def _normalize_version(version_str: str) -> str:
    """Return the version with ``_`` separators rendered as ``.``.

    ``V1_2_3`` and ``V1.2.3`` name the same version, so they must not produce
    two different history rows.

    Applied to all-digit versions only, matching long-standing behaviour. A
    version carrying letters is returned verbatim: rewriting ``1_2A`` to
    ``1.2A`` would not match the ``1_2A`` already written to existing history
    rows, and the raw-string set lookups against ``undone_versions`` in
    ``MigrationStateManager`` compare versions as text, not through the
    comparator.
    """
    if version_str.replace(".", "").replace("_", "").isdigit():
        return version_str.replace("_", ".")
    return version_str


# A near-miss is a file that visibly reached for the convention and missed:
# a prefix letter followed by a version-ish character (``V2.1_create.sql``,
# ``R_repeat.sql``), or a prefix plus a one-letter version and the separator
# (``VA__create.sql``). Both halves are deliberately tight, because this fires
# on every single run:
#
#   * the prefix letter alone is far too weak — ``backup_old.sql``,
#     ``routines.sql`` and ``users.sql`` all start with one;
#   * allowing any run of letters before ``__`` is also too weak, because
#     ordinary words then qualify: ``util__helpers.py``,
#     ``report__daily.sql``, ``views__all.sql``. Capping it at a single
#     letter keeps ``VA``/``UB``-style attempts and lets words through.
#
# Baseline (``B``) is deliberately absent: a well-formed ``B1__x.sql`` is
# excluded by design, not by malformation, so warning about it would be wrong.
_NEAR_MISS_RE = re.compile(r"^[VUR](?:[0-9_]|[A-Za-z]?[0-9.]*__)", re.IGNORECASE)


def _looks_like_migration(script_name: str) -> bool:
    """True if *script_name* looks like a failed attempt at the convention."""
    return _NEAR_MISS_RE.match(script_name) is not None


def _matches_callback_event(base_name: str, event_prefix: str) -> bool:
    """Return True if ``base_name`` is a callback file for ``event_prefix``.

    Delegates the boundary rule to :func:`_callback_event_prefix`, so a file
    resolves to exactly one event and never also to a shorter prefix of it.
    Both arguments are compared case-insensitively.
    """
    matched = _callback_event_prefix(base_name)
    return matched is not None and matched.lower() == event_prefix.lower()


def parse_migration_filename(filename: str) -> FilenameMetadata:
    """Resolve a filename with the ScriptManager discovery grammar."""
    # Extract tags if present - they can be in any valid filename.
    # Shared with the callback event helpers so classification and event
    # matching normalize a name identically; see strip_migration_tags.
    filename_without_tags, tags = strip_migration_tags(filename)

    # MULTI-FORMAT SUPPORT: Get the file extension to support multiple formats
    from pathlib import Path

    from dblift.core.migration.formats import MigrationFormatDetector

    file_path = Path(filename_without_tags)
    file_extension = file_path.suffix.lower()

    # Check if this is a valid migration file extension
    if not MigrationFormatDetector.is_migration_file(file_path):
        # Not a recognized migration format - return UNKNOWN
        description = filename_without_tags
        return FilenameMetadata(MigrationType.UNKNOWN, None, description, tuple(tags))

    # Escape the extension for use in regex patterns
    extension_escaped = re.escape(file_extension)

    # Check for callback scripts first (before the generic baseline catch-all).
    # Case-insensitive, and the "__" separator is mandatory: a name without it
    # is not a callback and falls through to the UNKNOWN catch-all below.
    callback_event = _callback_event_prefix(filename_without_tags)
    if callback_event is not None:
        description = filename_without_tags.replace(file_extension, "")
        return FilenameMetadata(
            MigrationType.CALLBACK, None, description, tuple(tags), callback_event
        )

    # Versioned migration: V{version}__{description}[tag1,tag2].<extension>
    versioned_match = re.match(_versioned_pattern("V", extension_escaped), filename_without_tags)
    if versioned_match:
        return FilenameMetadata(
            MigrationType.SQL,
            _normalize_version(versioned_match.group(1)),
            versioned_match.group(2),
            tuple(tags),
        )

    # Undo migration: U{version}__{description}[tag1,tag2].<extension>
    undo_match = re.match(_versioned_pattern("U", extension_escaped), filename_without_tags)
    if undo_match:
        return FilenameMetadata(
            MigrationType.UNDO_SQL,
            _normalize_version(undo_match.group(1)),
            undo_match.group(2),
            tuple(tags),
        )

    # Repeatable migration: R__{description}[tag1,tag2].<extension>
    repeatable_pattern = rf"^R__(.+){extension_escaped}$"
    repeatable_match = re.match(repeatable_pattern, filename_without_tags)
    if repeatable_match:
        return FilenameMetadata(
            MigrationType.REPEATABLE, None, repeatable_match.group(1), tuple(tags)
        )

    # Handle malformed versioned migration: V__.<extension> (no version, no description)
    malformed_versioned = f"V__{file_extension}"
    if filename_without_tags == malformed_versioned or filename_without_tags == "V__.sql":
        return FilenameMetadata(MigrationType.SQL, None, "", tuple(tags))

    # Any other file is unrecognized/invalid (baselines don't exist as script files)
    # For malformed script names, return the filename for debugging/logging purposes
    description = filename_without_tags.replace(file_extension, "").replace(".sql", "")
    return FilenameMetadata(MigrationType.UNKNOWN, None, description, tuple(tags))
