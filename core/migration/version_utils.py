"""Shared migration utilities: version comparison and success/failure normalization."""

import re
from typing import Any, List, Optional, Tuple

# One comparable run inside a segment: (kind, number, text) where kind 0 is a
# digit run and kind 1 a letter run. The uniform 3-tuple shape lets runs of
# either kind be compared directly, and puts every digit run below every
# letter run.
_VersionRun = Tuple[int, int, str]
_VersionPart = List[_VersionRun]

_EMPTY_RUN: _VersionRun = (0, 0, "")
_RUN_RE = re.compile(r"\d+|[A-Za-z]+")


def _segment_runs(segment: str) -> _VersionPart:
    """Decompose one segment into its digit and letter runs.

    ``"3RC1"`` becomes ``[(0, 3, ""), (1, 0, "rc"), (0, 1, "")]``. Decomposing
    rather than matching ``<digits><letters>`` as a whole is what makes
    ``1.2.3RC1`` order below ``1.2.4``: the leading number is compared first.
    Matching the segment wholesale left ``3RC1`` unrecognised, so it was
    treated as a pure letter run and sorted above every numeric segment.
    """
    runs: _VersionPart = [
        (0, int(token), "") if token.isdigit() else (1, 0, token.lower())
        for token in _RUN_RE.findall(segment)
    ]
    return runs or [_EMPTY_RUN]


def _parse_version_parts(version: str) -> List[_VersionPart]:
    """Split a version into comparable segments, each a list of runs."""
    if version == "":
        return []
    return [_segment_runs(segment) for segment in re.split(r"[._]", version)]


def _compare_segments(left: _VersionPart, right: _VersionPart) -> int:
    """Compare two segments run by run.

    When one segment runs out, the one with runs left over is the greater:
    ``3A`` is above ``3``. That is dblift's convention — a suffix marks a
    later revision — and deliberately not PEP 440, where a suffix marks a
    pre-release and sorts below. Flipping it would silently reorder every
    history that already contains a suffixed version.
    """
    for index in range(max(len(left), len(right))):
        if index >= len(left):
            return -1
        if index >= len(right):
            return 1
        if left[index] != right[index]:
            return -1 if left[index] < right[index] else 1
    return 0


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

    # Missing segments pad with zero, so "1.0" equals "1".
    for i in range(max(len(v1_parts), len(v2_parts))):
        p1 = v1_parts[i] if i < len(v1_parts) else [_EMPTY_RUN]
        p2 = v2_parts[i] if i < len(v2_parts) else [_EMPTY_RUN]
        result = _compare_segments(p1, p2)
        if result != 0:
            return result

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
