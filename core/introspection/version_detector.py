"""
Database version value type.

Provides the :class:`DatabaseVersion` value object used to represent and
compare database server versions (major/minor/patch) during normalization.
"""

from dataclasses import dataclass
from typing import Optional


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
