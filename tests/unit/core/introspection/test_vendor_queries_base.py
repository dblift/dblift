"""Comprehensive tests for core.introspection.vendor_queries_base.VendorMetadataQueries."""

import pytest

from core.introspection.vendor_queries_base import VendorMetadataQueries


class ConcreteVendorQueries(VendorMetadataQueries):
    """Concrete implementation of VendorMetadataQueries for testing."""

    def get_check_constraints_query(self, schema: str, table: str):
        return ("SELECT constraint_name, check_clause FROM check_constraints", [])

    def get_sequences_query(self, schema: str):
        return ("SELECT sequence_name FROM sequences", [])

    def get_views_query(self, schema: str):
        return ("SELECT view_name, view_definition FROM views", [])

    def get_view_definition_query(self, schema: str, view_name: str):
        return ("SELECT definition FROM views WHERE name = ?", [view_name])

    def get_indexes_query(self, schema: str, table: str):
        return ("SELECT index_name, column_name FROM indexes", [])


@pytest.mark.unit
class TestVendorMetadataQueries:
    """Test suite for VendorMetadataQueries base class."""

    @pytest.fixture
    def vendor_queries(self):
        """Create a concrete VendorMetadataQueries instance."""
        return ConcreteVendorQueries()

    def test_get_triggers_query_returns_none_by_default(self, vendor_queries):
        """Test get_triggers_query() returns (None, []) by default."""
        query, params = vendor_queries.get_triggers_query("public")
        assert query is None
        assert params == []

        query, params = vendor_queries.get_triggers_query("public", "users")
        assert query is None
        assert params == []

    def test_get_computed_columns_query_returns_none_by_default(self, vendor_queries):
        """Test get_computed_columns_query() returns (None, []) by default."""
        query, params = vendor_queries.get_computed_columns_query("public", "users")
        assert query is None
        assert params == []

    def test_get_identity_columns_query_returns_none_by_default(self, vendor_queries):
        """Test get_identity_columns_query() returns (None, []) by default."""
        query, params = vendor_queries.get_identity_columns_query("public", "users")
        assert query is None
        assert params == []

    def test_get_table_partitions_query_returns_none_by_default(self, vendor_queries):
        """Test get_table_partitions_query() returns (None, []) by default."""
        query, params = vendor_queries.get_table_partitions_query("public", "users")
        assert query is None
        assert params == []

    def test_get_materialized_views_query_returns_none_by_default(self, vendor_queries):
        """Test get_materialized_views_query() returns (None, []) by default."""
        query, params = vendor_queries.get_materialized_views_query("public")
        assert query is None
        assert params == []

    def test_get_procedures_query_returns_none_by_default(self, vendor_queries):
        """Test get_procedures_query() returns (None, []) by default."""
        query, params = vendor_queries.get_procedures_query("public")
        assert query is None
        assert params == []

    def test_get_functions_query_returns_none_by_default(self, vendor_queries):
        """Test get_functions_query() returns (None, []) by default."""
        query, params = vendor_queries.get_functions_query("public")
        assert query is None
        assert params == []

    def test_get_procedure_parameters_query_returns_none_by_default(self, vendor_queries):
        """Test get_procedure_parameters_query() returns (None, []) by default."""
        query, params = vendor_queries.get_procedure_parameters_query("public", "test_proc")
        assert query is None
        assert params == []

    def test_get_procedure_arguments_query_delegates_to_parameters(self, vendor_queries):
        """Test get_procedure_arguments_query() delegates to get_procedure_parameters_query()."""
        query, params = vendor_queries.get_procedure_arguments_query("public", "test_proc")
        assert query is None
        assert params == []

    def test_get_synonyms_query_returns_none_by_default(self, vendor_queries):
        """Test get_synonyms_query() returns (None, []) by default."""
        query, params = vendor_queries.get_synonyms_query("public")
        assert query is None
        assert params == []

    def test_get_database_links_returns_none_by_default(self, vendor_queries):
        """Test get_database_links() returns (None, []) by default."""
        query, params = vendor_queries.get_database_links("public")
        assert query is None
        assert params == []

    def test_get_user_defined_types_query_returns_none_by_default(self, vendor_queries):
        """Test get_user_defined_types_query() returns (None, []) by default."""
        query, params = vendor_queries.get_user_defined_types_query("public")
        assert query is None
        assert params == []

    def test_get_enum_values_query_returns_none_by_default(self, vendor_queries):
        """Test get_enum_values_query() returns (None, []) by default."""
        query, params = vendor_queries.get_enum_values_query("public", "my_enum")
        assert query is None
        assert params == []

    def test_get_composite_type_attributes_query_returns_none_by_default(self, vendor_queries):
        """Test get_composite_type_attributes_query() returns (None, []) by default."""
        query, params = vendor_queries.get_composite_type_attributes_query("public", "my_type")
        assert query is None
        assert params == []

    def test_get_extensions_query_returns_none_by_default(self, vendor_queries):
        """Test get_extensions_query() returns (None, []) by default."""
        query, params = vendor_queries.get_extensions_query("public")
        assert query is None
        assert params == []

        query, params = vendor_queries.get_extensions_query()
        assert query is None
        assert params == []

    def test_supports_check_constraints_returns_true(self, vendor_queries):
        """Test supports_check_constraints() returns True by default."""
        assert vendor_queries.supports_check_constraints() is True

    def test_supports_sequences_returns_true(self, vendor_queries):
        """Test supports_sequences() returns True by default."""
        assert vendor_queries.supports_sequences() is True

    def test_supports_views_returns_true(self, vendor_queries):
        """Test supports_views() returns True by default."""
        assert vendor_queries.supports_views() is True

    def test_supports_triggers_returns_false(self, vendor_queries):
        """Test supports_triggers() returns False by default."""
        assert vendor_queries.supports_triggers() is False

    def test_supports_computed_columns_returns_false(self, vendor_queries):
        """Test supports_computed_columns() returns False by default."""
        assert vendor_queries.supports_computed_columns() is False

    def test_supports_partitions_returns_false(self, vendor_queries):
        """Test supports_partitions() returns False by default."""
        assert vendor_queries.supports_partitions() is False

    def test_supports_materialized_views_returns_false(self, vendor_queries):
        """Test supports_materialized_views() returns False by default."""
        assert vendor_queries.supports_materialized_views() is False

    def test_supports_procedures_returns_false(self, vendor_queries):
        """Test supports_procedures() returns False by default."""
        assert vendor_queries.supports_procedures() is False

    def test_supports_functions_returns_false(self, vendor_queries):
        """Test supports_functions() returns False by default."""
        assert vendor_queries.supports_functions() is False

    def test_supports_synonyms_returns_false(self, vendor_queries):
        """Test supports_synonyms() returns False by default."""
        assert vendor_queries.supports_synonyms() is False

    def test_supports_database_links_returns_false(self, vendor_queries):
        """Test supports_database_links() returns False by default."""
        assert vendor_queries.supports_database_links() is False

    def test_supports_user_defined_types_returns_false(self, vendor_queries):
        """Test supports_user_defined_types() returns False by default."""
        assert vendor_queries.supports_user_defined_types() is False

    def test_supports_extensions_returns_false(self, vendor_queries):
        """Test supports_extensions() returns False by default."""
        assert vendor_queries.supports_extensions() is False

    def test_get_all_indexes_query_returns_none_by_default(self, vendor_queries):
        """Test get_all_indexes_query() returns None by default (bulk not supported)."""
        result = vendor_queries.get_all_indexes_query("public")
        assert result is None

    def test_get_all_indexes_query_can_be_overridden(self):
        """Test that get_all_indexes_query() can be overridden to support bulk retrieval."""

        class BulkCapableVendor(ConcreteVendorQueries):
            def get_all_indexes_query(self, schema: str):
                return ("SELECT * FROM all_indexes WHERE schema = ?", [schema])

        vendor = BulkCapableVendor()
        result = vendor.get_all_indexes_query("myschema")
        assert result is not None
        query, params = result
        assert "all_indexes" in query
        assert params == ["myschema"]

    def test_supports_linked_servers_false_by_default(self, vendor_queries):
        """Base implementation does not support linked servers."""
        assert vendor_queries.supports_linked_servers() is False

    def test_get_linked_servers_query_returns_none_by_default(self, vendor_queries):
        """Base implementation returns (None, []) for linked servers."""
        sql, params = vendor_queries.get_linked_servers_query()
        assert sql is None
        assert params == []

    def test_supports_modules_false_by_default(self, vendor_queries):
        """Base implementation does not support modules."""
        assert vendor_queries.supports_modules() is False

    def test_get_modules_query_returns_none_by_default(self, vendor_queries):
        """Base implementation returns (None, []) for modules."""
        sql, params = vendor_queries.get_modules_query("myschema")
        assert sql is None
        assert params == []
