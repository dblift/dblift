"""
Consistency validator for schema introspection.

Verifies that relationships are complete and consistent.
"""

import logging
from typing import Dict, List, Optional, Set

from core.sql_model.base import ConstraintType
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.sql_model.view import View
from core.validation.result import ValidationResult, ValidationSeverity
from db.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class ConsistencyValidator:
    """
    Validates consistency of schema relationships.

    Checks:
    - Foreign key references exist
    - Index references valid columns
    - Constraint relationships are valid
    - View dependencies exist
    """

    def __init__(self):
        """Initialize the consistency validator."""

    def validate_foreign_keys(
        self,
        tables: List[Table],
        schema: str,
    ) -> ValidationResult:
        """Validate foreign key references.

        Args:
            tables: List of tables to validate
            schema: Schema name

        Returns:
            ValidationResult with consistency issues
        """
        result = ValidationResult(validator_name="ConsistencyValidator")

        # Build table and column index
        table_map: Dict[str, Table] = {}
        column_map: Dict[tuple[str, str], Set[str]] = {}

        for table in tables:
            table_map[table.name.lower()] = table
            column_map[(schema.lower(), table.name.lower())] = {
                col.name.lower() for col in table.columns
            }

        # Validate each foreign key
        for table in tables:
            for constraint in table.constraints:
                if constraint.constraint_type == ConstraintType.FOREIGN_KEY:
                    ref_table = constraint.reference_table
                    ref_schema = getattr(constraint, "reference_schema", None) or schema

                    if not ref_table:
                        result.add_issue(
                            ValidationSeverity.ERROR,
                            f"Foreign key {constraint.name or 'unnamed'} missing reference table",
                            object_type="constraint",
                            object_name=constraint.name or "unnamed",
                            property_name="reference_table",
                        )
                        continue

                    # Check if referenced table exists
                    ref_table_lower = ref_table.lower()
                    if ref_table_lower not in table_map:
                        result.add_issue(
                            ValidationSeverity.ERROR,
                            f"Foreign key references non-existent table: {ref_schema}.{ref_table}",
                            object_type="constraint",
                            object_name=constraint.name or "unnamed",
                            property_name="reference_table",
                            expected_value=f"{ref_schema}.{ref_table}",
                            actual_value="not found",
                        )
                        continue

                    # Check if referenced columns exist
                    if constraint.reference_columns:
                        ref_table_obj = table_map[ref_table_lower]
                        ref_columns = {col.name.lower() for col in ref_table_obj.columns}
                        for ref_col in constraint.reference_columns:
                            if ref_col.lower() not in ref_columns:
                                result.add_issue(
                                    ValidationSeverity.ERROR,
                                    f"Foreign key references non-existent column: {ref_table}.{ref_col}",
                                    object_type="constraint",
                                    object_name=constraint.name or "unnamed",
                                    property_name="reference_columns",
                                    expected_value=ref_col,
                                    actual_value="not found",
                                )

                    # Check if local columns exist
                    for local_col in constraint.column_names:
                        table_columns = column_map.get((schema.lower(), table.name.lower()), set())
                        if local_col.lower() not in table_columns:
                            result.add_issue(
                                ValidationSeverity.ERROR,
                                f"Foreign key references non-existent local column: {table.name}.{local_col}",
                                object_type="constraint",
                                object_name=constraint.name or "unnamed",
                                property_name="column_names",
                                expected_value=local_col,
                                actual_value="not found",
                            )

        return result

    def validate_indexes(
        self,
        tables: List[Table],
        indexes: List[Index],
        schema: str,
        views: Optional[List[View]] = None,
    ) -> ValidationResult:
        """Validate index column references.

        Args:
            tables: List of tables
            indexes: List of indexes
            schema: Schema name
            views: Optional list of views (included so indexes on SQL Server
                indexed views are not flagged as referencing a non-existent table)

        Returns:
            ValidationResult with consistency issues
        """
        result = ValidationResult(validator_name="ConsistencyValidator")

        # Build column index — include views so indexed-view indexes are valid
        column_map: Dict[tuple[str, str], Set[str]] = {}
        for obj in [*(tables or []), *(views or [])]:
            column_map[(schema.lower(), obj.name.lower())] = {
                (col if isinstance(col, str) else col.name).lower()
                for col in getattr(obj, "columns", [])
            }

        # Validate each index
        for index in indexes:
            table_name = index.table_name.lower()
            table_key = (schema.lower(), table_name)

            if table_key not in column_map:
                result.add_issue(
                    ValidationSeverity.ERROR,
                    f"Index references non-existent table: {schema}.{index.table_name}",
                    object_type="index",
                    object_name=index.name,
                    property_name="table_name",
                    expected_value=index.table_name,
                    actual_value="not found",
                )
                continue

            table_columns = column_map[table_key]

            # Check index columns
            for col in index.columns:
                # Handle expression columns (may contain functions)
                if "(" in col or ")" in col:
                    continue  # Skip expression columns

                col_lower = col.lower().strip("\"'`[]")
                index_dialect = getattr(index, "dialect", None)
                if col_lower == "*" and isinstance(index_dialect, str):
                    if ProviderRegistry.get_quirks(index_dialect.lower()).is_nosql:
                        continue  # NoSQL dialects use automatic indexing
                if col_lower not in table_columns:
                    result.add_issue(
                        ValidationSeverity.ERROR,
                        f"Index references non-existent column: {index.table_name}.{col}",
                        object_type="index",
                        object_name=index.name,
                        property_name="columns",
                        expected_value=col,
                        actual_value="not found",
                    )

        return result

    def validate_constraints(
        self,
        tables: List[Table],
        schema: str,
    ) -> ValidationResult:
        """Validate constraint column references.

        Args:
            tables: List of tables
            schema: Schema name

        Returns:
            ValidationResult with consistency issues
        """
        result = ValidationResult(validator_name="ConsistencyValidator")

        # Build column index
        column_map: Dict[tuple[str, str], Set[str]] = {}
        for table in tables:
            column_map[(schema.lower(), table.name.lower())] = {
                col.name.lower() for col in table.columns
            }

        # Validate each constraint
        for table in tables:
            table_key = (schema.lower(), table.name.lower())
            table_columns = column_map.get(table_key, set())

            for constraint in table.constraints:
                # Check constraint columns exist
                for col_name in constraint.column_names:
                    if col_name.lower() not in table_columns:
                        result.add_issue(
                            ValidationSeverity.ERROR,
                            f"Constraint references non-existent column: {table.name}.{col_name}",
                            object_type="constraint",
                            object_name=constraint.name or "unnamed",
                            property_name="column_names",
                            expected_value=col_name,
                            actual_value="not found",
                        )

        return result

    def validate_all(
        self,
        tables: List[Table],
        indexes: Optional[List[Index]] = None,
        views: Optional[List[View]] = None,
        schema: str = "public",
    ) -> ValidationResult:
        """Validate all consistency checks.

        Args:
            tables: List of tables
            indexes: Optional list of indexes
            views: Optional list of views
            schema: Schema name

        Returns:
            ValidationResult with all consistency issues
        """
        result = ValidationResult(validator_name="ConsistencyValidator")

        # Validate foreign keys
        fk_result = self.validate_foreign_keys(tables, schema)
        result.issues.extend(fk_result.issues)
        if not fk_result.passed:
            result.passed = False

        # Validate constraints
        constraint_result = self.validate_constraints(tables, schema)
        result.issues.extend(constraint_result.issues)
        if not constraint_result.passed:
            result.passed = False

        # Validate indexes if provided
        if indexes:
            index_result = self.validate_indexes(tables, indexes, schema, views=views)
            result.issues.extend(index_result.issues)
            if not index_result.passed:
                result.passed = False

        result.metadata["table_count"] = len(tables)
        result.metadata["index_count"] = len(indexes) if indexes else 0
        result.metadata["view_count"] = len(views) if views else 0

        return result
