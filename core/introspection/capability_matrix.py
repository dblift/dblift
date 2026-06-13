"""
Database capability matrix for version-specific features.

Provides a comprehensive mapping of database features to their
minimum version requirements and availability across editions.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from core.introspection.version_detector import DatabaseVersion


@dataclass
class FeatureRequirement:
    """Represents version and edition requirements for a feature."""

    min_version: Optional[DatabaseVersion] = None
    max_version: Optional[DatabaseVersion] = None
    editions: Optional[Set[str]] = None  # e.g., {"Enterprise", "Standard"}
    requires_license: bool = False
    notes: Optional[str] = None


class CapabilityMatrix:
    """
    Comprehensive capability matrix for database features.

    Tracks which features are available in which database versions
    and editions, enabling feature-aware introspection and SQL generation.
    """

    # PostgreSQL capabilities
    POSTGRESQL_FEATURES: Dict[str, FeatureRequirement] = {
        "materialized_views": FeatureRequirement(
            min_version=DatabaseVersion(9, 3),
            notes="Requires PostgreSQL 9.3+",
        ),
        "jsonb": FeatureRequirement(
            min_version=DatabaseVersion(9, 4),
            notes="JSONB data type support",
        ),
        "row_level_security": FeatureRequirement(
            min_version=DatabaseVersion(9, 5),
            notes="Row-level security policies",
        ),
        "identity_columns": FeatureRequirement(
            min_version=DatabaseVersion(10, 0),
            notes="GENERATED AS IDENTITY",
        ),
        "partitioning": FeatureRequirement(
            min_version=DatabaseVersion(10, 0),
            notes="Native table partitioning",
        ),
        "generated_columns": FeatureRequirement(
            min_version=DatabaseVersion(12, 0),
            notes="GENERATED ALWAYS AS columns",
        ),
        "sql_json_functions": FeatureRequirement(
            min_version=DatabaseVersion(9, 3),
            notes="JSON functions and operators",
        ),
    }

    # Oracle capabilities
    ORACLE_FEATURES: Dict[str, FeatureRequirement] = {
        "identity_columns": FeatureRequirement(
            min_version=DatabaseVersion(12, 1),
            notes="GENERATED AS IDENTITY (12cR1+)",
        ),
        "json_data_type": FeatureRequirement(
            min_version=DatabaseVersion(12, 2),
            notes="JSON data type (12cR2+)",
        ),
        "invisible_columns": FeatureRequirement(
            min_version=DatabaseVersion(12, 1),
            notes="INVISIBLE columns (12cR1+)",
        ),
        "temporal_validity": FeatureRequirement(
            min_version=DatabaseVersion(12, 1),
            notes="Temporal validity periods (12cR1+)",
        ),
        "adaptive_plans": FeatureRequirement(
            min_version=DatabaseVersion(12, 1),
            editions={"Enterprise"},
            requires_license=True,
            notes="Adaptive execution plans (Enterprise only)",
        ),
    }

    # MySQL capabilities
    MYSQL_FEATURES: Dict[str, FeatureRequirement] = {
        "json_data_type": FeatureRequirement(
            min_version=DatabaseVersion(5, 7),
            notes="JSON data type (MySQL 5.7+)",
        ),
        "generated_columns": FeatureRequirement(
            min_version=DatabaseVersion(5, 7),
            notes="Generated columns (MySQL 5.7+)",
        ),
        "check_constraints": FeatureRequirement(
            min_version=DatabaseVersion(8, 0),
            notes="CHECK constraints (MySQL 8.0+)",
        ),
        "window_functions": FeatureRequirement(
            min_version=DatabaseVersion(8, 0),
            notes="Window functions (MySQL 8.0+)",
        ),
        "common_table_expressions": FeatureRequirement(
            min_version=DatabaseVersion(8, 0),
            notes="CTEs (MySQL 8.0+)",
        ),
    }

    # SQL Server capabilities
    SQLSERVER_FEATURES: Dict[str, FeatureRequirement] = {
        "json_data_type": FeatureRequirement(
            min_version=DatabaseVersion(13, 0),  # SQL Server 2016
            notes="JSON data type (SQL Server 2016+)",
        ),
        "temporal_tables": FeatureRequirement(
            min_version=DatabaseVersion(13, 0),  # SQL Server 2016
            notes="System-versioned temporal tables",
        ),
        "columnstore_indexes": FeatureRequirement(
            min_version=DatabaseVersion(11, 0),  # SQL Server 2012
            editions={"Enterprise", "Developer"},
            notes="Columnstore indexes (Enterprise/Developer)",
        ),
        "memory_optimized_tables": FeatureRequirement(
            min_version=DatabaseVersion(12, 0),  # SQL Server 2014
            editions={"Enterprise", "Developer"},
            notes="In-Memory OLTP (Enterprise/Developer)",
        ),
        "graph_database": FeatureRequirement(
            min_version=DatabaseVersion(14, 0),  # SQL Server 2017
            notes="Graph database features",
        ),
    }

    # DB2 capabilities
    DB2_FEATURES: Dict[str, FeatureRequirement] = {
        "json_data_type": FeatureRequirement(
            min_version=DatabaseVersion(10, 5),
            notes="JSON data type (DB2 10.5+)",
        ),
        "temporal_tables": FeatureRequirement(
            min_version=DatabaseVersion(10, 1),
            notes="Temporal tables (DB2 10.1+)",
        ),
        "row_access_control": FeatureRequirement(
            min_version=DatabaseVersion(10, 5),
            notes="Row and column access control",
        ),
    }

    # Combined feature matrix
    FEATURE_MATRIX: Dict[str, Dict[str, FeatureRequirement]] = {
        "postgresql": POSTGRESQL_FEATURES,
        "oracle": ORACLE_FEATURES,
        "mysql": MYSQL_FEATURES,
        "sqlserver": SQLSERVER_FEATURES,
        "db2": DB2_FEATURES,
    }

    @classmethod
    def get_feature_requirement(cls, dialect: str, feature: str) -> Optional[FeatureRequirement]:
        """
        Get feature requirement for a dialect.

        Args:
            dialect: Database dialect
            feature: Feature name

        Returns:
            FeatureRequirement or None if not found
        """
        dialect_features = cls.FEATURE_MATRIX.get(dialect.lower(), {})
        return dialect_features.get(feature)

    @classmethod
    def check_feature_availability(
        cls,
        dialect: str,
        feature: str,
        version: DatabaseVersion,
        edition: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a feature is available for given version and edition.

        Args:
            dialect: Database dialect
            feature: Feature name
            version: Database version
            edition: Optional edition name

        Returns:
            Tuple of (is_available, reason_if_not)
        """
        requirement = cls.get_feature_requirement(dialect, feature)
        if not requirement:
            return False, f"Feature '{feature}' not defined for {dialect}"

        # Check version
        if requirement.min_version and version < requirement.min_version:
            return False, f"Requires {dialect} {requirement.min_version}, but detected {version}"

        if requirement.max_version and version >= requirement.max_version:
            return False, f"Feature deprecated in {dialect} {requirement.max_version}"

        # Check edition
        if requirement.editions and edition:
            if edition not in requirement.editions:
                return (
                    False,
                    f"Feature requires {dialect} {', '.join(requirement.editions)} edition",
                )

        return True, None

    @classmethod
    def get_available_features(
        cls,
        dialect: str,
        version: DatabaseVersion,
        edition: Optional[str] = None,
    ) -> List[str]:
        """
        Get list of available features for a version and edition.

        Args:
            dialect: Database dialect
            version: Database version
            edition: Optional edition name

        Returns:
            List of available feature names
        """
        dialect_features = cls.FEATURE_MATRIX.get(dialect.lower(), {})
        available = []

        for feature, requirement in dialect_features.items():
            is_available, _ = cls.check_feature_availability(dialect, feature, version, edition)
            if is_available:
                available.append(feature)

        return available

    @classmethod
    def get_unsupported_features(
        cls,
        dialect: str,
        version: DatabaseVersion,
        edition: Optional[str] = None,
    ) -> List[tuple[str, str]]:
        """
        Get list of unsupported features with reasons.

        Args:
            dialect: Database dialect
            version: Database version
            edition: Optional edition name

        Returns:
            List of (feature_name, reason) tuples
        """
        dialect_features = cls.FEATURE_MATRIX.get(dialect.lower(), {})
        unsupported = []

        for feature, requirement in dialect_features.items():
            is_available, reason = cls.check_feature_availability(
                dialect, feature, version, edition
            )
            if not is_available:
                unsupported.append((feature, reason or "Unknown reason"))

        return unsupported
