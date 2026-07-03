"""Script Organizer - Organizes generated SQL into files with dependency ordering.

This module provides functionality to organize SQL scripts into files
with proper dependency ordering and various organization strategies.
"""

import logging
from collections import defaultdict
from typing import Dict, List

from core.sql_generator.dependency_analyzer import DependencyAnalyzer
from core.sql_generator.options import OrganizationStrategy, ScriptOptions
from core.sql_model.base import SqlObject, get_object_type_name

logger = logging.getLogger(__name__)


class ScriptOrganizer:
    """Organizes SQL objects into files with dependency ordering.

    This class handles:
    - Dependency analysis and ordering
    - File organization strategies
    - Header/footer generation
    - Script formatting
    """

    def __init__(self) -> None:
        """Initialize script organizer."""
        self.dependency_analyzer = DependencyAnalyzer()

    def organize(
        self,
        objects: List[SqlObject],
        options: ScriptOptions,
    ) -> Dict[str, List[SqlObject]]:
        """Organize objects into files based on strategy.

        Args:
            objects: List of SQL objects to organize
            options: Organization options

        Returns:
            Dictionary mapping file names to lists of objects
        """
        if not objects:
            return {}

        # Filter objects if needed
        filtered_objects = self._filter_objects(objects, options)

        # Order by dependencies
        ordered_objects = self._order_by_dependencies(filtered_objects, options)

        # Organize into files
        if options.organization == OrganizationStrategy.SINGLE_FILE:
            return self._organize_single_file(ordered_objects)

        elif options.organization == OrganizationStrategy.BY_TYPE:
            return self._organize_by_type(ordered_objects)

        elif options.organization == OrganizationStrategy.BY_OBJECT:
            return self._organize_by_object(ordered_objects)

        elif options.organization == OrganizationStrategy.BY_SCHEMA:
            return self._organize_by_schema(ordered_objects)

        elif options.organization == OrganizationStrategy.BY_DEPENDENCY:
            return self._organize_by_dependency(ordered_objects)

        else:
            # Default to by_type
            return self._organize_by_type(ordered_objects)

    def _filter_objects(self, objects: List[SqlObject], options: ScriptOptions) -> List[SqlObject]:
        """Filter objects based on include/exclude options."""
        if options.include_object_types is None and not options.exclude_object_types:
            return objects

        filtered = []
        for obj in objects:
            obj_type = get_object_type_name(obj)

            # Check exclude
            if options.exclude_object_types and obj_type in options.exclude_object_types:
                continue

            # Check include
            if options.include_object_types and obj_type not in options.include_object_types:
                continue

            filtered.append(obj)

        return filtered

    def _order_by_dependencies(
        self, objects: List[SqlObject], options: ScriptOptions
    ) -> List[SqlObject]:
        """Order objects by their dependencies.

        Args:
            objects: Objects to order
            options: Organization options

        Returns:
            Ordered list of objects
        """
        if len(objects) <= 1:
            return objects

        try:
            # Use dependency analyzer to order
            ordered = self.dependency_analyzer.get_create_order(objects)

            # Check for circular dependencies
            cycles = self.dependency_analyzer.graph.detect_circular_dependencies()
            if cycles:
                cycle_details = []
                for cycle in cycles[:5]:  # Limit to first 5 cycles to avoid log spam
                    cycle_names = []
                    for obj in cycle:
                        obj_type = get_object_type_name(obj)
                        schema = getattr(obj, "schema", None) or ""
                        name = getattr(obj, "name", "unknown")
                        cycle_names.append(
                            f"{obj_type} {schema}.{name}" if schema else f"{obj_type} {name}"
                        )
                    cycle_details.append(" -> ".join(cycle_names))

                details_str = "; ".join(cycle_details)
                if len(cycles) > 5:
                    details_str += f" ... and {len(cycles) - 5} more cycles"

                logger.debug(f"Detected {len(cycles)} circular dependency cycles: {details_str}")

            return ordered

        except Exception as e:
            logger.warning(f"Dependency analysis failed: {e}, using original order")
            return objects

    def _organize_single_file(self, objects: List[SqlObject]) -> Dict[str, List[SqlObject]]:
        """Organize all objects into a single file."""
        return {"schema.sql": objects}

    def _organize_by_type(self, objects: List[SqlObject]) -> Dict[str, List[SqlObject]]:
        """Organize objects by their type."""
        by_type: Dict[str, List[SqlObject]] = defaultdict(list)

        for obj in objects:
            obj_type = get_object_type_name(obj)
            file_name = f"{obj_type.lower()}.sql"
            by_type[file_name].append(obj)

        return dict(by_type)

    def _organize_by_object(self, objects: List[SqlObject]) -> Dict[str, List[SqlObject]]:
        """Organize one file per object."""
        files = {}

        for obj in objects:
            obj_type = get_object_type_name(obj)
            file_name = f"{obj.name}_{obj_type.lower()}.sql"
            files[file_name] = [obj]

        return files

    def _organize_by_schema(self, objects: List[SqlObject]) -> Dict[str, List[SqlObject]]:
        """Organize objects by schema."""
        by_schema: Dict[str, List[SqlObject]] = defaultdict(list)

        for obj in objects:
            schema = obj.schema or "default"
            file_name = f"{schema}/schema.sql"
            by_schema[file_name].append(obj)

        return dict(by_schema)

    def _organize_by_dependency(self, objects: List[SqlObject]) -> Dict[str, List[SqlObject]]:
        """Organize objects by dependency chains.

        Groups objects that are in the same dependency chain together.
        """
        # Build dependency groups
        groups: List[List[SqlObject]] = []
        # Use object IDs since SqlObject instances may not be hashable
        processed_ids = set()

        for obj in objects:
            obj_id = id(obj)
            if obj_id in processed_ids:
                continue

            # Build a group starting from this object
            group = [obj]
            processed_ids.add(obj_id)

            # Add all dependencies and dependents
            deps = self.dependency_analyzer.graph.get_dependencies(obj)
            dependents = self.dependency_analyzer.graph.get_dependents(obj)

            for dep in deps:
                dep_id = id(dep)
                if dep in objects and dep_id not in processed_ids:
                    group.append(dep)
                    processed_ids.add(dep_id)

            for dependent in dependents:
                dep_id = id(dependent)
                if dependent in objects and dep_id not in processed_ids:
                    group.append(dependent)
                    processed_ids.add(dep_id)

            groups.append(group)

        # Create files for each group
        files = {}
        for i, group in enumerate(groups):
            if len(group) == 1:
                obj = group[0]
                obj_type = get_object_type_name(obj)
                file_name = f"{obj.name}_{obj_type.lower()}.sql"
            else:
                # Group multiple objects
                file_name = f"dependency_group_{i+1}.sql"
            files[file_name] = group

        return files

    def get_drop_order(self, objects: List[SqlObject]) -> List[SqlObject]:
        """Get objects in DROP order (dependents first).

        Args:
            objects: Objects to order for DROP statements

        Returns:
            Objects in reverse dependency order
        """
        if len(objects) <= 1:
            return objects

        try:
            return self.dependency_analyzer.get_drop_order(objects)
        except Exception as e:
            logger.warning(f"Dependency analysis for DROP failed: {e}, using original order")
            return objects

    def generate_file_header(
        self,
        file_name: str,
        object_count: int,
        dialect: str,
        include_timestamp: bool = True,
    ) -> str:
        """Generate a header comment for a SQL file.

        Args:
            file_name: Name of the file
            object_count: Number of objects in the file
            dialect: SQL dialect
            include_timestamp: Whether to include generation timestamp

        Returns:
            Header comment string
        """
        from datetime import datetime

        header_lines = [
            f"-- SQL Script: {file_name}",
            f"-- Generated for dialect: {dialect}",
            f"-- Object count: {object_count}",
        ]

        if include_timestamp:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header_lines.append(f"-- Generated: {timestamp}")

        header_lines.append("--")

        # Dialect-specific session-init lines (SQL Server pins
        # ANSI_NULLS / QUOTED_IDENTIFIER ON).
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks((dialect or "").lower())
        header_lines.extend(quirks.script_header_session_init())

        header_lines.append("")

        return "\n".join(header_lines)

    def generate_file_footer(self, file_name: str, include_summary: bool = True) -> str:
        """Generate a footer comment for a SQL file.

        Args:
            file_name: Name of the file
            include_summary: Whether to include summary

        Returns:
            Footer comment string
        """
        footer_lines = []

        if include_summary:
            footer_lines.append("")
            footer_lines.append("-- End of script")

        return "\n".join(footer_lines)
