"""Safety checker for validating changes before execution.

This module provides safety checks for database schema changes to help
prevent data loss and ensure safe migrations.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from core.sql_model.table import Table

logger = logging.getLogger(__name__)

# When ``ProviderRegistry`` has no plugin for ``SafetyChecker.dialect``, quirks
# resolve to :class:`~db.base_quirks.BaseQuirks` with no schema hints. Historically
# ``SafetyChecker`` fell back to PostgreSQL's default for these cases so existence
# checks stay schema-qualified against ``public`` (common for PG-compatible URLs).
_UNKNOWN_DIALECT_DEFAULT_SCHEMA = "public"


@dataclass
class SafetyCheckResult:
    """Result of a safety check."""

    safe: bool
    error: Optional[str] = None
    suggestion: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """String representation."""
        if self.safe:
            if self.warnings:
                return f"Safe (with warnings: {', '.join(self.warnings)})"
            return "Safe"
        return f"Unsafe: {self.error}"

    def add_warning(self, warning: str) -> None:
        """Add a warning to the result."""
        self.warnings.append(warning)


# Type compatibility mappings for common safe conversions
# Format: {(from_type, to_type): is_safe}
SAFE_TYPE_CONVERSIONS: Dict[str, Set[str]] = {
    # Integer types - safe to widen
    "tinyint": {
        "smallint",
        "int",
        "integer",
        "bigint",
        "numeric",
        "decimal",
        "float",
        "double",
        "real",
    },
    "smallint": {"int", "integer", "bigint", "numeric", "decimal", "float", "double", "real"},
    "int": {"bigint", "numeric", "decimal", "float", "double", "real"},
    "integer": {"bigint", "numeric", "decimal", "float", "double", "real"},
    "bigint": {"numeric", "decimal", "float", "double", "real"},
    # Float types
    "real": {"float", "double", "double precision"},
    "float": {"double", "double precision"},
    # String types - VARCHAR to TEXT is safe
    "char": {"varchar", "nvarchar", "text", "ntext", "clob"},
    "varchar": {"text", "ntext", "clob", "nvarchar"},
    "nchar": {"nvarchar", "ntext"},
    "nvarchar": {"ntext", "text"},
    # Date/time - date to datetime is safe
    "date": {"datetime", "datetime2", "timestamp"},
    "time": {"datetime", "datetime2", "timestamp"},
}

# Types that use size (single number in parentheses represents length)
SIZE_BASED_TYPES: Set[str] = {
    "char",
    "varchar",
    "nchar",
    "nvarchar",
    "character",
    "character varying",
    "binary",
    "varbinary",
    "bit",
}

# Types that use precision/scale (number in parentheses represents precision, not length)
PRECISION_BASED_TYPES: Set[str] = {
    "decimal",
    "numeric",
    "number",
    "float",
    "real",
    "double",
    "double precision",
}


class SafetyChecker:
    """Checks safety of database changes before execution.

    This class provides methods to validate schema changes for potential
    data loss or integrity issues before they are applied.
    """

    def __init__(self, dialect: str = "postgresql"):  # lint: allow-dialect-string
        """Initialize the safety checker.

        Args:
            dialect: SQL dialect (postgresql, sqlserver, oracle, mysql, db2)
        """
        from db.provider_registry import ProviderRegistry

        self.logger = logging.getLogger(__name__)
        self.dialect = dialect.lower()
        self._quirks = ProviderRegistry.get_quirks(self.dialect)

    def check_not_null_constraint(
        self, table: Table, column: str, provider: Optional[Any] = None
    ) -> SafetyCheckResult:
        """Check if column has NULL values before setting NOT NULL.

        Args:
            table: Table object
            column: Column name
            provider: Database provider (optional, for live checks)

        Returns:
            SafetyCheckResult indicating if adding NOT NULL is safe
        """
        if provider is None:
            # Without provider, we can't check - return warning
            return SafetyCheckResult(
                safe=False,
                error="Cannot verify NULL values without database connection",
                suggestion="Connect to database or provide default value for existing NULL rows",
            )

        # Generate check SQL based on dialect
        schema = table.schema or self._get_default_schema()
        formatted_table = self._format_table_name(schema, table.name)
        quoted_column = self._quote_identifier(column)
        check_sql = (
            f"SELECT COUNT(*) as null_count FROM {formatted_table} WHERE {quoted_column} IS NULL"
        )

        try:
            # Execute query using provider
            if hasattr(provider, "execute_query"):
                results = provider.execute_query(check_sql)
                if results and len(results) > 0:
                    null_count = results[0].get("null_count", results[0].get("NULL_COUNT", 0))
                    if isinstance(null_count, (int, float)) and null_count > 0:
                        return SafetyCheckResult(
                            safe=False,
                            error=f"Column {column} contains {int(null_count)} NULL values",
                            suggestion=f"Update NULL values with: UPDATE {formatted_table} SET {quoted_column} = <default_value> WHERE {quoted_column} IS NULL",
                            details={"null_count": int(null_count)},
                        )
                    return SafetyCheckResult(
                        safe=True,
                        details={"null_count": 0},
                    )

            # Fallback if provider doesn't have expected method
            self.logger.warning(
                "Provider does not support execute_query - cannot verify NULL values"
            )
            return SafetyCheckResult(
                safe=False,
                error="Provider does not support safety check queries",
                suggestion="Manual verification required",
            )

        except Exception as e:
            self.logger.warning(f"Error checking NULL values: {e}")
            return SafetyCheckResult(
                safe=False,
                error=f"Error checking NULL values: {str(e)}",
                suggestion="Manual verification required",
            )

    def check_type_compatibility(
        self, old_type: str, new_type: str, dialect: Optional[str] = None
    ) -> SafetyCheckResult:
        """Check if type change is compatible (won't cause data loss).

        Args:
            old_type: Current column type
            new_type: New column type
            dialect: SQL dialect (uses instance dialect if not specified)

        Returns:
            SafetyCheckResult indicating if type change is safe
        """
        dialect = (dialect or self.dialect).lower()

        # Normalize types for comparison
        old_lower = self._normalize_type(old_type)
        new_lower = self._normalize_type(new_type)
        old_base = self._extract_base_type(old_lower)
        new_base = self._extract_base_type(new_lower)

        # Same type is always compatible
        if old_lower == new_lower:
            return SafetyCheckResult(safe=True)

        # Same base type - check size or precision depending on type
        if old_base == new_base:
            # Check if this is a size-based type (VARCHAR, CHAR, etc.)
            if self._is_size_based_type(old_base):
                old_size = self._extract_size(old_lower)
                new_size = self._extract_size(new_lower)

                if old_size is not None and new_size is not None:
                    if new_size >= old_size:
                        return SafetyCheckResult(safe=True)
                    else:
                        return SafetyCheckResult(
                            safe=False,
                            error=f"Reducing size from {old_type} to {new_type} may truncate data",
                            suggestion="Verify no data exceeds new size limit",
                            details={"old_size": old_size, "new_size": new_size},
                        )

            # Check if this is a precision-based type (NUMERIC, DECIMAL, etc.)
            elif self._is_precision_based_type(old_base):
                old_precision = self._extract_precision(old_lower)
                new_precision = self._extract_precision(new_lower)

                if old_precision and new_precision:
                    if (
                        new_precision[0] >= old_precision[0]
                        and new_precision[1] >= old_precision[1]
                    ):
                        return SafetyCheckResult(safe=True)
                    else:
                        result = SafetyCheckResult(
                            safe=False,
                            error=f"Reducing precision/scale from {old_type} to {new_type} may cause data loss",
                            suggestion="Verify no data exceeds new precision/scale",
                            details={
                                "old_precision": old_precision,
                                "new_precision": new_precision,
                            },
                        )
                        if new_precision[0] < old_precision[0]:
                            result.add_warning("Precision reduction may truncate integer part")
                        if new_precision[1] < old_precision[1]:
                            result.add_warning("Scale reduction may truncate decimal places")
                        return result

        # Check safe type conversions
        if old_base in SAFE_TYPE_CONVERSIONS:
            if new_base in SAFE_TYPE_CONVERSIONS[old_base]:
                return SafetyCheckResult(
                    safe=True,
                    details={"conversion": f"{old_base} -> {new_base}"},
                )

        # Check for potentially unsafe conversions
        unsafe_conversions = [
            # Numeric to string (might work but could lose precision)
            (
                {"int", "integer", "bigint", "float", "double", "numeric", "decimal"},
                {"char", "varchar", "nvarchar", "text"},
            ),
            # Date/time conversions that might lose data
            ({"datetime", "datetime2", "timestamp"}, {"date"}),  # Loses time component
            ({"datetime", "datetime2", "timestamp"}, {"time"}),  # Loses date component
        ]

        for from_types, to_types in unsafe_conversions:
            if old_base in from_types and new_base in to_types:
                return SafetyCheckResult(
                    safe=False,
                    error=f"Type change from {old_type} to {new_type} may cause data loss",
                    suggestion="Verify data compatibility or use explicit conversion",
                    details={"from_type": old_base, "to_type": new_base},
                )

        # Default: return warning for unknown conversions (conservative)
        return SafetyCheckResult(
            safe=False,
            error=f"Type change from {old_type} to {new_type} may cause data loss",
            suggestion="Verify data compatibility or use explicit conversion with CAST/CONVERT",
        )

    def check_column_references(
        self, table: Table, column: str, provider: Optional[Any] = None
    ) -> SafetyCheckResult:
        """Check if column is referenced by other database objects.

        Checks for references in:
        - Foreign key constraints
        - Indexes
        - Views (when the provider exposes catalog queries)
        - Stored procedures (when the provider exposes catalog queries)

        Args:
            table: Table object
            column: Column name to check
            provider: Database provider (optional, for live checks)

        Returns:
            SafetyCheckResult with reference information
        """
        if provider is None:
            return SafetyCheckResult(
                safe=False,
                error="Cannot check column references without database connection",
                suggestion="Connect to database to check for foreign keys, indexes, and views referencing this column",
            )

        schema = table.schema or self._get_default_schema()
        references: List[Dict[str, str]] = []

        try:
            # Check for foreign key references using parameterized queries
            fk_query, fk_params = self._get_fk_reference_query(schema, table.name, column)
            if fk_query and hasattr(provider, "execute_query"):
                fk_results = provider.execute_query(fk_query, fk_params)
                for fk in fk_results or []:
                    references.append(
                        {
                            "type": "FOREIGN_KEY",
                            "name": fk.get("constraint_name", fk.get("CONSTRAINT_NAME", "unknown")),
                            "referencing_table": fk.get(
                                "table_name", fk.get("TABLE_NAME", "unknown")
                            ),
                        }
                    )

            # Check for index references using parameterized queries
            idx_query, idx_params = self._get_index_reference_query(schema, table.name, column)
            if idx_query and hasattr(provider, "execute_query"):
                idx_results = provider.execute_query(idx_query, idx_params)
                for idx in idx_results or []:
                    references.append(
                        {
                            "type": "INDEX",
                            "name": idx.get("index_name", idx.get("INDEX_NAME", "unknown")),
                        }
                    )

            if references:
                ref_summary = ", ".join([f"{r['type']}: {r['name']}" for r in references])
                return SafetyCheckResult(
                    safe=False,
                    error=f"Column {column} is referenced by: {ref_summary}",
                    suggestion="Drop or modify dependent objects before dropping this column",
                    details={"references": references},
                )

            return SafetyCheckResult(
                safe=True,
                details={"references": []},
            )

        except Exception as e:
            self.logger.warning(f"Error checking column references: {e}")
            return SafetyCheckResult(
                safe=False,
                error=f"Error checking column references: {str(e)}",
                suggestion="Manual verification required",
            )

    def check_table_has_data(
        self, table: Table, provider: Optional[Any] = None
    ) -> SafetyCheckResult:
        """Check if table contains data before dropping.

        Args:
            table: Table object
            provider: Database provider (optional, for live checks)

        Returns:
            SafetyCheckResult with row count information
        """
        if provider is None:
            return SafetyCheckResult(
                safe=False,
                error="Cannot check table data without database connection",
                suggestion="Connect to database to verify table is empty before dropping",
            )

        schema = table.schema or self._get_default_schema()
        formatted_table = self._format_table_name(schema, table.name)

        try:
            # Use TOP/LIMIT 1 with EXISTS for performance on large tables
            check_sql = self._quirks.existence_check_sql(formatted_table)

            if hasattr(provider, "execute_query"):
                results = provider.execute_query(check_sql)
                if results and len(results) > 0:
                    has_data = results[0].get("has_data", results[0].get("HAS_DATA", 0))
                    if has_data:
                        return SafetyCheckResult(
                            safe=False,
                            error=f"Table {table.name} contains data",
                            suggestion="Back up data before dropping, or use TRUNCATE first if data is not needed",
                            details={"has_data": True},
                        )
                    return SafetyCheckResult(
                        safe=True,
                        details={"has_data": False},
                    )

            return SafetyCheckResult(
                safe=False,
                error="Provider does not support safety check queries",
                suggestion="Manual verification required",
            )

        except Exception as e:
            self.logger.warning(f"Error checking table data: {e}")
            return SafetyCheckResult(
                safe=False,
                error=f"Error checking table data: {str(e)}",
                suggestion="Manual verification required",
            )

    def _get_default_schema(self) -> str:
        """Get default schema for the dialect."""
        from db.provider_registry import ProviderRegistry

        explicit = self._quirks.default_schema_name or self._quirks.parser_default_schema
        if explicit:
            return explicit
        if ProviderRegistry.canonical_dialect_name(self.dialect) is not None:
            return ""
        return _UNKNOWN_DIALECT_DEFAULT_SCHEMA

    def _format_table_name(self, schema: str, table_name: str) -> str:
        """Format schema-qualified table name based on dialect."""
        open_q = self._quirks.quote_open
        close_q = self._quirks.quote_close
        clean_schema = schema.replace(close_q, close_q + close_q)
        clean_table = table_name.replace(close_q, close_q + close_q)
        if schema:
            return f"{open_q}{clean_schema}{close_q}.{open_q}{clean_table}{close_q}"
        return f"{open_q}{clean_table}{close_q}"

    def _quote_identifier(self, identifier: str) -> str:
        """Quote identifier based on dialect."""
        open_q = self._quirks.quote_open
        close_q = self._quirks.quote_close
        return f"{open_q}{identifier.replace(close_q, close_q + close_q)}{close_q}"

    def _normalize_type(self, type_str: str) -> str:
        """Normalize type string for comparison."""
        return type_str.lower().strip()

    def _extract_base_type(self, type_str: str) -> str:
        """Extract base type without size/precision."""
        # Remove anything in parentheses
        return re.sub(r"\([^)]*\)", "", type_str).strip()

    def _is_size_based_type(self, base_type: str) -> bool:
        """Check if this is a size-based type (VARCHAR, CHAR, etc.)."""
        return base_type.lower() in SIZE_BASED_TYPES

    def _is_precision_based_type(self, base_type: str) -> bool:
        """Check if this is a precision-based type (DECIMAL, NUMERIC, etc.)."""
        return base_type.lower() in PRECISION_BASED_TYPES

    def _extract_size(self, type_str: str) -> Optional[int]:
        """Extract size from size-based type strings like VARCHAR(100).

        Only returns a value for size-based types (VARCHAR, CHAR, etc.).
        Returns None for precision-based types (DECIMAL, NUMERIC, etc.).
        """
        base_type = self._extract_base_type(type_str)

        # Only extract size for size-based types
        if not self._is_size_based_type(base_type):
            return None

        match = re.search(r"\((\d+)\)", type_str)
        if match:
            return int(match.group(1))
        return None

    def _extract_precision(self, type_str: str) -> Optional[Tuple[int, int]]:
        """Extract precision and scale from type like NUMERIC(10,2).

        Returns:
            Tuple of (precision, scale) or None if not a precision-based type.
        """
        base_type = self._extract_base_type(type_str)

        # Only extract precision for precision-based types
        if not self._is_precision_based_type(base_type):
            return None

        # Check for precision,scale format: NUMERIC(10,2)
        match = re.search(r"\((\d+)\s*,\s*(\d+)\)", type_str)
        if match:
            return (int(match.group(1)), int(match.group(2)))

        # Single value is precision with scale 0: NUMERIC(10) -> (10, 0)
        match = re.search(r"\((\d+)\)", type_str)
        if match:
            return (int(match.group(1)), 0)

        return None

    def _get_fk_reference_query(
        self, schema: str, table: str, column: str
    ) -> Tuple[Optional[str], List[Any]]:
        """Get parameterized query to find foreign keys referencing this column."""
        return self._quirks.fk_reference_query(schema, table, column)

    def _get_index_reference_query(
        self, schema: str, table: str, column: str
    ) -> Tuple[Optional[str], List[Any]]:
        """Get parameterized query to find indexes on this column."""
        return self._quirks.index_reference_query(schema, table, column)
