"""Dependency Analyzer for SQL Objects.

This module analyzes dependencies between SQL objects to enable proper
ordering of CREATE and DROP statements.
"""

import logging
import re
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set, Tuple

from core.sql_model.base import (
    SqlObject,
    get_constraint_type_name,
    get_object_type_name,
)

logger = logging.getLogger(__name__)


class DependencyGraph:
    """Represents a dependency graph for SQL objects."""

    def __init__(self):
        """Initialize an empty dependency graph."""
        # Use object identity (id()) as keys since SqlObject subclasses may not be hashable
        # Map: object id -> object
        self._objects_by_id: Dict[int, SqlObject] = {}

        # Map: object id -> set of object ids it depends on
        self.dependencies: Dict[int, Set[int]] = defaultdict(set)

        # Map: object id -> set of object ids that depend on it
        self.dependents: Dict[int, Set[int]] = defaultdict(set)

    def add_object(self, obj: SqlObject) -> None:
        """Add an object to the graph.

        Args:
            obj: SQL object to add
        """
        obj_id = id(obj)
        self._objects_by_id[obj_id] = obj
        if obj_id not in self.dependencies:
            self.dependencies[obj_id] = set()
        if obj_id not in self.dependents:
            self.dependents[obj_id] = set()

    @property
    def objects(self) -> List[SqlObject]:
        """Get all objects in the graph."""
        return list(self._objects_by_id.values())

    def add_dependency(self, obj: SqlObject, depends_on: SqlObject) -> None:
        """Add a dependency relationship.

        Args:
            obj: Object that depends on depends_on
            depends_on: Object that obj depends on
        """
        self.add_object(obj)
        self.add_object(depends_on)

        obj_id = id(obj)
        depends_on_id = id(depends_on)

        self.dependencies[obj_id].add(depends_on_id)
        self.dependents[depends_on_id].add(obj_id)

    def get_dependencies(self, obj: SqlObject) -> List[SqlObject]:
        """Get all objects that the given object depends on.

        Args:
            obj: SQL object

        Returns:
            List of objects that obj depends on
        """
        obj_id = id(obj)
        dep_ids = self.dependencies.get(obj_id, set())
        return [self._objects_by_id[dep_id] for dep_id in dep_ids if dep_id in self._objects_by_id]

    def get_dependents(self, obj: SqlObject) -> List[SqlObject]:
        """Get all objects that depend on the given object.

        Args:
            obj: SQL object

        Returns:
            List of objects that depend on obj
        """
        obj_id = id(obj)
        dependent_ids = self.dependents.get(obj_id, set())
        return [
            self._objects_by_id[dep_id] for dep_id in dependent_ids if dep_id in self._objects_by_id
        ]

    def detect_circular_dependencies(self) -> List[List[SqlObject]]:
        """Detect circular dependencies in the graph.

        Returns:
            List of cycles (each cycle is a list of objects)
        """
        cycles = []
        visited_ids = set()
        rec_stack_ids = set()

        def dfs(node_id: int, path_ids: List[int]) -> None:
            """DFS to detect cycles."""
            if node_id in rec_stack_ids:
                # Found a cycle
                cycle_start = path_ids.index(node_id)
                cycle_ids = path_ids[cycle_start:] + [node_id]
                cycle = [
                    self._objects_by_id[cid] for cid in cycle_ids if cid in self._objects_by_id
                ]
                # Only add cycle if it has at least 2 nodes (avoid self-loops)
                if len(cycle) >= 2:
                    cycles.append(cycle)
                return

            if node_id in visited_ids:
                return

            visited_ids.add(node_id)
            rec_stack_ids.add(node_id)
            path_ids.append(node_id)

            for dep_id in self.dependencies.get(node_id, set()):
                dfs(dep_id, path_ids[:])

            # Backtrack: remove from recursion stack and path
            rec_stack_ids.remove(node_id)
            # Note: path_ids.pop() is not needed here because we pass copies (path_ids[:])
            # to recursive calls, so the original path_ids is only modified by this call

        for obj_id in self._objects_by_id.keys():
            if obj_id not in visited_ids:
                dfs(obj_id, [])

        return cycles


