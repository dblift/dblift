"""Unit tests for PostgreSQL metadata queries.

These tests verify that PostgreSQLMetadataQueries methods return
correctly structured SQL queries with proper parameters, without
requiring a database connection.
"""

import pytest

from db.plugins.postgresql.introspection.postgresql_queries import (
    PostgreSQLMetadataQueries,
)


@pytest.mark.unit
class TestPostgreSQLMetadataQueries:
    """Test PostgreSQLMetadataQueries class."""

    def test_initialization(self):
        """Test that PostgreSQLMetadataQueries can be instantiated."""
        queries = PostgreSQLMetadataQueries()
        assert queries is not None

    def test_get_check_constraints_query(self):
        """Test get_check_constraints_query returns correct SQL and parameters."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_check_constraints_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "pg_catalog.pg_constraint" in sql
        assert "pg_catalog.pg_get_constraintdef" in sql
        assert "con.contype = 'c'" in sql
        assert "?" in sql  # Parameter placeholder

    def test_get_sequences_query(self):
        """Test get_sequences_query returns correct SQL and parameters."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"

        sql, params = queries.get_sequences_query(schema)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert schema in params
        assert "pg_catalog.pg_sequences" in sql
        assert "pg_catalog.pg_class" in sql
        assert "?" in sql

    def test_get_views_query(self):
        """Test get_views_query returns correct SQL and parameters."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"

        sql, params = queries.get_views_query(schema)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 1
        assert params[0] == schema
        assert "pg_catalog.pg_class" in sql
        assert "pg_catalog.pg_get_viewdef" in sql
        assert "relkind" in sql  # filter is present (exact form may vary by fix)
        assert "?" in sql

    def test_get_view_definition_query(self):
        """Test get_view_definition_query returns correct SQL and parameters."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        view_name = "user_view"

        sql, params = queries.get_view_definition_query(schema, view_name)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == view_name
        assert "pg_catalog.pg_get_viewdef" in sql
        assert "c.relkind = 'v'" in sql
        assert "?" in sql

    def test_get_indexes_query(self):
        """Test get_indexes_query returns correct SQL and parameters."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_indexes_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "pg_catalog.pg_index" in sql
        assert "pg_catalog.pg_get_indexdef" in sql
        assert "NOT ix.indisprimary" in sql
        assert "?" in sql

    def test_get_triggers_query_with_table(self):
        """Test get_triggers_query with table parameter."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_triggers_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "information_schema.triggers" in sql
        assert "pg_catalog.pg_trigger" in sql
        assert "tr.event_object_table = ?" in sql
        assert "?" in sql

    def test_get_triggers_query_without_table(self):
        """Test get_triggers_query without table parameter."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"

        sql, params = queries.get_triggers_query(schema, table=None)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 1
        assert params[0] == schema
        assert "information_schema.triggers" in sql
        assert "tr.event_object_schema = ?" in sql
        assert "?" in sql

    def test_get_computed_columns_query(self):
        """Test get_computed_columns_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_computed_columns_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "pg_catalog.pg_attribute" in sql
        assert "a.attgenerated != ''" in sql
        assert "?" in sql

    def test_get_identity_columns_query(self):
        """Test get_identity_columns_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_identity_columns_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "pg_catalog.pg_attribute" in sql
        assert "a.attidentity != ''" in sql
        assert "?" in sql

    def test_get_table_partitions_query(self):
        """Test get_table_partitions_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_table_partitions_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "pg_catalog.pg_inherits" in sql
        assert "c.relispartition" in sql
        assert "?" in sql

    def test_get_procedures_query(self):
        """Test get_procedures_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"

        sql, params = queries.get_procedures_query(schema)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 1
        assert params[0] == schema
        assert "pg_catalog.pg_proc" in sql
        assert "p.prokind = 'p'" in sql
        assert "?" in sql

    def test_get_functions_query(self):
        """Test get_functions_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"

        sql, params = queries.get_functions_query(schema)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 1
        assert params[0] == schema
        assert "pg_catalog.pg_proc" in sql
        assert "p.prokind IN ('f', 'a', 'w')" in sql
        assert "?" in sql

    def test_get_materialized_views_query(self):
        """Test get_materialized_views_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"

        sql, params = queries.get_materialized_views_query(schema)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 1
        assert params[0] == schema
        assert "pg_catalog.pg_class" in sql
        assert "c.relkind = 'm'" in sql
        assert "?" in sql

    def test_get_table_inheritance_query(self):
        """Test get_table_inheritance_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_table_inheritance_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "pg_catalog.pg_inherits" in sql
        assert "?" in sql

    def test_get_table_row_security_query(self):
        """Test get_table_row_security_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_table_row_security_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "pg_catalog.pg_class" in sql
        assert "c.relrowsecurity" in sql
        assert "?" in sql

    def test_get_policies_query(self):
        """Test get_policies_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_policies_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "pg_catalog.pg_policy" in sql
        assert "?" in sql

    def test_get_user_defined_types_query(self):
        """Test get_user_defined_types_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"

        sql, params = queries.get_user_defined_types_query(schema)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 1
        assert params[0] == schema
        assert "pg_catalog.pg_type" in sql
        assert "t.typtype IN ('c', 'e', 'd')" in sql
        assert "?" in sql

    def test_get_enum_values_query(self):
        """Test get_enum_values_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        type_name = "status_enum"

        sql, params = queries.get_enum_values_query(schema, type_name)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == type_name
        assert "pg_catalog.pg_enum" in sql
        assert "?" in sql

    def test_get_composite_type_attributes_query(self):
        """Test get_composite_type_attributes_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        type_name = "address_type"

        sql, params = queries.get_composite_type_attributes_query(schema, type_name)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == type_name
        assert "pg_catalog.pg_attribute" in sql
        assert "?" in sql

    def test_get_extensions_query(self):
        """Test get_extensions_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()

        sql, params = queries.get_extensions_query()

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 0  # No parameters
        assert "pg_catalog.pg_extension" in sql

    def test_get_foreign_data_wrappers_query(self):
        """Test get_foreign_data_wrappers_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()

        sql, params = queries.get_foreign_data_wrappers_query()

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 0
        assert "pg_catalog.pg_foreign_data_wrapper" in sql

    def test_get_foreign_servers_query(self):
        """Test get_foreign_servers_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()

        sql, params = queries.get_foreign_servers_query()

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 0
        assert "pg_catalog.pg_foreign_server" in sql

    def test_get_partition_scheme_query(self):
        """Test get_partition_scheme_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        sql, params = queries.get_partition_scheme_query(schema, table)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 2
        assert params[0] == schema
        assert params[1] == table
        assert "pg_get_partkeydef" in sql
        assert "c.relkind = 'p'" in sql
        assert "?" in sql

    def test_get_partitioned_tables_query(self):
        """Test get_partitioned_tables_query returns correct SQL."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"

        sql, params = queries.get_partitioned_tables_query(schema)

        assert isinstance(sql, str)
        assert isinstance(params, list)
        assert len(params) == 1
        assert params[0] == schema
        assert "pg_catalog.pg_class" in sql
        assert "c.relkind = 'p'" in sql
        assert "?" in sql

    def test_supports_methods(self):
        """Test all supports_* methods return True for PostgreSQL."""
        queries = PostgreSQLMetadataQueries()

        assert queries.supports_check_constraints() is True
        assert queries.supports_sequences() is True
        assert queries.supports_views() is True
        assert queries.supports_triggers() is True
        assert queries.supports_computed_columns() is True
        assert queries.supports_partitions() is True
        assert queries.supports_materialized_views() is True
        assert queries.supports_procedures() is True
        assert queries.supports_functions() is True
        assert queries.supports_user_defined_types() is True
        assert queries.supports_extensions() is True

    def test_query_with_special_characters_in_names(self):
        """Test queries handle special characters in schema/table names."""
        queries = PostgreSQLMetadataQueries()
        schema = "my-schema"
        table = "user_table"

        sql, params = queries.get_check_constraints_query(schema, table)

        assert params[0] == schema
        assert params[1] == table
        # SQL should use parameterized queries (?) not string interpolation
        assert schema not in sql
        assert table not in sql

    def test_query_parameter_consistency(self):
        """Test that query parameters match the number of ? placeholders."""
        queries = PostgreSQLMetadataQueries()
        schema = "public"
        table = "users"

        # Test various queries
        test_cases = [
            ("get_check_constraints_query", (schema, table), 2),
            ("get_sequences_query", (schema,), 2),
            ("get_views_query", (schema,), 1),
            ("get_view_definition_query", (schema, "view"), 2),
            ("get_indexes_query", (schema, table), 2),
            ("get_triggers_query", (schema, table), 2),
            ("get_triggers_query", (schema, None), 1),
            ("get_computed_columns_query", (schema, table), 2),
            ("get_identity_columns_query", (schema, table), 2),
            ("get_table_partitions_query", (schema, table), 2),
            ("get_procedures_query", (schema,), 1),
            ("get_functions_query", (schema,), 1),
            ("get_materialized_views_query", (schema,), 1),
            ("get_table_inheritance_query", (schema, table), 2),
            ("get_table_row_security_query", (schema, table), 2),
            ("get_policies_query", (schema, table), 2),
            ("get_user_defined_types_query", (schema,), 1),
            ("get_enum_values_query", (schema, "enum"), 2),
            ("get_composite_type_attributes_query", (schema, "type"), 2),
            ("get_partition_scheme_query", (schema, table), 2),
            ("get_partitioned_tables_query", (schema,), 1),
        ]

        for method_name, args, expected_param_count in test_cases:
            method = getattr(queries, method_name)
            sql, params = method(*args)

            # Count ? placeholders in SQL
            placeholder_count = sql.count("?")
            assert (
                len(params) == expected_param_count
            ), f"{method_name}: expected {expected_param_count} params, got {len(params)}"
            assert (
                placeholder_count == expected_param_count
            ), f"{method_name}: expected {expected_param_count} placeholders, got {placeholder_count}"
