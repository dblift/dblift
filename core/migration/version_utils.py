"""Shared migration utilities: version comparison and success/failure normalization."""

import re
from typing import Any, List, Optional, Tuple, Union

_VersionPart = Union[Tuple[int, int, str], Tuple[int, str]]


def _parse_version_parts(version: str) -> List[_VersionPart]:
    """Split a version into comparable numeric/alpha segments."""
    if version == "":
        return []

    parts: List[_VersionPart] = []
    for segment in re.split(r"[._]", version):
        if segment == "":
            parts.append((0, 0, ""))
            continue

        numeric_match = re.match(r"^(\d+)([A-Za-z]*)$", segment)
        if numeric_match:
            parts.append((0, int(numeric_match.group(1)), numeric_match.group(2).lower()))
        else:
            parts.append((1, segment.lower()))
    return parts


def compare_versions(version1: Optional[str], version2: Optional[str]) -> int:
    """Compare two migration version strings.

    Handles None, underscore-separated and dot-separated numeric versions
    (e.g. '1_2_3', '1.2.3'), and alphanumeric segments after the first
    (e.g. '3.2A', '1.2.3RC1').

    Purely alphabetic versions ('A' vs 'B') are ordered correctly too, but no
    migration *filename* can carry one: a version must start with a digit, or
    ``Users__seed.sql`` would be indistinguishable from a migration at version
    'sers' (see ``MigrationScriptManager.parse_filename``). That path exists
    for history rows, whose ``version`` column can hold arbitrary text after
    an import from another tool.

    Args:
        version1: First version string, or None (treated as empty string).
        version2: Second version string, or None (treated as empty string).

    Returns:
        -1 if version1 < version2, 0 if equal, 1 if version1 > version2.
    """
    v1 = str(version1).strip() if version1 is not None else ""
    v2 = str(version2).strip() if version2 is not None else ""

    if v1 == v2:
        return 0

    v1_parts = _parse_version_parts(v1)
    v2_parts = _parse_version_parts(v2)

    for i in range(max(len(v1_parts), len(v2_parts))):
        p1 = v1_parts[i] if i < len(v1_parts) else (0, 0, "")
        p2 = v2_parts[i] if i < len(v2_parts) else (0, 0, "")
        if p1 < p2:
            return -1
        if p1 > p2:
            return 1

    return 0


def is_migration_success(value: Any) -> bool:
    """Return True if value represents a successful migration outcome.

    Migration history ``success`` fields can be stored as bool (True/False),
    integer (1/0), or occasionally a string — depending on the native driver and
    dialect.  This helper normalises all representations so comparisons are
    consistent across the codebase (replaces scattered ``is True or == 1`` patterns).

    Args:
        value: The success field from a migration history record.

    Returns:
        True if the value indicates success (bool True, integer 1, or string "true"/"1").
    """
    if value is True or value == 1:
        return True
    if isinstance(value, str) and value.lower() in ("true", "1"):
        return True
    return False


def is_migration_failure(value: Any) -> bool:
    """Return True if value represents an explicit migration failure.

    Matches bool False, integer 0, and the string representations "False"/"false"
    that some native drivers may surface.

    Args:
        value: The success field from a migration history record.

    Returns:
        True if the value explicitly indicates failure.
    """
    return value is False or value == 0 or value in ("False", "false")
