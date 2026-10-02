"""
Database version value type.

Provides the :class:`DatabaseVersion` value object used to represent and
compare database server versions (major/minor/patch) during normalization,
plus the shared :func:`parse_version` / :func:`version_matches_spec` helpers
used by version-specific type mappings and feature gates.
"""

import re
from dataclasses import dataclass
from typing import Optional, Union


@dataclass
class DatabaseVersion:
    """Represents a database version with major, minor, and patch components."""

    major: int
    minor: int = 0
    patch: int = 0
    build: Optional[str] = None
    full_version: Optional[str] = None

    def __str__(self) -> str:
        """String representation of version."""
        parts = [f"{self.major}.{self.minor}"]
        if self.patch > 0:
            parts.append(f".{self.patch}")
        if self.build:
            parts.append(f" ({self.build})")
        return "".join(parts)

    def __ge__(self, other: "DatabaseVersion") -> bool:
        """Compare versions (>=)."""
        if self.major != other.major:
            return self.major >= other.major
        if self.minor != other.minor:
            return self.minor >= other.minor
        return self.patch >= other.patch

    def __lt__(self, other: "DatabaseVersion") -> bool:
        """Compare versions (<)."""
        return not (self >= other)


_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(version_str: Optional[str]) -> Optional[DatabaseVersion]:
    """Parse the first dotted numeric run in *version_str* into a version.

    Handles vendor banners as well as bare versions: ``"PostgreSQL 16.2 on
    x86_64..."`` -> 16.2, ``"8.0.36-log"`` -> 8.0.36, ``"15.0.2000.5"`` ->
    15.0.2000, ``"Oracle Database 19c ... Release 19.0.0.0.0"`` -> 19.0.0.
    Returns ``None`` (never raises) when no ``major.minor`` run is found.
    """
    if not version_str:
        return None
    match = _VERSION_RE.search(version_str)
    if match is None:
        return None
    major, minor, patch = match.group(1), match.group(2), match.group(3)
    return DatabaseVersion(
        major=int(major),
        minor=int(minor),
        patch=int(patch) if patch is not None else 0,
        full_version=version_str,
    )


def version_matches_spec(version: Union[str, DatabaseVersion, None], spec: str) -> bool:
    """True when *version* satisfies *spec* (``"9.4+"`` -> version >= 9.4).

    A spec without a trailing ``+`` requires an exact ``major.minor[.patch]``
    match. Returns ``False`` (never raises) when either side is unparseable.
    """
    actual = parse_version(version) if not isinstance(version, DatabaseVersion) else version
    if actual is None:
        return False
    if spec.endswith("+"):
        minimum = parse_version(spec[:-1])
        if minimum is None:
            return False
        return actual >= minimum
    exact = parse_version(spec)
    if exact is None:
        return False
    return (actual.major, actual.minor, actual.patch) == (exact.major, exact.minor, exact.patch)
