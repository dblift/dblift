"""
Database version detection and capability tracking.

Detects database versions and tracks version-specific capabilities
to enable feature-aware introspection and SQL generation.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# SQL Server year-based version numbers (released years) to internal version numbers.
# Used to convert SQL Server's "year" versioning (e.g. 2019) to internal (e.g. 15).
_SQLSERVER_YEAR_TO_VERSION: Dict[int, int] = {
    2008: 10,
    2012: 11,
    2014: 12,
    2016: 13,
    2017: 14,
    2019: 15,
    2022: 16,
}


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


@dataclass
class DatabaseCapabilities:
    """Tracks database capabilities based on version."""

    version: DatabaseVersion
    dialect: str
    capabilities: Set[str] = field(default_factory=set)
    unsupported_features: Set[str] = field(default_factory=set)
    warnings: List[str] = field(default_factory=list)

    def supports(self, feature: str) -> bool:
        """Check if a feature is supported."""
        return feature in self.capabilities

    def is_unsupported(self, feature: str) -> bool:
        """Check if a feature is explicitly unsupported."""
        return feature in self.unsupported_features


class VersionDetector:
    """
    Detects database versions and tracks capabilities.

    Supports:
    - PostgreSQL (9.0+)
    - Oracle (10g+)
    - MySQL (5.0+)
    - SQL Server (2008+)
    - DB2 (9.0+)
    """

    # Version patterns for different databases
    VERSION_PATTERNS = {
        "postgresql": [
            r"PostgreSQL\s+(\d+)\.(\d+)(?:\.(\d+))?",
            r"(\d+)\.(\d+)(?:\.(\d+))?",
        ],
        "oracle": [
            r"Oracle Database\s+(\d+)g?[^\d]*(\d+)?",
            r"(\d+)\.(\d+)(?:\.(\d+))?",
        ],
        "mysql": [
            r"(\d+)\.(\d+)(?:\.(\d+))?",
        ],
        "sqlserver": [
            r"Microsoft SQL Server\s+(\d+)(?:\.(\d+))?(?:\.(\d+))?",
            r"(\d+)\.(\d+)(?:\.(\d+))?",
        ],
        # SQL Server year to version mapping: 2016=13, 2017=14, 2019=15, 2022=16
        "db2": [
            r"DB2/(?:LUW|z/OS)\s+(\d+)\.(\d+)(?:\.(\d+))?",
            r"(\d+)\.(\d+)(?:\.(\d+))?",
        ],
    }

    # Feature capability matrix
    FEATURE_MATRIX = {
        "postgresql": {
            "materialized_views": {"min_version": DatabaseVersion(9, 3)},
            "jsonb": {"min_version": DatabaseVersion(9, 4)},
            "row_level_security": {"min_version": DatabaseVersion(9, 5)},
            "identity_columns": {"min_version": DatabaseVersion(10, 0)},
            "partitioning": {"min_version": DatabaseVersion(10, 0)},
            "generated_columns": {"min_version": DatabaseVersion(12, 0)},
        },
        "oracle": {
            "identity_columns": {"min_version": DatabaseVersion(12, 1)},
            "json_data_type": {"min_version": DatabaseVersion(12, 2)},
            "invisible_columns": {"min_version": DatabaseVersion(12, 1)},
        },
        "mysql": {
            "json_data_type": {"min_version": DatabaseVersion(5, 7)},
            "generated_columns": {"min_version": DatabaseVersion(5, 7)},
            "check_constraints": {"min_version": DatabaseVersion(8, 0)},
            "window_functions": {"min_version": DatabaseVersion(8, 0)},
        },
        "sqlserver": {
            "json_data_type": {"min_version": DatabaseVersion(13, 0)},  # SQL Server 2016
            "temporal_tables": {"min_version": DatabaseVersion(13, 0)},
            "columnstore_indexes": {"min_version": DatabaseVersion(11, 0)},  # SQL Server 2012
        },
        "db2": {
            "json_data_type": {"min_version": DatabaseVersion(10, 5)},
            "temporal_tables": {"min_version": DatabaseVersion(10, 1)},
        },
    }

    def __init__(self, dialect: str):
        """
        Initialize the version detector.

        Args:
            dialect: Database dialect name
        """
        self.dialect = dialect.lower()
        self.version: Optional[DatabaseVersion] = None
        self.capabilities: Optional[DatabaseCapabilities] = None

    def detect_version(self, version_string: str) -> DatabaseVersion:
        """
        Parse version string and extract version components.

        Args:
            version_string: Raw version string from database

        Returns:
            DatabaseVersion object
        """
        patterns = self.VERSION_PATTERNS.get(self.dialect, [])

        for pattern in patterns:
            match = re.search(pattern, version_string, re.IGNORECASE)
            if match:
                groups = match.groups()
                major = int(groups[0])
                minor = int(groups[1]) if len(groups) > 1 and groups[1] else 0
                patch = int(groups[2]) if len(groups) > 2 and groups[2] else 0

                # SQL Server year to version mapping
                if self.dialect in frozenset({"sqlserver"}) and 2000 <= major < 3000:
                    if major in _SQLSERVER_YEAR_TO_VERSION:
                        major = _SQLSERVER_YEAR_TO_VERSION[major]
                        # Handle R2 releases
                        if "R2" in version_string.upper() and major == 10:
                            minor = 5

                self.version = DatabaseVersion(
                    major=major,
                    minor=minor,
                    patch=patch,
                    full_version=version_string,
                )
                return self.version

        # Fallback: try to extract any numbers
        numbers = re.findall(r"\d+", version_string)
        if numbers:
            major = int(numbers[0])
            minor = int(numbers[1]) if len(numbers) > 1 else 0
            patch = int(numbers[2]) if len(numbers) > 2 else 0
            self.version = DatabaseVersion(
                major=major,
                minor=minor,
                patch=patch,
                full_version=version_string,
            )
            return self.version

        # Unknown version
        logger.warning(f"Could not parse version string: {version_string}")
        self.version = DatabaseVersion(major=0, minor=0, patch=0, full_version=version_string)
        return self.version

    def build_capabilities(self, version: Optional[DatabaseVersion] = None) -> DatabaseCapabilities:
        """
        Build capability matrix based on version.

        Args:
            version: Optional version (uses detected version if not provided)

        Returns:
            DatabaseCapabilities object
        """
        if version is None:
            if self.version is None:
                raise ValueError("No version detected. Call detect_version() first.")
            version = self.version

        capabilities = DatabaseCapabilities(version=version, dialect=self.dialect)

        # Check feature matrix
        feature_matrix = self.FEATURE_MATRIX.get(self.dialect, {})
        for feature, requirements in feature_matrix.items():
            min_version = requirements.get("min_version")
            if min_version and version >= min_version:
                capabilities.capabilities.add(feature)
            else:
                capabilities.unsupported_features.add(feature)
                if min_version:
                    capabilities.warnings.append(
                        f"Feature '{feature}' requires {self.dialect} {min_version}, "
                        f"but detected version is {version}"
                    )

        self.capabilities = capabilities
        return capabilities

    def check_feature_support(self, feature: str) -> tuple[bool, Optional[str]]:
        """
        Check if a feature is supported and return reason if not.

        Args:
            feature: Feature name to check

        Returns:
            Tuple of (is_supported, reason_if_not)
        """
        if not self.capabilities:
            return False, "Capabilities not built. Call build_capabilities() first."

        if self.capabilities.supports(feature):
            return True, None

        if self.capabilities.is_unsupported(feature):
            feature_matrix = self.FEATURE_MATRIX.get(self.dialect, {})
            requirements = feature_matrix.get(feature, {})
            min_version = requirements.get("min_version")
            if min_version:
                return (
                    False,
                    f"Requires {self.dialect} {min_version}, but detected {self.capabilities.version}",
                )

        return False, "Feature not supported or unknown"

    def get_warnings(self) -> List[str]:
        """Get all capability warnings."""
        if not self.capabilities:
            return []
        return self.capabilities.warnings
