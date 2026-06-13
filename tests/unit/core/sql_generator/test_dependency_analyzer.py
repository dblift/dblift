"""Tests for DependencyAnalyzer and DependencyGraph classes."""

import logging

import pytest

from core.sql_generator.dependency_analyzer import DependencyAnalyzer, DependencyGraph
from core.sql_model import Index, Procedure, Sequence, Table, Trigger, View
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint, SqlObjectType


@pytest.mark.unit
class TestDependencyGraph:
    """Test DependencyGraph class."""

    def test_init(self):
        """Test DependencyGraph initialization."""
        graph = DependencyGraph()
        assert len(graph.objects) == 0
        assert len(graph.dependencies) == 0
        assert len(graph.dependents) == 0

    def test_add_object(self):
        """Test adding an object to the graph."""
        graph = DependencyGraph()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        graph.add_object(table)
        assert table in graph.objects
        assert id(table) in graph.dependencies
        assert id(table) in graph.dependents

    def test_add_dependency(self):
        """Test adding a dependency relationship."""
        graph = DependencyGraph()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        graph.add_dependency(view, table)
        assert table in graph.objects
        assert view in graph.objects
        # view depends on table, so table's dependents should include view
        assert id(view) in graph.dependents[id(table)]
        # view's dependencies should include table
        assert id(table) in graph.dependencies[id(view)]

    def test_get_dependencies(self):
        """Test getting dependencies of an object."""
        graph = DependencyGraph()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        graph.add_dependency(view, table)
        deps = graph.get_dependencies(view)
        assert table in deps

    def test_get_dependents(self):
        """Test getting dependents of an object."""
        graph = DependencyGraph()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        graph.add_dependency(view, table)
        dependents = graph.get_dependents(table)
        assert view in dependents

    def test_detect_circular_dependencies_no_cycles(self):
        """Test detecting circular dependencies when none exist."""
        graph = DependencyGraph()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT 1", dialect="postgresql")
        graph.add_dependency(view, table)
        cycles = graph.detect_circular_dependencies()
        assert cycles == []

    def test_detect_circular_dependencies_with_cycle(self):
        """Test detecting circular dependencies."""
        graph = DependencyGraph()
        table1 = Table(name="table1", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table2 = Table(name="table2", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        # Create circular dependency manually
        graph.add_object(table1)
        graph.add_object(table2)
        graph.dependencies[id(table1)].add(id(table2))
        graph.dependents[id(table2)].add(id(table1))
        graph.dependencies[id(table2)].add(id(table1))
        graph.dependents[id(table1)].add(id(table2))
        cycles = graph.detect_circular_dependencies()
        assert len(cycles) > 0


@pytest.mark.unit
class TestDependencyAnalyzer:
    """Test DependencyAnalyzer class."""

    def test_init(self):
        """Test DependencyAnalyzer initialization."""
        analyzer = DependencyAnalyzer()
        assert analyzer.graph is not None

    def test_build_graph_empty(self):
        """Test building graph with empty list."""
        analyzer = DependencyAnalyzer()
        graph = analyzer.build_graph([])
        assert len(graph.objects) == 0

    def test_build_graph_table_view_dependency(self):
        """Test building graph with table-view dependency."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        graph = analyzer.build_graph([table, view])
        deps = graph.get_dependencies(view)
        assert table in deps

    def test_build_graph_index_table_dependency(self):
        """Test building graph with index-table dependency."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        index = Index(name="idx_id", table_name="users", columns=["id"], dialect="postgresql")
        graph = analyzer.build_graph([table, index])
        deps = graph.get_dependencies(index)
        assert table in deps

    def test_build_graph_trigger_table_dependency(self):
        """Test building graph with trigger-table dependency."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        trigger = Trigger(
            name="trg_users",
            table_name="users",
            timing="BEFORE",
            events=["INSERT"],
            dialect="postgresql",
        )
        graph = analyzer.build_graph([table, trigger])
        deps = graph.get_dependencies(trigger)
        assert table in deps

    def test_build_graph_procedure_table_dependency(self):
        """Test building graph with procedure-table dependency."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        procedure = Procedure(name="sp_test", body="SELECT * FROM users", dialect="postgresql")
        graph = analyzer.build_graph([table, procedure])
        deps = graph.get_dependencies(procedure)
        assert table in deps

    def test_build_graph_foreign_key_dependency(self):
        """Test building graph with foreign key dependency."""
        analyzer = DependencyAnalyzer()
        table1 = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table2 = Table(
            name="orders",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("user_id", "INTEGER")],
            dialect="postgresql",
        )
        constraint = SqlConstraint(
            name="fk_orders_user",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="users",
        )
        table2.constraints = [constraint]
        graph = analyzer.build_graph([table1, table2])
        deps = graph.get_dependencies(table2)
        assert table1 in deps

    def test_build_graph_foreign_key_with_schema(self):
        """Test building graph with foreign key referencing schema.table."""
        analyzer = DependencyAnalyzer()
        table1 = Table(
            name="users",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        table2 = Table(
            name="orders",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("user_id", "INTEGER")],
            dialect="postgresql",
        )
        constraint = SqlConstraint(
            name="fk_orders_user",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="public.users",
        )
        table2.constraints = [constraint]
        graph = analyzer.build_graph([table1, table2])
        deps = graph.get_dependencies(table2)
        assert table1 in deps

    def test_build_graph_system_versioned_table(self):
        """Test building graph with system-versioned table dependency."""
        analyzer = DependencyAnalyzer()
        history_table = Table(
            name="users_history", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table.system_versioned = True
        table.history_table = "users_history"
        graph = analyzer.build_graph([table, history_table])
        deps = graph.get_dependencies(table)
        assert history_table in deps

    def test_normalize_schema_none(self):
        """Test _normalize_schema with None."""
        analyzer = DependencyAnalyzer()
        result = analyzer._normalize_schema(None)
        assert result == ""

    def test_normalize_schema_empty(self):
        """Test _normalize_schema with empty string."""
        analyzer = DependencyAnalyzer()
        result = analyzer._normalize_schema("")
        assert result == ""

    def test_normalize_schema_lowercase(self):
        """Test _normalize_schema converts to lowercase."""
        analyzer = DependencyAnalyzer()
        result = analyzer._normalize_schema("PUBLIC")
        assert result == "public"

    def test_lookup_object_exact_match(self):
        """Test _lookup_object with exact match."""
        analyzer = DependencyAnalyzer()
        table = Table(
            name="users",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        object_map = {("public", "users"): table}
        result = analyzer._lookup_object(object_map, "public", "users")
        assert result == table

    def test_lookup_object_fallback_to_default_schema(self):
        """Test _lookup_object falls back to default schema."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        object_map = {("", "users"): table}
        result = analyzer._lookup_object(object_map, "public", "users")
        assert result == table

    def test_lookup_object_not_found(self):
        """Test _lookup_object when object not found."""
        analyzer = DependencyAnalyzer()
        object_map = {}
        result = analyzer._lookup_object(object_map, "public", "users")
        assert result is None

    def test_extract_table_references_from_query_simple(self):
        """Test _extract_table_references_from_query with simple query."""
        analyzer = DependencyAnalyzer()
        query = "SELECT * FROM users"
        refs = analyzer._extract_table_references_from_query(query)
        assert ("", "users") in refs or (None, "users") in refs

    def test_extract_table_references_from_query_with_schema(self):
        """Test _extract_table_references_from_query with schema."""
        analyzer = DependencyAnalyzer()
        query = "SELECT * FROM public.users"
        refs = analyzer._extract_table_references_from_query(query)
        assert ("public", "users") in refs

    def test_extract_table_references_from_query_join(self):
        """Test _extract_table_references_from_query with JOIN."""
        analyzer = DependencyAnalyzer()
        query = "SELECT * FROM users JOIN orders ON users.id = orders.user_id"
        refs = analyzer._extract_table_references_from_query(query)
        assert ("", "users") in refs or (None, "users") in refs
        assert ("", "orders") in refs or (None, "orders") in refs

    def test_extract_table_references_from_query_filters_keywords(self):
        """Test _extract_table_references_from_query filters SQL keywords."""
        analyzer = DependencyAnalyzer()
        query = "SELECT * FROM SELECT WHERE GROUP"
        refs = analyzer._extract_table_references_from_query(query)
        # Should not include SQL keywords
        assert ("", "select") not in refs
        assert ("", "where") not in refs
        assert ("", "group") not in refs

    def test_topological_sort_create_order(self):
        """Test topological_sort for CREATE order."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        analyzer.build_graph([table, view])
        sorted_objs = analyzer.topological_sort([table, view], reverse=False)
        assert sorted_objs.index(table) < sorted_objs.index(view)

    def test_topological_sort_drop_order(self):
        """Test topological_sort for DROP order."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        analyzer.build_graph([table, view])
        sorted_objs = analyzer.topological_sort([table, view], reverse=True)
        assert sorted_objs.index(view) < sorted_objs.index(table)

    def test_topological_sort_with_none_objects(self):
        """Test topological_sort with None objects (uses graph objects)."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        analyzer.build_graph([table, view])
        sorted_objs = analyzer.topological_sort(objects=None, reverse=False)
        assert len(sorted_objs) == 2

    def test_topological_sort_circular_dependency(self):
        """Test topological_sort handles circular dependencies."""
        analyzer = DependencyAnalyzer()
        table1 = Table(name="table1", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table2 = Table(name="table2", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        # Create circular dependency manually
        analyzer.graph.add_object(table1)
        analyzer.graph.add_object(table2)
        analyzer.graph.dependencies[id(table1)].add(id(table2))
        analyzer.graph.dependents[id(table2)].add(id(table1))
        analyzer.graph.dependencies[id(table2)].add(id(table1))
        analyzer.graph.dependents[id(table1)].add(id(table2))
        sorted_objs = analyzer.topological_sort([table1, table2], reverse=False)
        # Should still return all objects even with circular dependency
        assert len(sorted_objs) == 2

    def test_topological_sort_circular_dependency_logs_debug_not_warning(self, caplog):
        """Circular dependency details should stay out of normal command output."""
        analyzer = DependencyAnalyzer()
        table1 = Table(name="table1", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        table2 = Table(name="table2", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        analyzer.graph.add_object(table1)
        analyzer.graph.add_object(table2)
        analyzer.graph.add_dependency(table1, table2)
        analyzer.graph.add_dependency(table2, table1)

        with caplog.at_level(logging.DEBUG, logger="core.sql_generator.dependency_analyzer"):
            sorted_objs = analyzer.topological_sort([table1, table2], reverse=False)

        assert len(sorted_objs) == 2
        circular_records = [
            record
            for record in caplog.records
            if "Circular dependencies detected" in record.message
        ]
        assert circular_records
        assert all(record.levelno == logging.DEBUG for record in circular_records)

    def test_get_create_order(self):
        """Test get_create_order."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        ordered = analyzer.get_create_order([view, table])
        assert ordered.index(table) < ordered.index(view)

    def test_get_drop_order(self):
        """Test get_drop_order."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="active_users", query="SELECT id FROM users", dialect="postgresql")
        ordered = analyzer.get_drop_order([table, view])
        assert ordered.index(view) < ordered.index(table)

    def test_materialized_view_dependency(self):
        """Test materialized view dependency."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        view = View(name="mv_users", query="SELECT id FROM users", dialect="postgresql")
        view.object_type = SqlObjectType.MATERIALIZED_VIEW
        graph = analyzer.build_graph([table, view])
        deps = graph.get_dependencies(view)
        assert table in deps

    def test_procedure_with_body_references(self):
        """Test procedure with body that references tables."""
        analyzer = DependencyAnalyzer()
        table = Table(name="users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")
        # Use FROM clause which is what the extractor looks for
        procedure = Procedure(name="sp_test", body="SELECT * FROM users", dialect="postgresql")
        graph = analyzer.build_graph([table, procedure])
        deps = graph.get_dependencies(procedure)
        assert table in deps

    def test_index_with_table_schema(self):
        """Test index with table_schema attribute."""
        analyzer = DependencyAnalyzer()
        table = Table(
            name="users",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        index = Index(name="idx_id", table_name="users", columns=["id"], dialect="postgresql")
        index.table_schema = "public"
        graph = analyzer.build_graph([table, index])
        deps = graph.get_dependencies(index)
        assert table in deps

    def test_foreign_key_with_reference_schema(self):
        """Test foreign key with reference_schema attribute."""
        analyzer = DependencyAnalyzer()
        table1 = Table(
            name="users",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        table2 = Table(
            name="orders",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("user_id", "INTEGER")],
            dialect="postgresql",
        )
        constraint = SqlConstraint(
            name="fk_orders_user",
            constraint_type=ConstraintType.FOREIGN_KEY,
            column_names=["user_id"],
            reference_table="users",
        )
        constraint.reference_schema = "public"
        table2.constraints = [constraint]
        graph = analyzer.build_graph([table1, table2])
        deps = graph.get_dependencies(table2)
        assert table1 in deps

    def test_system_versioned_with_history_schema(self):
        """Test system-versioned table with history_schema."""
        analyzer = DependencyAnalyzer()
        history_table = Table(
            name="users_history",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        table = Table(
            name="users",
            schema="public",
            columns=[SqlColumn("id", "INTEGER")],
            dialect="postgresql",
        )
        table.system_versioned = True
        table.history_table = "users_history"
        table.history_schema = "public"
        graph = analyzer.build_graph([table, history_table])
        deps = graph.get_dependencies(table)
        assert history_table in deps
