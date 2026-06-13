"""Diff Analyzer for validating and analyzing schema diffs.

This module provides analysis of schema diffs to detect safety issues,
dependencies, and breaking changes before generating SQL.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from core.comparison.diff_models import (
    ColumnDiff,
    DiffResult,
    DiffSeverity,
    SchemaDiff,
    TableDiff,
)
from core.migration.snapshots.schema_snapshot import SchemaSnapshotPayload

logger = logging.getLogger(__name__)


@dataclass
class BreakingChange:
    """Represents a breaking change that might affect applications."""

    change_type: str
    object_name: str
    description: str
    severity: DiffSeverity
    affected_objects: List[str] = field(default_factory=list)


@dataclass
class DependencyNode:
    """Represents a dependency node in the dependency graph."""

    object_name: str
    object_type: str
    depends_on: List[str] = field(default_factory=list)
    depended_by: List[str] = field(default_factory=list)


@dataclass
class DependencyGraph:
    """Represents dependencies between objects."""

    nodes: Dict[str, DependencyNode] = field(default_factory=dict)

    def add_node(self, name: str, object_type: str) -> None:
        """Add a node to the graph."""
        if name not in self.nodes:
            self.nodes[name] = DependencyNode(name, object_type)

    def add_dependency(self, from_name: str, to_name: str) -> None:
        """Add a dependency from one object to another."""
        if from_name not in self.nodes:
            raise ValueError(f"Node {from_name} not found in graph")
        if to_name not in self.nodes:
            raise ValueError(f"Node {to_name} not found in graph")

        if to_name not in self.nodes[from_name].depends_on:
            self.nodes[from_name].depends_on.append(to_name)
        if from_name not in self.nodes[to_name].depended_by:
            self.nodes[to_name].depended_by.append(from_name)

    def get_execution_order(self) -> List[str]:
        """Get topological sort of execution order."""
        # Simple topological sort
        result: List[str] = []
        visited: Set[str] = set()
        temp_visited: Set[str] = set()

        def visit(node_name: str) -> None:
            if node_name in temp_visited:
                # Cycle detected - log warning but continue
                logger.warning(f"Circular dependency detected involving {node_name}")
                return
            if node_name in visited:
                return

            temp_visited.add(node_name)
            node = self.nodes[node_name]
            for dep in node.depends_on:
                visit(dep)
            temp_visited.remove(node_name)
            visited.add(node_name)
            result.append(node_name)

        for node_name in self.nodes:
            if node_name not in visited:
                visit(node_name)

        return result


@dataclass
class ValidationResult:
    """Result of validating a change."""

    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)


@dataclass
class SafetyCheck:
    """Represents a safety check result."""

    safe: bool
    error_message: Optional[str] = None
    warning_message: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class DiffAnalysis:
    """Result of analyzing a schema diff."""

    is_valid: bool
    validation_result: ValidationResult
    safety_checks: List[SafetyCheck] = field(default_factory=list)
    breaking_changes: List[BreakingChange] = field(default_factory=list)
    dependency_graph: Optional[DependencyGraph] = None
    execution_order: List[str] = field(default_factory=list)


class DiffAnalyzer:
    """Analyzes schema diffs for validation, safety, and dependencies."""

    def __init__(self):
        """Initialize the diff analyzer."""
        self.logger = logging.getLogger(__name__)

    def analyze_diff(
        self, diff: SchemaDiff, current_state: Optional[SchemaSnapshotPayload] = None
    ) -> DiffAnalysis:
        """Analyze diff and return analysis with safety checks.

        Args:
            diff: Schema diff to analyze
            current_state: Current database state (optional, for safety checks)

        Returns:
            DiffAnalysis with validation, safety checks, and dependencies
        """
        validation_result = self._validate_diff(diff)
        safety_checks = self._check_safety(diff, current_state)
        breaking_changes = self._detect_breaking_changes(diff)
        dependency_graph = self._calculate_dependencies(diff)
        execution_order = dependency_graph.get_execution_order() if dependency_graph else []

        is_valid = validation_result.is_valid and all(check.safe for check in safety_checks)

        return DiffAnalysis(
            is_valid=is_valid,
            validation_result=validation_result,
            safety_checks=safety_checks,
            breaking_changes=breaking_changes,
            dependency_graph=dependency_graph,
            execution_order=execution_order,
        )

    def validate_change(self, change: DiffResult) -> ValidationResult:
        """Validate if change is safe to apply.

        Args:
            change: Diff result to validate

        Returns:
            ValidationResult with validation status
        """
        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []

        if isinstance(change, ColumnDiff):
            # Validate column changes
            if change.data_type_diff:
                # Type changes need validation
                expected_type, actual_type = change.data_type_diff
                if not self._is_type_compatible(expected_type, actual_type):
                    errors.append(
                        f"Type change from {actual_type} to {expected_type} may not be compatible"
                    )

            if change.nullable_diff:
                expected_nullable, actual_nullable = change.nullable_diff
                if not expected_nullable and actual_nullable:
                    warnings.append("Setting NOT NULL on nullable column - check for NULL values")

        elif isinstance(change, TableDiff):
            # Validate table changes
            if change.missing_columns:
                errors.append(
                    f"Table {change.table_name} is missing {len(change.missing_columns)} columns"
                )

        is_valid = len(errors) == 0

        return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings, info=info)

    def check_data_safety(
        self, change: DiffResult, current_state: Optional[SchemaSnapshotPayload] = None
    ) -> SafetyCheck:
        """Check if change will cause data loss or errors.

        Args:
            change: Diff result to check
            current_state: Current database state

        Returns:
            SafetyCheck result
        """
        if isinstance(change, ColumnDiff):
            # Check NOT NULL constraint
            if change.nullable_diff:
                expected_nullable, actual_nullable = change.nullable_diff
                if not expected_nullable and actual_nullable:
                    # Setting NOT NULL - need to check for NULL values
                    return SafetyCheck(
                        safe=False,
                        error_message="Cannot set NOT NULL: column may contain NULL values",
                        suggestion="Update NULL values first or use DEFAULT value",
                    )

            # Check type changes
            if change.data_type_diff:
                expected_type, actual_type = change.data_type_diff
                if not self._is_type_compatible(expected_type, actual_type):
                    return SafetyCheck(
                        safe=False,
                        error_message=f"Type change from {actual_type} to {expected_type} may cause data loss",
                        suggestion="Verify data compatibility or use explicit conversion",
                    )

        return SafetyCheck(safe=True)

    def _validate_diff(self, diff: SchemaDiff) -> ValidationResult:
        """Validate the entire diff."""
        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []

        # Validate all table diffs
        for table_diff in diff.modified_tables:
            table_validation = self.validate_change(table_diff)
            errors.extend(table_validation.errors)
            warnings.extend(table_validation.warnings)
            info.extend(table_validation.info)

        # Check for impossible changes
        if diff.missing_tables and diff.extra_tables:
            # Check if we're trying to drop and create same table (name collision)
            missing_set = set(diff.missing_tables)
            extra_set = set(diff.extra_tables)
            collisions = missing_set & extra_set
            if collisions:
                errors.append(
                    f"Name collision detected: {collisions} appear in both missing and extra"
                )

        is_valid = len(errors) == 0

        return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings, info=info)

    def _check_safety(
        self,
        diff: SchemaDiff,
        current_state: Optional[SchemaSnapshotPayload] = None,
    ) -> List[SafetyCheck]:
        """Check safety of all changes."""
        safety_checks: List[SafetyCheck] = []

        # Check table changes
        for table_diff in diff.modified_tables:
            for column_diff in table_diff.modified_columns:
                check = self.check_data_safety(column_diff, current_state)
                safety_checks.append(check)

        return safety_checks

    def _detect_breaking_changes(self, diff: SchemaDiff) -> List[BreakingChange]:
        """Detect changes that might break applications."""
        breaking_changes: List[BreakingChange] = []

        # Check for column removals
        for table_diff in diff.modified_tables:
            if table_diff.extra_columns:
                for col_name in table_diff.extra_columns:
                    breaking_changes.append(
                        BreakingChange(
                            change_type="column_removal",
                            object_name=f"{table_diff.table_name}.{col_name}",
                            description=f"Column {col_name} will be removed from table {table_diff.table_name}",
                            severity=DiffSeverity.ERROR,
                        )
                    )

            # Check for type changes
            for column_diff in table_diff.modified_columns:
                if column_diff.data_type_diff:
                    expected_type, actual_type = column_diff.data_type_diff
                    breaking_changes.append(
                        BreakingChange(
                            change_type="type_change",
                            object_name=f"{table_diff.table_name}.{column_diff.column_name}",
                            description=f"Column type changed from {actual_type} to {expected_type}",
                            severity=DiffSeverity.ERROR,
                        )
                    )

        # Check for table removals
        if diff.extra_tables:
            for table_name in diff.extra_tables:
                breaking_changes.append(
                    BreakingChange(
                        change_type="table_removal",
                        object_name=table_name,
                        description=f"Table {table_name} will be removed",
                        severity=DiffSeverity.ERROR,
                    )
                )

        return breaking_changes

    def _calculate_dependencies(self, diff: SchemaDiff) -> DependencyGraph:
        """Calculate execution order based on dependencies."""
        graph = DependencyGraph()

        # Add nodes for all tables
        for table_name in diff.missing_tables:
            graph.add_node(table_name, "table")

        for table_diff in diff.modified_tables:
            graph.add_node(table_diff.table_name, "table")

        # BACKLOG P2 (story 10-26): Implémenter détection de dépendances FK dans _calculate_dependencies()
        # Raison: Nécessite accès aux FK dans SchemaDiff — structure à valider; gestion cycles FK circulaires
        # Impact: Sans dépendances, l'ordre de création des tables avec FK est non-déterministe
        #   → peut causer "FK constraint violation" lors de la création de tables dans le mauvais ordre
        # Approche: SchemaDiff.missing_tables est List[str] (noms uniquement, voir diff_models.py:1451)
        #   Prérequis: changer missing_tables en List[Table] OU ajouter un champ missing_table_defs: Dict[str, Table]
        #   Ensuite: pour chaque Table dans missing_tables, itérer table.foreign_keys
        #   Pour chaque FK, ajouter une arête: table_référencée → table_courante
        #   Détecter les cycles (FK circulaires) et les reporter sans bloquer
        # Dépendances: Modifier SchemaDiff pour exposer les définitions complètes des tables manquantes
        # Ref: voir _bmad-output/implementation-artifacts/10-26-todos-documenter-ou-implementer.md

        return graph

    def _is_type_compatible(self, expected_type: str, actual_type: str) -> bool:
        """Check if type change is compatible.

        This is a simplified check. A full implementation would need
        database-specific type compatibility rules.

        Args:
            expected_type: Expected type
            actual_type: Actual type

        Returns:
            True if types are compatible
        """
        # Normalize types for comparison
        expected_lower = expected_type.lower().strip()
        actual_lower = actual_type.lower().strip()

        # Same type is always compatible
        if expected_lower == actual_lower:
            return True

        # Check for size increases (generally safe)
        if "varchar" in expected_lower and "varchar" in actual_lower:
            # Extract sizes if possible
            try:
                expected_size = self._extract_size(expected_lower)
                actual_size = self._extract_size(actual_lower)
                if expected_size and actual_size:
                    return expected_size >= actual_size
            except (ValueError, AttributeError):
                pass

        # Default: assume incompatible (conservative)
        return False

    def _extract_size(self, type_str: str) -> Optional[int]:
        """Extract size from type string like VARCHAR(100)."""
        match = re.search(r"\((\d+)\)", type_str)
        if match:
            return int(match.group(1))
        return None