class DependencyAnalyzer:
    """Analyzes dependencies between SQL objects."""

    def __init__(self):
        """Initialize the dependency analyzer."""
        self.graph = DependencyGraph()

    def build_graph(self, objects: List[SqlObject]) -> DependencyGraph:
        """Build a dependency graph from a list of objects.

        Analyzes relationships such as:
        - Views depend on tables
        - Indexes depend on tables
        - Procedures/Functions depend on tables/views
        - Triggers depend on tables
        - Foreign keys create table dependencies

        Args:
            objects: List of SQL objects to analyze

        Returns:
            DependencyGraph with all dependencies
        """
        self.graph = DependencyGraph()

        # Add all objects to graph
        for obj in objects:
            self.graph.add_object(obj)

        # Build dependency map for quick lookup
        object_map: Dict[Tuple[Optional[str], str], SqlObject] = {}
        for obj in objects:
            schema_key = self._normalize_schema(obj.schema)
            name = obj.name.lower()
            object_map[(schema_key, name)] = obj
            # Register default schema aliases so references without schema still resolve
            if schema_key:
                object_map.setdefault(("", name), obj)
                object_map.setdefault((None, name), obj)
            else:
                object_map.setdefault((None, name), obj)

        # Analyze dependencies for each object
        for obj in objects:
            deps = self._analyze_object_dependencies(obj, object_map, objects)
            for dep in deps:
                self.graph.add_dependency(obj, dep)

        return self.graph

    def _analyze_object_dependencies(
        self,
        obj: SqlObject,
        object_map: Dict[Tuple[Optional[str], str], SqlObject],
        all_objects: List[SqlObject],
    ) -> List[SqlObject]:
        """Analyze dependencies for a single object.

        Args:
            obj: Object to analyze
            object_map: Map of (schema, name) -> object for quick lookup
            all_objects: All objects in the schema

        Returns:
            List of objects that obj depends on
        """
        dependencies = []

        obj_type = get_object_type_name(obj)

        # Views depend on tables they reference
        if obj_type in ("VIEW", "MATERIALIZED_VIEW"):
            if hasattr(obj, "query") and obj.query:
                # Extract table references from query
                # This is a simplified version - could be enhanced with SQL parsing
                table_refs = self._extract_table_references_from_query(obj.query)
                for schema, table_name in table_refs:
                    # Normalize schema: use empty string if None (matches object_map key format)
                    dep_obj = self._lookup_object(object_map, schema, table_name)
                    if dep_obj:
                        dependencies.append(dep_obj)

        # Indexes depend on tables
        elif obj_type == "INDEX":
            if hasattr(obj, "table_name") and obj.table_name:
                schema = getattr(obj, "table_schema", None) or getattr(obj, "schema", None)
                dep_obj = self._lookup_object(object_map, schema, obj.table_name)
                if dep_obj:
                    dependencies.append(dep_obj)

        # Triggers depend on tables
        elif obj_type == "TRIGGER":
            if hasattr(obj, "table_name") and obj.table_name:
                schema = getattr(obj, "table_schema", None) or getattr(obj, "schema", None)
                dep_obj = self._lookup_object(object_map, schema, obj.table_name)
                if dep_obj:
                    dependencies.append(dep_obj)

        # Procedures/Functions depend on tables/views they reference
        elif obj_type in ("PROCEDURE", "FUNCTION"):
            if hasattr(obj, "body") and obj.body:
                table_refs = self._extract_table_references_from_query(obj.body)
                for schema, table_name in table_refs:
                    dep_obj = self._lookup_object(object_map, schema, table_name)
                    if dep_obj:
                        dependencies.append(dep_obj)

        # Tables depend on tables referenced by foreign keys
        elif obj_type == "TABLE":
            if hasattr(obj, "constraints"):
                for constraint in obj.constraints:
                    if (
                        hasattr(constraint, "constraint_type")
                        and get_constraint_type_name(constraint) == "FOREIGN KEY"
                    ):
                        if hasattr(constraint, "reference_table") and constraint.reference_table:
                            # Handle schema-qualified table names (e.g., "schema.table")
                            ref_table = constraint.reference_table
                            ref_schema = getattr(constraint, "reference_schema", None)

                            # If reference_table contains a schema prefix, parse it
                            if "." in ref_table and not ref_schema:
                                parts = ref_table.rsplit(".", 1)
                                if len(parts) == 2:
                                    ref_schema = parts[0]
                                    ref_table = parts[1]

                            dep_obj = self._lookup_object(
                                object_map,
                                ref_schema,
                                ref_table,
                            )
                            if dep_obj:
                                dependencies.append(dep_obj)
            if hasattr(obj, "columns"):
                for column in obj.columns or []:
                    type_dep = self._lookup_column_type_dependency(
                        all_objects, getattr(obj, "schema", None), getattr(column, "data_type", "")
                    )
                    if type_dep:
                        dependencies.append(type_dep)

                    default_dep = self._lookup_nextval_sequence_dependency(
                        all_objects,
                        getattr(obj, "schema", None),
                        getattr(column, "default_value", None),
                    )
                    if default_dep:
                        dependencies.append(default_dep)
            if getattr(obj, "system_versioned", False) and getattr(obj, "history_table", None):
                history_schema = getattr(obj, "history_schema", None) or getattr(
                    obj, "schema", None
                )
                history_table = getattr(obj, "history_table", None)
                if history_table:
                    dep_obj = self._lookup_object(object_map, history_schema, history_table)
                    if dep_obj:
                        dependencies.append(dep_obj)

        return dependencies

    def _normalize_schema(self, schema: Optional[str]) -> str:
        """Normalize schema names for consistent lookup."""
        if not schema:
            return ""
        return schema.lower()

    def _lookup_object(
        self,
        object_map: Dict[Tuple[Optional[str], str], SqlObject],
        schema: Optional[str],
        name: str,
    ) -> Optional[SqlObject]:
        """Lookup an object by schema/name with fallback to default schema."""
        normalized_schema = self._normalize_schema(schema)
        name_key = name.lower()

        key = (normalized_schema, name_key)
        if key in object_map:
            return object_map[key]

        fallback_keys: List[Tuple[Optional[str], str]] = []
        if normalized_schema:
            fallback_keys.append(("", name_key))
        fallback_keys.append((None, name_key))

        for fallback in fallback_keys:
            if fallback in object_map:
                return object_map[fallback]
        return None

    def _lookup_column_type_dependency(
        self, objects: List[SqlObject], table_schema: Optional[str], data_type: str
    ) -> Optional[SqlObject]:
        type_name = self._normalize_type_reference(data_type)
        if not type_name:
            return None
        return self._lookup_named_object_by_type(
            objects, table_schema, type_name, {"TYPE", "USER_DEFINED_TYPE"}
        )

    def _lookup_nextval_sequence_dependency(
        self, objects: List[SqlObject], table_schema: Optional[str], default_value: object
    ) -> Optional[SqlObject]:
        if not default_value:
            return None
        match = re.search(r"nextval\('([^']+)'(?:::regclass)?\)", str(default_value), re.I)
        if not match:
            return None
        sequence_ref = match.group(1).strip('"')
        if "." in sequence_ref:
            schema, name = sequence_ref.rsplit(".", 1)
        else:
            schema, name = table_schema, sequence_ref
        return self._lookup_named_object_by_type(objects, schema, name, {"SEQUENCE"})

    def _lookup_named_object_by_type(
        self,
        objects: List[SqlObject],
        schema: Optional[str],
        name: str,
        object_types: Set[str],
    ) -> Optional[SqlObject]:
        normalized_schema = self._normalize_schema(schema)
        normalized_name = name.strip('"').lower()
        fallback = None
        for obj in objects:
            obj_type = get_object_type_name(obj)
            if obj_type not in object_types:
                continue
            obj_name = getattr(obj, "name", "")
            if not obj_name or str(obj_name).strip('"').lower() != normalized_name:
                continue
            obj_schema = self._normalize_schema(getattr(obj, "schema", None))
            if obj_schema == normalized_schema:
                return obj
            if not obj_schema or not normalized_schema:
                fallback = obj
        return fallback

    def _normalize_type_reference(self, data_type: str) -> str:
        if not data_type:
            return ""
        type_name = str(data_type).strip().split()[0]  # lint: allow-enum-str
        type_name = re.sub(r"\(.*$", "", type_name)
        type_name = type_name.rstrip("[]")
        if "." in type_name:
            type_name = type_name.rsplit(".", 1)[1]
        return type_name.strip('"').lower()

    def _extract_table_references_from_query(self, query: str) -> List[Tuple[Optional[str], str]]:
        """Extract table references from a SQL query.

        This is a simplified implementation that extracts basic table names
        from queries. A more sophisticated version could use SQL parsing.

        Args:
            query: SQL query string

        Returns:
            List of (schema, table_name) tuples
        """
        references = []
        # Pattern: FROM schema.table or FROM table or JOIN schema.table
        # Match FROM/JOIN followed by identifier(s)
        normalized_query = re.sub(r"[`\"\[\]]", "", query)
        patterns = [
            r"(?:FROM|JOIN)\s+(?:\w+\.)?(\w+)",  # FROM table or FROM schema.table (capture table)
            r"(?:FROM|JOIN)\s+(\w+)\.(\w+)",  # FROM schema.table (both)
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, normalized_query, re.IGNORECASE)
            for match in matches:
                groups = match.groups()
                if len(groups) == 2:
                    # schema.table pattern
                    schema, table = groups
                    references.append((schema.lower() if schema else None, table.lower()))
                elif len(groups) == 1:
                    table = groups[0]
                    # Skip common SQL keywords
                    table_upper = table.upper()
                    if table_upper not in (
                        "SELECT",
                        "WHERE",
                        "GROUP",
                        "ORDER",
                        "HAVING",
                        "FROM",
                        "JOIN",
                        "AS",
                    ):
                        references.append((None, table.lower()))

        # Remove duplicates
        return list(set(references))

    def topological_sort(
        self, objects: Optional[List[SqlObject]] = None, reverse: bool = False
    ) -> List[SqlObject]:
        """Perform topological sort on objects based on dependencies.

        Args:
            objects: Optional list of objects to sort. If None, uses all objects in graph.
            reverse: If True, sort in reverse order (for DROP statements)

        Returns:
            List of objects in dependency order
        """
        if objects is None:
            objects = list(self.graph._objects_by_id.values())

        # Map objects to their IDs for efficient lookup
        # Use list indexing since objects may not be hashable
        obj_to_id = {}
        id_to_obj = {}
        for obj in objects:
            obj_id = id(obj)
            obj_to_id[obj_id] = obj_id  # Store ID as both key and value for lookup
            id_to_obj[obj_id] = obj

        # Build in-degree map using IDs
        # Only count dependencies that are in the objects list being sorted
        objects_set = {id(obj) for obj in objects}
        in_degree: Dict[int, int] = {}
        for obj in objects:
            obj_id = id(obj)
            # Only count dependencies that are in the objects list
            dependencies = self.graph.get_dependencies(obj)
            in_degree[obj_id] = sum(1 for dep in dependencies if id(dep) in objects_set)

        # Find objects with no dependencies
        queue = deque([obj_id for obj_id in in_degree.keys() if in_degree[obj_id] == 0])
        result_ids = []

        if reverse:
            # For DROP, we want reverse order (dependents first)
            # Build reverse graph - only include dependents that are in objects list
            # reverse_deps[dep_id] = set of obj_ids that depend on dep_id in original graph
            reverse_deps: Dict[int, Set[int]] = defaultdict(set)
            for obj in objects:
                obj_id = id(obj)
                for dep in self.graph.get_dependencies(obj):
                    dep_id = id(dep)
                    if dep_id in objects_set:
                        reverse_deps[dep_id].add(obj_id)

            in_degree = {}
            for obj in objects:
                obj_id = id(obj)
                # Only count dependents that are in the objects list
                in_degree[obj_id] = len(reverse_deps.get(obj_id, set()))

            queue = deque([obj_id for obj_id in in_degree.keys() if in_degree[obj_id] == 0])
        while queue:
            obj_id = queue.popleft()
            result_ids.append(obj_id)

            if reverse:
                # For DROP, when we process an object, we need to decrease in_degree of objects
                # that it depends on in the original graph (because we want to drop dependents before dependencies)
                # So we look at what the current object depends on, not what depends on it
                obj = id_to_obj[obj_id]
                dependencies = self.graph.get_dependencies(obj)
                for dep in dependencies:
                    dep_id = id(dep)
                    # Only process dependencies that are in the objects list
                    if dep_id in objects_set and dep_id in in_degree:
                        in_degree[dep_id] -= 1
                        if in_degree[dep_id] == 0:
                            queue.append(dep_id)
            else:
                # For CREATE, add objects that depend on current object
                obj = id_to_obj[obj_id]
                for dependent in self.graph.get_dependents(obj):
                    dep_id = id(dependent)
                    # Only process dependents that are in the objects list
                    if dep_id in objects_set and dep_id in in_degree:
                        in_degree[dep_id] -= 1
                        if in_degree[dep_id] == 0:
                            queue.append(dep_id)

        # Check for circular dependencies
        result_ids_set = set(result_ids)
        all_obj_ids = {id(obj) for obj in objects}

        # Only log if there's actually a mismatch
        if len(result_ids) != len(objects) or result_ids_set != all_obj_ids:
            remaining_ids = all_obj_ids - result_ids_set
            remaining_objects = [
                id_to_obj[obj_id] for obj_id in remaining_ids if obj_id in id_to_obj
            ]

            # Log details about objects with circular dependencies
            if remaining_objects:
                obj_details = []
                for obj in remaining_objects[:10]:  # Limit to first 10 to avoid log spam
                    obj_type = get_object_type_name(obj)
                    schema = getattr(obj, "schema", None) or ""
                    name = getattr(obj, "name", "unknown")
                    obj_details.append(
                        f"{obj_type} {schema}.{name}" if schema else f"{obj_type} {name}"
                    )

                details_str = ", ".join(obj_details)
                if len(remaining_objects) > 10:
                    details_str += f", ... and {len(remaining_objects) - 10} more"

                logger.debug(
                    f"Circular dependencies detected. {len(remaining_ids)} objects not in sorted order: {details_str}"
                )
            else:
                logger.debug(
                    f"Circular dependencies detected. {len(remaining_ids)} objects not in sorted order."
                )
            # Add remaining objects at the end
            result_ids.extend(remaining_ids)

        # Convert IDs back to objects
        result = [id_to_obj[obj_id] for obj_id in result_ids if obj_id in id_to_obj]
        return result

    def get_create_order(self, objects: List[SqlObject]) -> List[SqlObject]:
        """Get objects in order for CREATE statements (dependencies first).

        Args:
            objects: List of objects to order

        Returns:
            Objects in CREATE order (dependencies come before dependents)
        """
        self.build_graph(objects)
        return self.topological_sort(objects, reverse=False)

    def get_drop_order(self, objects: List[SqlObject]) -> List[SqlObject]:
        """Get objects in order for DROP statements (dependents first).

        Args:
            objects: List of objects to order

        Returns:
            Objects in DROP order (dependents come before dependencies)
        """
        self.build_graph(objects)
        return self.topological_sort(objects, reverse=True)
