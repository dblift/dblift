"""Tests for db/introspection/vendor_queries_protocols.py — protocol structural checks."""

import unittest


class TestProtocolStructure(unittest.TestCase):
    def test_itable_queries_is_runtime_checkable(self):
        from core.introspection.vendor_queries_protocols import ITableQueries

        # Mock implementing required methods
        class MockTable:
            def get_table_partitions_query(self, schema, table):
                return ("SELECT 1", [])

            def get_table_properties_query(self, schema, table):
                return ("SELECT 1", [])

            def get_partition_scheme_query(self, schema, table):
                return ("SELECT 1", [])

            def get_table_inheritance_query(self, schema, table):
                return ("SELECT 1", [])

            def get_table_row_security_query(self, schema, table):
                return ("SELECT 1", [])

            def get_policies_query(self, schema, table):
                return ("SELECT 1", [])

            def get_partitioned_tables_query(self, schema):
                return ("SELECT 1", [])

            def supports_partitions(self):
                return False

        self.assertIsInstance(MockTable(), ITableQueries)

    def test_iview_queries_protocol(self):
        from core.introspection.vendor_queries_protocols import IViewQueries

        class MockView:
            def get_views_query(self, schema):
                return ("SELECT 1", [])

            def get_view_definition_query(self, schema, view_name):
                return ("SELECT 1", [])

            def get_materialized_views_query(self, schema):
                return ("SELECT 1", [])

            def supports_views(self):
                return True

            def supports_materialized_views(self):
                return False

        self.assertIsInstance(MockView(), IViewQueries)

    def test_iindex_queries_protocol(self):
        from core.introspection.vendor_queries_protocols import IIndexQueries

        class MockIndex:
            def get_indexes_query(self, schema, table):
                return ("SELECT 1", [])

            def get_all_indexes_query(self, schema):
                return ("SELECT 1", [])

        self.assertIsInstance(MockIndex(), IIndexQueries)

    def test_isequence_queries_protocol(self):
        from core.introspection.vendor_queries_protocols import ISequenceQueries

        class MockSeq:
            def supports_sequences(self):
                return True

            def get_sequences_query(self, schema):
                return ("SELECT 1", [])

        self.assertIsInstance(MockSeq(), ISequenceQueries)

    def test_iconstraint_queries_protocol(self):
        # Story 26-3 / PR #241 Bugbot: ``get_sequences_query`` and
        # ``supports_sequences`` were removed from ``IConstraintQueries``
        # and live on ``ISequenceQueries``. The minimal mock that
        # satisfies ``IConstraintQueries`` therefore omits them — and
        # MUST still pass isinstance.
        from core.introspection.vendor_queries_protocols import IConstraintQueries

        class MockConstr:
            def get_check_constraints_query(self, schema, table):
                return ("SELECT 1", [])

            def get_unique_constraints_query(self, schema, table):
                return ("SELECT 1", [])

            def supports_check_constraints(self):
                return True

        self.assertIsInstance(MockConstr(), IConstraintQueries)

    def test_iconstraint_queries_no_longer_requires_sequence_methods(self):
        # Regression guard against re-adding sequence methods to
        # IConstraintQueries. (PR #241 Bugbot.)
        from core.introspection.vendor_queries_protocols import IConstraintQueries

        protocol_methods = {m for m in dir(IConstraintQueries) if not m.startswith("_")}
        self.assertNotIn("get_sequences_query", protocol_methods)
        self.assertNotIn("supports_sequences", protocol_methods)

    def test_concrete_queries_satisfy_both_constraint_and_sequence_protocols(self):
        # Verifies the ISP split keeps concrete implementations
        # conforming to BOTH protocols. Anyone migrating a typed caller
        # from IConstraintQueries to ISequenceQueries will find the same
        # objects on the other side.
        from core.introspection.vendor_queries_protocols import (
            IConstraintQueries,
            ISequenceQueries,
        )
        from db.plugins.postgresql.introspection.postgresql_queries import (
            PostgreSQLMetadataQueries,
        )

        for attr in ("get_check_constraints_query", "get_unique_constraints_query"):
            self.assertTrue(
                hasattr(PostgreSQLMetadataQueries, attr),
                f"Missing IConstraintQueries.{attr}",
            )
        for attr in ("get_sequences_query", "supports_sequences"):
            self.assertTrue(
                hasattr(PostgreSQLMetadataQueries, attr),
                f"Missing ISequenceQueries.{attr}",
            )

    def test_non_conforming_class_not_instance(self):
        from core.introspection.vendor_queries_protocols import ITableQueries

        class NotATable:
            pass

        self.assertNotIsInstance(NotATable(), ITableQueries)

    def test_postgresql_queries_satisfies_protocols(self):
        from core.introspection.vendor_queries_protocols import ISequenceQueries, IViewQueries
        from db.plugins.postgresql.introspection.postgresql_queries import (
            PostgreSQLMetadataQueries,
        )

        # Check structural conformance at the class level to avoid DB initialisation
        for attr in [
            "get_views_query",
            "get_view_definition_query",
            "get_materialized_views_query",
            "supports_views",
            "supports_materialized_views",
        ]:
            self.assertTrue(
                hasattr(PostgreSQLMetadataQueries, attr), f"Missing IViewQueries.{attr}"
            )
        for attr in ["get_sequences_query", "supports_sequences"]:
            self.assertTrue(
                hasattr(PostgreSQLMetadataQueries, attr), f"Missing ISequenceQueries.{attr}"
            )


class TestProtocolMethods(unittest.TestCase):
    """Test that protocol method signatures match expected usage."""

    def test_itable_queries_methods_callable(self):
        from core.introspection.vendor_queries_protocols import ITableQueries

        # Check all required method names exist in Protocol
        methods = [m for m in dir(ITableQueries) if not m.startswith("_")]
        self.assertIn("get_table_partitions_query", methods)
        self.assertIn("get_table_properties_query", methods)

    def test_isequence_queries_supports_check(self):
        from core.introspection.vendor_queries_protocols import ISequenceQueries

        methods = [m for m in dir(ISequenceQueries) if not m.startswith("_")]
        self.assertIn("supports_sequences", methods)
        self.assertIn("get_sequences_query", methods)
