"""
Canonical type mapping for SQL data types.

Provides a canonical form for all SQL data types across dialects,
enabling consistent type representation regardless of source dialect.
"""

import logging
import re
from typing import Any, Dict, Optional, Set

from db.provider_registry import ProviderRegistry

_logger = logging.getLogger(__name__)

from core.normalization.type_constants import CANONICAL_TO_VARIANTS
from core.normalization.type_mappings import (
    TYPE_ALIASES,
    VARIANT_TO_CANONICAL,
    get_version_specific_mappings,
)


class CanonicalTypeMapper:
    """
    Maps SQL data types to canonical forms.

    Canonical types are standard forms that represent the semantic meaning
    of a type regardless of dialect-specific syntax.

    Example:
        - PostgreSQL: INT, INT4, INTEGER → INTEGER
        - Oracle: NUMBER(10,0) → INTEGER
        - MySQL: INT, INTEGER → INTEGER
        - SQL Server: INT → INTEGER
    """

    # Use comprehensive mappings from type_mappings module
    CANONICAL_TYPES = CANONICAL_TO_VARIANTS

    # Reverse mapping: dialect-specific type -> canonical type
    TYPE_TO_CANONICAL: Dict[str, str] = VARIANT_TO_CANONICAL.copy()

    def __init__(self):
        """Initialize the canonical type mapper."""
        self._build_reverse_mapping()

    def _build_reverse_mapping(self):
        """Build reverse mapping from dialect types to canonical types."""
        # Use the comprehensive mapping from type_mappings
        for canonical, variants in CANONICAL_TO_VARIANTS.items():
            for variant in variants:
                self.TYPE_TO_CANONICAL[variant.upper()] = canonical

    def to_canonical(
        self,
        data_type: str,
        dialect: Optional[str] = None,
        version: Optional[str] = None,
    ) -> str:
        """Convert a data type to its canonical form.

        Args:
            data_type: Data type string (e.g., "INT", "VARCHAR2(100)")
            dialect: Optional source dialect for better mapping
            version: Optional database version for version-specific mappings

        Returns:
            Canonical type name

        Example:
            >>> mapper = CanonicalTypeMapper()
            >>> mapper.to_canonical("INT", "postgresql")
            'INTEGER'
            >>> mapper.to_canonical("VARCHAR2(100)", "oracle")
            'VARCHAR'
        """
        if not data_type:
            return data_type

        # Extract base type (without precision/scale)
        base_type = self._extract_base_type(data_type).upper()

        # Special handling for NUMBER/DECIMAL with scale=0 -> INTEGER
        if base_type in ("NUMBER", "NUMERIC", "DECIMAL"):
            # Try to extract precision and scale
            match = re.search(r"\((\d+)(?:,(\d+))?\)", data_type)
            if match:
                precision = int(match.group(1))
                scale = int(match.group(2)) if match.group(2) else 0
                if scale == 0 and precision <= 18:  # Reasonable integer range
                    return "INTEGER"

        # Check version-specific mappings first
        if dialect and version:
            for (map_dialect, map_version), mappings in get_version_specific_mappings().items():
                if map_dialect == dialect.lower() and self._version_matches(version, map_version):
                    if base_type in mappings:
                        return mappings[base_type]

        # Check type aliases
        if base_type in TYPE_ALIASES:
            base_type = TYPE_ALIASES[base_type]

        # First try direct mapping
        canonical = self.TYPE_TO_CANONICAL.get(base_type)
        if canonical:
            return canonical

        # If dialect provided, normalize first
        if dialect:
            normalized = self._normalize_type_name(data_type, dialect)
            base_normalized = self._extract_base_type(normalized or "").upper()
            canonical = self.TYPE_TO_CANONICAL.get(base_normalized)
            if canonical:
                return canonical

        # If no mapping found, return the base type as-is
        return base_type

    def _version_matches(self, version: str, pattern: str) -> bool:
        """Check if version matches pattern (e.g., "9.4+", "12.2+")."""
        if pattern.endswith("+"):
            min_version = pattern[:-1]
            try:
                min_ver = self._parse_version(min_version)
                actual_ver = self._parse_version(version)
                # Compare DatabaseVersion objects - mypy doesn't understand the comparison
                result: bool = bool(actual_ver >= min_ver)  # type: ignore[operator]
                return result
            except Exception as e:
                _logger.debug(f"Version comparison failed: {e}")
                return False
        return version == pattern

    def _parse_version(self, version_str: str) -> Any:  # DatabaseVersion
        """Parse version string to DatabaseVersion."""
        from core.introspection.version_detector import DatabaseVersion

        parts = version_str.split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return DatabaseVersion(major, minor, patch)

    @staticmethod
    def _extract_base_type(data_type: str) -> str:
        """Extract the base type name before precision, scale, array, or spacing details."""
        if not data_type:
            return data_type
        normalized = data_type.strip()
        normalized = re.sub(r"\s*\(.*$", "", normalized)
        normalized = re.sub(r"\s+.*$", "", normalized)
        normalized = normalized.rstrip("[]")
        return normalized

    def _normalize_type_name(self, data_type: str, dialect: str) -> str:
        """Apply the local alias map for dialect-specific type names."""
        base_type = self._extract_base_type(data_type).upper()
        version_mappings = get_version_specific_mappings()
        dialect_lower = dialect.lower()
        for (map_dialect, _map_version), mappings in version_mappings.items():
            if map_dialect == dialect_lower and base_type in mappings:
                return mappings[base_type]
        return TYPE_ALIASES.get(base_type, base_type)

    def get_canonical_variants(self, canonical_type: str) -> Set[str]:
        """Get all variant names for a canonical type.

        Args:
            canonical_type: Canonical type name

        Returns:
            Set of variant type names
        """
        return CANONICAL_TO_VARIANTS.get(canonical_type.upper(), set())

    def from_canonical(
        self,
        canonical_type: str,
        dialect: Optional[str] = None,
        prefer_native: bool = True,
    ) -> str:
        """Convert canonical type to dialect-specific type.

        Args:
            canonical_type: Canonical type name
            dialect: Target dialect
            prefer_native: Prefer native dialect type over generic

        Returns:
            Dialect-specific type name

        Example:
            >>> mapper = CanonicalTypeMapper()
            >>> mapper.from_canonical("INTEGER", "oracle")
            'NUMBER'
            >>> mapper.from_canonical("VARCHAR", "postgresql")
            'VARCHAR'
        """
        if not canonical_type:
            return canonical_type

        canonical_upper = canonical_type.upper()

        # Get variants for this canonical type
        variants = CANONICAL_TO_VARIANTS.get(canonical_upper, {canonical_upper})

        # If dialect specified, prefer dialect-specific variants
        if dialect:
            dialect_lower = dialect.lower()

            preferences = ProviderRegistry.get_quirks(dialect_lower).type_preferences()
            if canonical_upper in preferences:
                return preferences[canonical_upper]

        # Return first variant (usually the most common)
        return next(iter(variants)) if variants else canonical_type

    def are_same_canonical(
        self, type1: str, type2: str, dialect1: Optional[str] = None, dialect2: Optional[str] = None
    ) -> bool:
        """Check if two types map to the same canonical type.

        Args:
            type1: First data type
            type2: Second data type
            dialect1: Optional dialect for first type
            dialect2: Optional dialect for second type

        Returns:
            True if both types map to the same canonical type
        """
        canonical1 = self.to_canonical(type1, dialect1)
        canonical2 = self.to_canonical(type2, dialect2)
        return canonical1 == canonical2
