"""
Dependency resolution for SQL objects.

Builds and manages dependency graphs for SQL objects to enable
proper ordering and dependency-aware operations.
"""

import logging
import re
from typing import Dict, List, Optional, Set

from core.sql_model.base import SqlObject
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.view import View

logger = logging.getLogger(__name__)


class DependencyResolver:
    """
    Resolves dependencies between SQL objects.

    Tracks:
    - Table dependencies (foreign keys, inheritance)
    - View dependencies (tables, other views)
    - Index dependencies (tables)
    - Procedure/Function dependencies (tables, views, other procedures)
    - Trigger dependencies (tables, procedures)
    """

    def __init__(self):
        """Initialize the dependency resolver."""
        self.dependency_graph: Dict[str, Set[str]] = {}
        self.reverse_dependency_graph: Dict[str, Set[str]] = {}

    def build_dependency_graph(
        self,
        tables: List[Table],
        views: Optional[List[View]] = None,
        indexes: Optional[List[Index]] = None,
        procedures: Optional[List[Procedure]] = None,
        triggers: Optional[List[Trigger]] = None,
        schema: str = "public",
    ) -> Dict[str, Set[str]]:
        """Build dependency graph for all objects.

        Args:
            tables: List of tables
            views: Optional list of views
            indexes: Optional list of indexes
            schema: Schema name

        Returns:
            Dictionary mapping object key -> set of dependency keys
        """
        self.dependency_graph = {}
        self.reverse_dependency_graph = {}

        # Process tables
        for table in tables:
            table_key = self._get_object_key("table", table.name, schema)
            deps = set()

            # Foreign key dependencies
            for constraint in table.constraints:
                if constraint.constraint_type.value == "FOREIGN KEY":
                    ref_table = constraint.reference_table
                    ref_schema = getattr(constraint, "reference_schema", None) or schema
                    if ref_table:
                        dep_key = self._get_object_key("table", ref_table, ref_schema)
                        deps.add(dep_key)

            # Inheritance dependencies (PostgreSQL ``INHERITS``). Read from
            # ``dialect_options`` under the canonical namespace resolved from
            # the registry, so this module names no dialect (ADR-26 E 26-5).
            inherits: List[str] = []
            if hasattr(table, "get_dialect_option"):
                from core.sql_model.table_options import builtin_namespace_for

                ns = builtin_namespace_for("table_supports_inherits")
                if ns:
                    inherits = table.get_dialect_option(ns, "inherits", default=[]) or []
            if inherits:
                for parent in inherits:
                    # Parent can be "table" or "schema.table"
                    if "." in parent:
                        parent_schema, parent_table = parent.split(".", 1)
                    else:
                        parent_schema = schema
                        parent_table = parent
                    dep_key = self._get_object_key("table", parent_table, parent_schema)
                    deps.add(dep_key)

            if deps:
                self.dependency_graph[table_key] = deps

        # Process views
        if views:
            for view in views:
                view_key = self._get_object_key("view", view.name, schema)
                deps = set()

                # View dependencies are in the query, which we'd need to parse
                # For now, we track explicit dependencies if available
                if hasattr(view, "dependencies") and view.dependencies:
                    for dep in view.dependencies:
                        # Handle both dict and string formats
                        if isinstance(dep, dict):
                            dep_type = dep.get("type", "table")
                            dep_name = dep.get("name", "")
                            dep_schema = dep.get("schema", schema)
                        elif isinstance(dep, str):
                            # Simple string format - assume it's a table name
                            dep_type = "table"
                            dep_name = dep
                            dep_schema = schema
                        else:
                            continue
                        dep_key = self._get_object_key(dep_type, dep_name, dep_schema)
                        deps.add(dep_key)

                # Try to extract table dependencies from view query
                if hasattr(view, "query") and view.query:
                    table_deps = self._extract_table_dependencies_from_query(view.query, schema)
                    deps.update(table_deps)

                # View dependencies on other views (if view.query references other views)
                if hasattr(view, "query") and view.query:
                    view_deps = self._extract_view_dependencies_from_query(
                        view.query, schema, views
                    )
                    deps.update(view_deps)

                if deps:
                    self.dependency_graph[view_key] = deps

        # Process indexes
        if indexes:
            for index in indexes:
                index_key = self._get_object_key("index", index.name, schema)
                table_key = self._get_object_key("table", index.table_name, schema)
                self.dependency_graph[index_key] = {table_key}

        # Process procedures/functions
        if procedures:
            for procedure in procedures:
                proc_key = self._get_object_key("procedure", procedure.name, schema)
                deps = set()

                # Extract dependencies from procedure body/definition
                if hasattr(procedure, "body") and procedure.body:
                    table_deps = self._extract_table_dependencies_from_query(procedure.body, schema)
                    deps.update(table_deps)

                if hasattr(procedure, "definition") and procedure.definition:
                    table_deps = self._extract_table_dependencies_from_query(
                        procedure.definition, schema
                    )
                    deps.update(table_deps)

                if deps:
                    self.dependency_graph[proc_key] = deps

        # Process triggers
        if triggers:
            for trigger in triggers:
                trigger_key = self._get_object_key("trigger", trigger.name, schema)
                deps = set()

                # Trigger depends on its table
                if hasattr(trigger, "table_name") and trigger.table_name:
                    table_key = self._get_object_key("table", trigger.table_name, schema)
                    deps.add(table_key)

                # Trigger may depend on procedures/functions
                if hasattr(trigger, "function_name") and trigger.function_name:
                    func_schema = getattr(trigger, "function_schema", None) or schema
                    func_key = self._get_object_key("procedure", trigger.function_name, func_schema)
                    deps.add(func_key)

                # Trigger execution order dependencies
                if hasattr(trigger, "follows_trigger") and trigger.follows_trigger:
                    follows_key = self._get_object_key("trigger", trigger.follows_trigger, schema)
                    deps.add(follows_key)

                if deps:
                    self.dependency_graph[trigger_key] = deps

        # Build reverse dependency graph
        self._build_reverse_graph()

        return self.dependency_graph

    def _build_reverse_graph(self):
        """Build reverse dependency graph (what depends on each object)."""
        self.reverse_dependency_graph = {}
        for obj_key, deps in self.dependency_graph.items():
            for dep_key in deps:
                if dep_key not in self.reverse_dependency_graph:
                    self.reverse_dependency_graph[dep_key] = set()
                self.reverse_dependency_graph[dep_key].add(obj_key)

    def get_dependencies(
        self, object_type: str, object_name: str, schema: str = "public"
    ) -> Set[str]:
        """Get direct dependencies for an object.

        Args:
            object_type: Object type (table, view, index, etc.)
            object_name: Object name
            schema: Schema name

        Returns:
            Set of dependency keys
        """
        obj_key = self._get_object_key(object_type, object_name, schema)
        return self.dependency_graph.get(obj_key, set())

    def get_dependents(
        self, object_type: str, object_name: str, schema: str = "public"
    ) -> Set[str]:
        """Get objects that depend on this object.

        Args:
            object_type: Object type
            object_name: Object name
            schema: Schema name

        Returns:
            Set of dependent object keys
        """
        obj_key = self._get_object_key(object_type, object_name, schema)
        return self.reverse_dependency_graph.get(obj_key, set())

    def get_all_dependencies(
        self,
        object_type: str,
        object_name: str,
        schema: str = "public",
    ) -> Set[str]:
        """Get all transitive dependencies for an object.

        Args:
            object_type: Object type
            object_name: Object name
            schema: Schema name

        Returns:
            Set of all dependency keys (transitive)
        """
        obj_key = self._get_object_key(object_type, object_name, schema)
        all_deps = set()
        visited = set()

        def _collect_deps(key: str):
            if key in visited:
                return
            visited.add(key)
            deps = self.dependency_graph.get(key, set())
            for dep in deps:
                all_deps.add(dep)
                _collect_deps(dep)

        _collect_deps(obj_key)
        return all_deps

    def get_dependency_order(
        self,
        objects: List[SqlObject],
        schema: str = "public",
    ) -> List[SqlObject]:
        """Get objects in dependency order (dependencies first).

        Args:
            objects: List of objects to order
            schema: Schema name

        Returns:
            List of objects in dependency order
        """
        # Build object key -> object mapping
        obj_map = {}
        for obj in objects:
            obj_key = self._get_object_key(obj.object_type.value.lower(), obj.name, schema)
            obj_map[obj_key] = obj

        # Topological sort
        ordered = []
        visited = set()
        visiting = set()

        def _visit(obj_key: str):
            if obj_key in visited:
                return
            if obj_key in visiting:
                # Circular dependency detected
                logger.warning(f"Circular dependency detected involving {obj_key}")
                return

            visiting.add(obj_key)

            # Visit dependencies first
            deps = self.dependency_graph.get(obj_key, set())
            for dep_key in deps:
                if dep_key in obj_map:
                    _visit(dep_key)

            visiting.remove(obj_key)
            visited.add(obj_key)

            # Add object to ordered list
            if obj_key in obj_map:
                ordered.append(obj_map[obj_key])

        # Visit all objects
        for obj in objects:
            obj_key = self._get_object_key(obj.object_type.value.lower(), obj.name, schema)
            if obj_key not in visited:
                _visit(obj_key)

        return ordered

    def detect_circular_dependencies(
        self,
        schema: str = "public",
    ) -> List[List[str]]:
        """Detect circular dependencies in the graph.

        Args:
            schema: Schema name

        Returns:
            List of circular dependency chains
        """
        cycles = []
        visited = set()
        rec_stack = set()

        def _dfs(obj_key: str, path: List[str]):
            visited.add(obj_key)
            rec_stack.add(obj_key)
            path.append(obj_key)

            deps = self.dependency_graph.get(obj_key, set())
            for dep_key in deps:
                if dep_key not in visited:
                    _dfs(dep_key, path.copy())
                elif dep_key in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(dep_key)
                    cycle = path[cycle_start:] + [dep_key]
                    cycles.append(cycle)

            rec_stack.remove(obj_key)
            path.pop()

        for obj_key in self.dependency_graph:
            if obj_key not in visited:
                _dfs(obj_key, [])

        return cycles

    def _extract_table_dependencies_from_query(self, query: str, schema: str) -> Set[str]:
        """Extract table dependencies from a SQL query.

        Args:
            query: SQL query string
            schema: Default schema name

        Returns:
            Set of table dependency keys
        """
        deps = set()

        # Simple pattern matching for FROM and JOIN clauses
        # This is a basic implementation - a full SQL parser would be more accurate
        patterns = [
            r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
            r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, query, re.IGNORECASE)
            for match in matches:
                table_ref = match.group(1)
                # Handle schema.table format
                if "." in table_ref:
                    parts = table_ref.split(".", 1)
                    table_schema = parts[0]
                    table_name = parts[1]
                else:
                    table_schema = schema
                    table_name = table_ref

                dep_key = self._get_object_key("table", table_name, table_schema)
                deps.add(dep_key)

        return deps

    def _extract_view_dependencies_from_query(
        self,
        query: str,
        schema: str,
        all_views: List[View],
    ) -> Set[str]:
        """Extract view dependencies from a SQL query.

        Args:
            query: SQL query string
            schema: Default schema name
            all_views: List of all views to check against

        Returns:
            Set of view dependency keys
        """
        deps = set()

        # Look for view names in FROM/JOIN clauses
        for view in all_views:
            view_name_lower = view.name.lower()
            # Simple check if view name appears in query (basic implementation)
            pattern = rf"\b{re.escape(view_name_lower)}\b"
            if re.search(pattern, query, re.IGNORECASE):
                view_key = self._get_object_key("view", view.name, schema)
                deps.add(view_key)

        return deps

    @staticmethod
    def _get_object_key(object_type: str, object_name: str, schema: str) -> str:
        """Get normalized object key for dependency tracking.

        Args:
            object_type: Object type
            object_name: Object name
            schema: Schema name

        Returns:
            Normalized object key
        """
        return f"{schema.lower()}.{object_type.lower()}.{object_name.lower()}"
