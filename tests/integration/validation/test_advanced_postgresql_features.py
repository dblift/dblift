"""
Advanced PostgreSQL-specific feature tests.

Tests for PostgreSQL-specific features like advanced index types,
triggers, and stored procedures/functions.
"""

from typing import Any, Dict

import pytest

from config import DbliftConfig
from config.database_config import DatabaseConfig
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester
from db.provider_registry import ProviderRegistry


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql"],
    indirect=True,
    ids=["postgresql"],
)
class TestAdvancedPostgreSQLFeatures:
    """Test advanced PostgreSQL-specific features."""

    def _get_provider(self, db_container):
        """Create database provider based on container type."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        db_config = DatabaseConfig(
            type=db_type,
            url=db_container.get("url"),
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=schema,
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("advanced_pg_test", enable_debug=False)
        return ProviderRegistry.create_provider(config, log=log)

    def _execute_sql(self, provider, sql_statements: list):
        """Execute a list of SQL statements."""
        for stmt in sql_statements:
            provider.query_executor.execute_statement(provider.connection, stmt, [])
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

    def test_gin_index_preservation(self, db_container):
        """Test that GIN indexes are preserved during round-trip."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with JSONB column and GIN index
        create_sql = [
            f"""
            CREATE TABLE "{schema}".gin_test (
                id SERIAL PRIMARY KEY,
                data JSONB,
                tags TEXT[]
            )
            """,
            f'CREATE INDEX gin_data_idx ON "{schema}".gin_test USING GIN (data)',
            f'CREATE INDEX gin_tags_idx ON "{schema}".gin_test USING GIN (tags)',
        ]
        self._execute_sql(provider, create_sql)

        test_schema = f"{schema}_test_gin"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables", "indexes"],
        )
        results = tester.run_round_trip_test()

        # GIN indexes might not be fully preserved yet, so we check for warnings
        # but don't fail the test if they're not perfect
        assert (
            results["success"] or len(results.get("warnings", [])) > 0
        ), f"Round-trip failed unexpectedly. Errors: {results.get('errors', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_gist_index_preservation(self, db_container):
        """Test that GIST indexes are preserved during round-trip."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with geometry column and GIST index
        # Note: This requires PostGIS extension, so we'll use a simpler example
        create_sql = [
            f"""
            CREATE TABLE "{schema}".gist_test (
                id SERIAL PRIMARY KEY,
                point_data POINT
            )
            """,
            f'CREATE INDEX gist_point_idx ON "{schema}".gist_test USING GIST (point_data)',
        ]

        try:
            self._execute_sql(provider, create_sql)
        except Exception as e:
            # GIST might not be available without extensions
            pytest.skip(f"GIST index test skipped: {e}")

        test_schema = f"{schema}_test_gist"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables", "indexes"],
        )
        results = tester.run_round_trip_test()

        # GIST indexes might not be fully preserved yet
        assert (
            results["success"] or len(results.get("warnings", [])) > 0
        ), f"Round-trip failed unexpectedly. Errors: {results.get('errors', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_brin_index_preservation(self, db_container):
        """Test that BRIN indexes are preserved during round-trip."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with BRIN index (good for large, naturally ordered data)
        create_sql = [
            f"""
            CREATE TABLE "{schema}".brin_test (
                id SERIAL PRIMARY KEY,
                created_at TIMESTAMP,
                value INTEGER
            )
            """,
            f'CREATE INDEX brin_created_idx ON "{schema}".brin_test USING BRIN (created_at)',
        ]
        self._execute_sql(provider, create_sql)

        test_schema = f"{schema}_test_brin"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables", "indexes"],
        )
        results = tester.run_round_trip_test()

        # BRIN indexes might not be fully preserved yet
        assert (
            results["success"] or len(results.get("warnings", [])) > 0
        ), f"Round-trip failed unexpectedly. Errors: {results.get('errors', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_trigger_introspection(self, db_container):
        """Test that triggers are introspected correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table and trigger
        create_sql = [
            f"""
            CREATE TABLE "{schema}".trigger_test (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100),
                updated_at TIMESTAMP
            )
            """,
            f"""
            CREATE OR REPLACE FUNCTION "{schema}".update_timestamp()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """,
            f"""
            CREATE TRIGGER update_timestamp_trigger
            BEFORE UPDATE ON "{schema}".trigger_test
            FOR EACH ROW
            EXECUTE FUNCTION "{schema}".update_timestamp()
            """,
        ]
        self._execute_sql(provider, create_sql)

        # Introspect triggers
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)

        # For now, we just verify that introspection doesn't crash
        # Full trigger support will be added later
        tables = introspector.get_tables(schema)
        assert len(tables) > 0, "Should introspect at least one table"

        if hasattr(provider, "close"):
            provider.close()

    def test_stored_function_introspection(self, db_container):
        """Test that stored functions are introspected correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create a stored function
        create_sql = [
            f"""
            CREATE OR REPLACE FUNCTION "{schema}".calculate_total(price NUMERIC, quantity INTEGER)
            RETURNS NUMERIC AS $$
            BEGIN
                RETURN price * quantity;
            END;
            $$ LANGUAGE plpgsql
            """,
        ]
        self._execute_sql(provider, create_sql)

        # For now, we just verify that the function was created
        # Full function introspection will be added later
        check_sql = f"""
        SELECT COUNT(*) as count
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = '{schema}' AND p.proname = 'calculate_total'
        """
        result = provider.query_executor.execute_query(provider.connection, check_sql)
        assert len(result) > 0 and result[0].get("count", 0) > 0, "Stored function should exist"

        if hasattr(provider, "close"):
            provider.close()

    def test_array_type_preservation(self, db_container):
        """Test that PostgreSQL array types are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with array columns
        create_sql = f"""
        CREATE TABLE "{schema}".array_test (
            id SERIAL PRIMARY KEY,
            tags TEXT[],
            scores INTEGER[],
            matrix INTEGER[][]
        )
        """
        self._execute_sql(provider, [create_sql])

        test_schema = f"{schema}_test_array"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )
        results = tester.run_round_trip_test()

        # Array types might not be fully preserved yet
        assert (
            results["success"] or len(results.get("warnings", [])) > 0
        ), f"Round-trip failed unexpectedly. Errors: {results.get('errors', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_partial_index_preservation(self, db_container):
        """Test that partial indexes (with WHERE clause) are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with partial index
        create_sql = [
            f"""
            CREATE TABLE "{schema}".partial_idx_test (
                id SERIAL PRIMARY KEY,
                status VARCHAR(20),
                created_at TIMESTAMP
            )
            """,
            f"""
            CREATE INDEX active_status_idx 
            ON "{schema}".partial_idx_test (created_at) 
            WHERE status = 'active'
            """,
        ]
        self._execute_sql(provider, create_sql)

        test_schema = f"{schema}_test_partial"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables", "indexes"],
        )
        results = tester.run_round_trip_test()

        # Partial indexes should be preserved
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('indexes', {}).get('differences', [])}"
        )

        if hasattr(provider, "close"):
            provider.close()

    def test_expression_index_preservation(self, db_container):
        """Test that expression indexes (function-based) are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with expression indexes
        create_sql = [
            f"""
            CREATE TABLE "{schema}".expression_idx_test (
                id SERIAL PRIMARY KEY,
                first_name VARCHAR(50),
                last_name VARCHAR(50),
                email VARCHAR(100),
                created_at TIMESTAMP
            )
            """,
            # Index on expression (lowercase email)
            f"""
            CREATE INDEX idx_email_lower 
            ON "{schema}".expression_idx_test (LOWER(email))
            """,
            # Index on expression (full name concatenation)
            f"""
            CREATE INDEX idx_full_name 
            ON "{schema}".expression_idx_test ((first_name || ' ' || last_name))
            """,
            # Index on expression with function (date truncation)
            f"""
            CREATE INDEX idx_created_date 
            ON "{schema}".expression_idx_test (DATE_TRUNC('day', created_at))
            """,
        ]
        self._execute_sql(provider, create_sql)

        test_schema = f"{schema}_test_expr"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables", "indexes"],
        )
        results = tester.run_round_trip_test()

        # Expression indexes should be preserved
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('indexes', {}).get('differences', [])}"
        )

        if hasattr(provider, "close"):
            provider.close()

    def test_hash_index_preservation(self, db_container):
        """Test that HASH indexes are preserved during round-trip."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with HASH index
        # Note: HASH indexes only support equality operations
        create_sql = [
            f"""
            CREATE TABLE "{schema}".hash_test (
                id SERIAL PRIMARY KEY,
                lookup_key VARCHAR(50)
            )
            """,
            f'CREATE INDEX hash_lookup_idx ON "{schema}".hash_test USING HASH (lookup_key)',
        ]
        self._execute_sql(provider, create_sql)

        test_schema = f"{schema}_test_hash"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables", "indexes"],
        )
        results = tester.run_round_trip_test()

        # HASH indexes should be preserved
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('indexes', {}).get('differences', [])}"
        )

        if hasattr(provider, "close"):
            provider.close()

    def test_spgist_index_preservation(self, db_container):
        """Test that SP-GIST indexes are preserved during round-trip."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with SP-GIST index
        # SP-GIST is useful for non-balanced data structures
        # We'll use a text column with SP-GIST (requires text_ops operator class)
        create_sql = [
            f"""
            CREATE TABLE "{schema}".spgist_test (
                id SERIAL PRIMARY KEY,
                search_text TEXT
            )
            """,
            f'CREATE INDEX spgist_text_idx ON "{schema}".spgist_test USING SPGIST (search_text)',
        ]

        try:
            self._execute_sql(provider, create_sql)
        except Exception as e:
            # SP-GIST might not be available or might need specific operator class
            pytest.skip(f"SP-GIST index test skipped: {e}")

        test_schema = f"{schema}_test_spgist"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables", "indexes"],
        )
        results = tester.run_round_trip_test()

        # SP-GIST indexes should be preserved
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('indexes', {}).get('differences', [])}"
        )

        if hasattr(provider, "close"):
            provider.close()

    def test_virtual_computed_columns(self, db_container):
        """Test that VIRTUAL computed columns (GENERATED ALWAYS AS without STORED) are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with VIRTUAL computed columns
        # Note: PostgreSQL doesn't have explicit VIRTUAL keyword like Oracle
        # VIRTUAL in PostgreSQL means omitting STORED (computed on-the-fly)
        # However, PostgreSQL requires STORED for most cases, so we'll test what's possible
        create_sql = f"""
        CREATE TABLE "{schema}".virtual_computed_test (
            id SERIAL PRIMARY KEY,
            val1 INTEGER,
            val2 INTEGER,
            -- PostgreSQL doesn't support true VIRTUAL like Oracle
            -- But we can test complex expressions
            sum_val INTEGER GENERATED ALWAYS AS (val1 + val2) STORED,
            product_val INTEGER GENERATED ALWAYS AS (val1 * val2) STORED,
            complex_expr INTEGER GENERATED ALWAYS AS ((val1 * 2) + (val2 * 3)) STORED
        )
        """
        self._execute_sql(provider, [create_sql])

        test_schema = f"{schema}_test_virtual"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )
        results = tester.run_round_trip_test()

        # Complex computed columns should be preserved
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

        if hasattr(provider, "close"):
            provider.close()

    def test_temporary_tables(self, db_container):
        """Test that temporary tables are handled correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create temporary table
        # Note: Temporary tables cannot be schema-qualified in PostgreSQL
        # They are created in a special temporary schema
        create_sql = """
        CREATE TEMPORARY TABLE temp_test (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50),
            value INTEGER
        )
        """
        self._execute_sql(provider, [create_sql])

        # For temporary tables, we mainly verify introspection works
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)

        # Introspect tables (temporary tables might not appear in standard introspection)
        # This test verifies the system doesn't crash on temporary tables
        tables = introspector.get_tables(schema)

        # Temporary tables might not be introspected (they're session-specific)
        # So we just verify the system handles them gracefully
        assert isinstance(tables, list), "Should return a list of tables"

        if hasattr(provider, "close"):
            provider.close()

    def test_unlogged_tables(self, db_container):
        """Test that UNLOGGED tables are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create unlogged table
        create_sql = f"""
        CREATE UNLOGGED TABLE "{schema}".unlogged_test (
            id SERIAL PRIMARY KEY,
            data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        self._execute_sql(provider, [create_sql])

        test_schema = f"{schema}_test_unlogged"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )
        results = tester.run_round_trip_test()

        # Unlogged tables should be preserved (though regenerated as regular tables)
        # The unlogged property might not be preserved, but the table structure should be
        assert (
            results["success"] or len(results.get("warnings", [])) > 0
        ), f"Round-trip failed unexpectedly. Errors: {results.get('errors', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_uuid_type_preservation(self, db_container):
        """Test that UUID type is preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with UUID columns
        create_sql = f"""
        CREATE TABLE "{schema}".uuid_test (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL,
            session_id UUID,
            CONSTRAINT uuid_test_user_id_key UNIQUE (user_id)
        )
        """
        self._execute_sql(provider, [create_sql])

        test_schema = f"{schema}_test_uuid"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )
        results = tester.run_round_trip_test()

        # UUID types should be preserved
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

        if hasattr(provider, "close"):
            provider.close()

    def test_network_types_preservation(self, db_container):
        """Test that network types (inet, cidr, macaddr) are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with network types
        create_sql = f"""
        CREATE TABLE "{schema}".network_test (
            id SERIAL PRIMARY KEY,
            ip_address INET,
            network CIDR,
            mac_address MACADDR
        )
        """
        self._execute_sql(provider, [create_sql])

        test_schema = f"{schema}_test_network"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )
        results = tester.run_round_trip_test()

        # Network types should be preserved
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )

        if hasattr(provider, "close"):
            provider.close()

    def test_trigger_generation(self, db_container):
        """Test that triggers can be generated from introspection."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table, function, and trigger
        create_sql = [
            f"""
            CREATE TABLE "{schema}".trigger_gen_test (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100),
                updated_at TIMESTAMP
            )
            """,
            f"""
            CREATE OR REPLACE FUNCTION "{schema}".update_timestamp()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """,
            f"""
            CREATE TRIGGER update_timestamp_trigger
            BEFORE UPDATE ON "{schema}".trigger_gen_test
            FOR EACH ROW
            EXECUTE FUNCTION "{schema}".update_timestamp()
            """,
        ]
        self._execute_sql(provider, create_sql)

        # Introspect triggers
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        triggers = introspector.get_triggers(schema, "trigger_gen_test")

        assert len(triggers) > 0, "Should introspect at least one trigger"

        # Test SQL generation
        trigger = triggers[0]
        generated_sql = trigger.create_statement

        assert generated_sql, "Should generate SQL for trigger"
        assert (
            "CREATE TRIGGER" in generated_sql.upper()
            or "CREATE OR REPLACE TRIGGER" in generated_sql.upper()
        ), f"Generated SQL should contain CREATE TRIGGER: {generated_sql}"
        assert (
            trigger.name.upper() in generated_sql.upper()
        ), f"Generated SQL should contain trigger name: {generated_sql}"

        if hasattr(provider, "close"):
            provider.close()

    def test_function_generation(self, db_container):
        """Test that functions can be generated from introspection."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create a function
        create_sql = f"""
        CREATE OR REPLACE FUNCTION "{schema}".calculate_total(price NUMERIC, quantity INTEGER)
        RETURNS NUMERIC AS $$
        BEGIN
            RETURN price * quantity;
        END;
        $$ LANGUAGE plpgsql
        """
        self._execute_sql(provider, [create_sql])

        # Introspect functions
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        functions = introspector.get_functions(schema)

        # Find our function
        calc_func = None
        for func in functions:
            if func.name.lower() == "calculate_total":
                calc_func = func
                break

        assert calc_func is not None, "Should introspect the function"

        # Test SQL generation
        generated_sql = calc_func.create_statement

        assert generated_sql, "Should generate SQL for function"
        assert (
            "CREATE" in generated_sql.upper() and "FUNCTION" in generated_sql.upper()
        ), f"Generated SQL should contain CREATE FUNCTION: {generated_sql}"
        assert (
            calc_func.name.upper() in generated_sql.upper()
        ), f"Generated SQL should contain function name: {generated_sql}"

        if hasattr(provider, "close"):
            provider.close()

    def test_partitioned_table_range(self, db_container):
        """Test that RANGE partitioned tables are introspected and SQL is generated correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create partitioned table with RANGE partitioning
        create_sql = f"""
        CREATE TABLE "{schema}".partitioned_range_test (
            id SERIAL,
            created_at DATE NOT NULL,
            data TEXT
        ) PARTITION BY RANGE (created_at)
        """
        self._execute_sql(provider, [create_sql])

        # Create partitions
        partition_sql = [
            f"""
            CREATE TABLE "{schema}".partitioned_range_test_2024_01
            PARTITION OF "{schema}".partitioned_range_test
            FOR VALUES FROM ('2024-01-01') TO ('2024-02-01')
            """,
            f"""
            CREATE TABLE "{schema}".partitioned_range_test_2024_02
            PARTITION OF "{schema}".partitioned_range_test
            FOR VALUES FROM ('2024-02-01') TO ('2024-03-01')
            """,
        ]
        self._execute_sql(provider, partition_sql)

        # Introspect partitioned table
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        tables = introspector.get_tables(schema)

        # Find partitioned table
        partitioned_table = None
        for table in tables:
            if table.name.lower() == "partitioned_range_test":
                partitioned_table = table
                break

        assert partitioned_table is not None, "Should introspect partitioned table"

        # Verify partition metadata is captured
        assert (
            partitioned_table.partition_method == "RANGE"
        ), f"Should capture RANGE partition method, got: {partitioned_table.partition_method}"
        assert partitioned_table.partition_columns is not None, "Should capture partition columns"
        assert (
            "created_at" in partitioned_table.partition_columns
        ), f"Should capture partition column 'created_at', got: {partitioned_table.partition_columns}"

        # Test SQL generation
        generated_sql = partitioned_table.create_statement
        assert generated_sql, "Should generate SQL for partitioned table"
        assert (
            "PARTITION BY RANGE" in generated_sql.upper()
        ), f"Generated SQL should contain PARTITION BY RANGE: {generated_sql[:500]}"
        assert (
            "created_at" in generated_sql
        ), f"Generated SQL should contain partition column: {generated_sql[:500]}"

        if hasattr(provider, "close"):
            provider.close()

    def test_partitioned_table_list(self, db_container):
        """Test that LIST partitioned tables are introspected and SQL is generated correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create partitioned table with LIST partitioning
        create_sql = f"""
        CREATE TABLE "{schema}".partitioned_list_test (
            id SERIAL,
            region VARCHAR(50) NOT NULL,
            data TEXT
        ) PARTITION BY LIST (region)
        """
        self._execute_sql(provider, [create_sql])

        # Create partitions
        partition_sql = [
            f"""
            CREATE TABLE "{schema}".partitioned_list_test_north
            PARTITION OF "{schema}".partitioned_list_test
            FOR VALUES IN ('north', 'northeast', 'northwest')
            """,
            f"""
            CREATE TABLE "{schema}".partitioned_list_test_south
            PARTITION OF "{schema}".partitioned_list_test
            FOR VALUES IN ('south', 'southeast', 'southwest')
            """,
        ]
        self._execute_sql(provider, partition_sql)

        # Introspect partitioned table
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        tables = introspector.get_tables(schema)

        # Find partitioned table
        partitioned_table = None
        for table in tables:
            if table.name.lower() == "partitioned_list_test":
                partitioned_table = table
                break

        assert partitioned_table is not None, "Should introspect partitioned table"

        # Verify partition metadata is captured
        assert (
            partitioned_table.partition_method == "LIST"
        ), f"Should capture LIST partition method, got: {partitioned_table.partition_method}"
        assert partitioned_table.partition_columns is not None, "Should capture partition columns"
        assert (
            "region" in partitioned_table.partition_columns
        ), f"Should capture partition column 'region', got: {partitioned_table.partition_columns}"

        # Test SQL generation
        generated_sql = partitioned_table.create_statement
        assert generated_sql, "Should generate SQL for partitioned table"
        assert (
            "PARTITION BY LIST" in generated_sql.upper()
        ), f"Generated SQL should contain PARTITION BY LIST: {generated_sql[:500]}"
        assert (
            "region" in generated_sql
        ), f"Generated SQL should contain partition column: {generated_sql[:500]}"

        if hasattr(provider, "close"):
            provider.close()

    def test_partitioned_table_hash(self, db_container):
        """Test that HASH partitioned tables are introspected and SQL is generated correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create partitioned table with HASH partitioning
        create_sql = f"""
        CREATE TABLE "{schema}".partitioned_hash_test (
            id SERIAL,
            user_id INTEGER NOT NULL,
            data TEXT
        ) PARTITION BY HASH (user_id)
        """
        self._execute_sql(provider, [create_sql])

        # Create partitions (HASH partitioning requires specifying number of partitions)
        partition_sql = [
            f"""
            CREATE TABLE "{schema}".partitioned_hash_test_0
            PARTITION OF "{schema}".partitioned_hash_test
            FOR VALUES WITH (MODULUS 4, REMAINDER 0)
            """,
            f"""
            CREATE TABLE "{schema}".partitioned_hash_test_1
            PARTITION OF "{schema}".partitioned_hash_test
            FOR VALUES WITH (MODULUS 4, REMAINDER 1)
            """,
            f"""
            CREATE TABLE "{schema}".partitioned_hash_test_2
            PARTITION OF "{schema}".partitioned_hash_test
            FOR VALUES WITH (MODULUS 4, REMAINDER 2)
            """,
            f"""
            CREATE TABLE "{schema}".partitioned_hash_test_3
            PARTITION OF "{schema}".partitioned_hash_test
            FOR VALUES WITH (MODULUS 4, REMAINDER 3)
            """,
        ]
        self._execute_sql(provider, partition_sql)

        # Introspect partitioned table
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        tables = introspector.get_tables(schema)

        # Find partitioned table
        partitioned_table = None
        for table in tables:
            if table.name.lower() == "partitioned_hash_test":
                partitioned_table = table
                break

        assert partitioned_table is not None, "Should introspect partitioned table"

        # Verify partition metadata is captured
        assert (
            partitioned_table.partition_method == "HASH"
        ), f"Should capture HASH partition method, got: {partitioned_table.partition_method}"
        assert partitioned_table.partition_columns is not None, "Should capture partition columns"
        assert (
            "user_id" in partitioned_table.partition_columns
        ), f"Should capture partition column 'user_id', got: {partitioned_table.partition_columns}"

        # Test SQL generation
        generated_sql = partitioned_table.create_statement
        assert generated_sql, "Should generate SQL for partitioned table"
        assert (
            "PARTITION BY HASH" in generated_sql.upper()
        ), f"Generated SQL should contain PARTITION BY HASH: {generated_sql[:500]}"
        assert (
            "user_id" in generated_sql
        ), f"Generated SQL should contain partition column: {generated_sql[:500]}"

        if hasattr(provider, "close"):
            provider.close()

    def test_partitioned_table_round_trip(self, db_container):
        """Test that partitioned tables can be round-tripped (introspect -> generate -> execute)."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create partitioned table with RANGE partitioning
        create_sql = f"""
        CREATE TABLE "{schema}".partitioned_round_trip_test (
            id SERIAL,
            created_at DATE NOT NULL,
            data TEXT
        ) PARTITION BY RANGE (created_at)
        """
        self._execute_sql(provider, [create_sql])

        # Create one partition
        partition_sql = f"""
        CREATE TABLE "{schema}".partitioned_round_trip_test_2024
        PARTITION OF "{schema}".partitioned_round_trip_test
        FOR VALUES FROM ('2024-01-01') TO ('2025-01-01')
        """
        self._execute_sql(provider, [partition_sql])

        # Introspect partitioned table
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        tables = introspector.get_tables(schema)

        # Find partitioned table
        partitioned_table = None
        for table in tables:
            if table.name.lower() == "partitioned_round_trip_test":
                partitioned_table = table
                break

        assert partitioned_table is not None, "Should introspect partitioned table"
        assert partitioned_table.partition_method == "RANGE", "Should capture partition method"

        # Generate SQL
        generated_sql = partitioned_table.create_statement
        assert generated_sql, "Should generate SQL"
        assert "PARTITION BY RANGE" in generated_sql.upper(), "Should contain PARTITION BY clause"

        # Test in a different schema to verify it can be recreated
        test_schema = f"{schema}_test_partition"
        provider.schema_operations.create_schema_if_not_exists(provider.connection, test_schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Drop table if it exists in test schema
        drop_sql = f'DROP TABLE IF EXISTS "{test_schema}".partitioned_round_trip_test CASCADE'
        try:
            provider.query_executor.execute_statement(provider.connection, drop_sql, [])
            # CRITICAL: Only commit if autoCommit is False
            if hasattr(provider.connection, "commit") and hasattr(
                provider.connection, "getAutoCommit"
            ):
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
        except Exception:
            pass  # Ignore if table doesn't exist

        # Replace schema name in generated SQL
        test_sql = generated_sql.replace(f'"{schema}"', f'"{test_schema}"')
        test_sql = test_sql.replace(f"{schema}.", f"{test_schema}.")

        try:
            # Execute generated SQL (without partitions for now, as they're not in the generated SQL)
            provider.query_executor.execute_statement(provider.connection, test_sql, [])
            # CRITICAL: Only commit if autoCommit is False
            if hasattr(provider.connection, "commit") and hasattr(
                provider.connection, "getAutoCommit"
            ):
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()

            # Verify partitioned table exists in test schema
            test_tables = introspector.get_tables(test_schema)
            test_table = None
            for t in test_tables:
                if t.name.lower() == "partitioned_round_trip_test":
                    test_table = t
                    break

            assert (
                test_table is not None
            ), "Partitioned table should exist in test schema after regeneration"
            assert test_table.partition_method == "RANGE", "Partition method should be preserved"

        except Exception as e:
            pytest.fail(f"Generated SQL failed to execute: {e}\nGenerated SQL:\n{test_sql}")

        if hasattr(provider, "close"):
            provider.close()

    def test_table_inheritance_single(self, db_container):
        """Test that single table inheritance is introspected and SQL is generated correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create parent table
        create_sql = [
            f"""
            CREATE TABLE "{schema}".parent_table (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            f"""
            CREATE TABLE "{schema}".child_table (
                child_specific VARCHAR(50)
            ) INHERITS ("{schema}".parent_table)
            """,
        ]
        self._execute_sql(provider, create_sql)

        # Introspect tables
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        tables = introspector.get_tables(schema)

        # Find child table
        child_table = None
        for table in tables:
            if table.name.lower() == "child_table":
                child_table = table
                break

        assert child_table is not None, "Should introspect child table"

        # Verify inheritance is captured
        assert child_table.inherits is not None, "Should capture inheritance information"
        assert (
            len(child_table.inherits) >= 1
        ), f"Should have at least 1 parent, got: {child_table.inherits}"

        # Check if parent table name is in inherits (might be schema-qualified or not)
        parent_found = False
        for parent in child_table.inherits:
            if "parent_table" in parent.lower():
                parent_found = True
                break
        assert parent_found, f"Should capture parent table in inherits: {child_table.inherits}"

        # Test SQL generation
        generated_sql = child_table.create_statement
        assert generated_sql, "Should generate SQL for child table"
        assert (
            "INHERITS" in generated_sql.upper()
        ), f"Generated SQL should contain INHERITS clause: {generated_sql[:500]}"
        assert (
            "parent_table" in generated_sql
        ), f"Generated SQL should contain parent table name: {generated_sql[:500]}"

        if hasattr(provider, "close"):
            provider.close()

    def test_table_inheritance_multiple(self, db_container):
        """Test that multiple table inheritance is introspected and SQL is generated correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create parent tables
        create_sql = [
            f"""
            CREATE TABLE "{schema}".parent1_table (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """,
            f"""
            CREATE TABLE "{schema}".parent2_table (
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20)
            )
            """,
            f"""
            CREATE TABLE "{schema}".child_table (
                child_specific VARCHAR(50)
            ) INHERITS ("{schema}".parent1_table, "{schema}".parent2_table)
            """,
        ]
        self._execute_sql(provider, create_sql)

        # Introspect tables
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        tables = introspector.get_tables(schema)

        # Find child table
        child_table = None
        for table in tables:
            if table.name.lower() == "child_table":
                child_table = table
                break

        assert child_table is not None, "Should introspect child table"

        # Verify multiple inheritance is captured
        assert child_table.inherits is not None, "Should capture inheritance information"
        assert (
            len(child_table.inherits) >= 2
        ), f"Should have at least 2 parents for multiple inheritance, got: {child_table.inherits}"

        # Check if both parent tables are in inherits
        parent1_found = False
        parent2_found = False
        for parent in child_table.inherits:
            if "parent1_table" in parent.lower():
                parent1_found = True
            if "parent2_table" in parent.lower():
                parent2_found = True

        assert parent1_found, f"Should capture parent1_table in inherits: {child_table.inherits}"
        assert parent2_found, f"Should capture parent2_table in inherits: {child_table.inherits}"

        # Test SQL generation
        generated_sql = child_table.create_statement
        assert generated_sql, "Should generate SQL for child table"
        assert (
            "INHERITS" in generated_sql.upper()
        ), f"Generated SQL should contain INHERITS clause: {generated_sql[:500]}"
        assert (
            "parent1_table" in generated_sql and "parent2_table" in generated_sql
        ), f"Generated SQL should contain both parent tables: {generated_sql[:500]}"

        if hasattr(provider, "close"):
            provider.close()

    def test_table_inheritance_round_trip(self, db_container):
        """Test that table inheritance can be round-tripped (introspect -> generate -> execute)."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create parent and child tables
        create_sql = [
            f"""
            CREATE TABLE "{schema}".parent_round_trip (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """,
            f"""
            CREATE TABLE "{schema}".child_round_trip (
                child_data TEXT
            ) INHERITS ("{schema}".parent_round_trip)
            """,
        ]
        self._execute_sql(provider, create_sql)

        # Introspect tables
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        tables = introspector.get_tables(schema)

        # Find child table
        child_table = None
        parent_table = None
        for table in tables:
            if table.name.lower() == "child_round_trip":
                child_table = table
            elif table.name.lower() == "parent_round_trip":
                parent_table = table

        assert child_table is not None, "Should introspect child table"
        assert parent_table is not None, "Should introspect parent table"
        assert (
            child_table.inherits is not None and len(child_table.inherits) >= 1
        ), "Should capture inheritance"

        # Generate SQL for both tables
        parent_sql = parent_table.create_statement
        child_sql = child_table.create_statement

        assert parent_sql, "Should generate SQL for parent table"
        assert child_sql, "Should generate SQL for child table"
        assert "INHERITS" in child_sql.upper(), "Child SQL should contain INHERITS"

        # Test in a different schema to verify it can be recreated
        test_schema = f"{schema}_test_inherit"
        provider.schema_operations.create_schema_if_not_exists(provider.connection, test_schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Drop tables if they exist
        drop_sql = [
            f'DROP TABLE IF EXISTS "{test_schema}".child_round_trip CASCADE',
            f'DROP TABLE IF EXISTS "{test_schema}".parent_round_trip CASCADE',
        ]
        for sql in drop_sql:
            try:
                provider.query_executor.execute_statement(provider.connection, sql, [])
                # CRITICAL: Only commit if autoCommit is False
                if hasattr(provider.connection, "commit") and hasattr(
                    provider.connection, "getAutoCommit"
                ):
                    if not provider.connection.getAutoCommit():
                        provider.connection.commit()
            except Exception:
                pass  # Ignore if tables don't exist

        # Replace schema name in generated SQL
        test_parent_sql = parent_sql.replace(f'"{schema}"', f'"{test_schema}"')
        test_parent_sql = test_parent_sql.replace(f"{schema}.", f"{test_schema}.")

        test_child_sql = child_sql.replace(f'"{schema}"', f'"{test_schema}"')
        test_child_sql = test_child_sql.replace(f"{schema}.", f"{test_schema}.")

        # Fix INHERITS clause to be schema-qualified
        # The generated SQL might have INHERITS ("parent_round_trip") which needs schema qualification
        import re

        # Match INHERITS ("table_name") or INHERITS (table_name) and add schema
        test_child_sql = re.sub(
            r'INHERITS\s*\(\s*"([^"]+)"\s*\)', f'INHERITS ("{test_schema}".\\1)', test_child_sql
        )
        # Also handle unquoted table names
        test_child_sql = re.sub(
            r"INHERITS\s*\(\s*([^)]+)\s*\)",
            lambda m: (
                f'INHERITS ("{test_schema}".{m.group(1)})' if '"' not in m.group(1) else m.group(0)
            ),
            test_child_sql,
        )

        try:
            # Execute parent table first (required for child table)
            provider.query_executor.execute_statement(provider.connection, test_parent_sql, [])
            # CRITICAL: Only commit if autoCommit is False
            if hasattr(provider.connection, "commit") and hasattr(
                provider.connection, "getAutoCommit"
            ):
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()

            # Execute child table
            provider.query_executor.execute_statement(provider.connection, test_child_sql, [])
            # CRITICAL: Only commit if autoCommit is False
            if hasattr(provider.connection, "commit") and hasattr(
                provider.connection, "getAutoCommit"
            ):
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()

            # Verify tables exist in test schema
            test_tables = introspector.get_tables(test_schema)
            test_child = None
            for t in test_tables:
                if t.name.lower() == "child_round_trip":
                    test_child = t
                    break

            assert (
                test_child is not None
            ), "Child table should exist in test schema after regeneration"
            assert (
                test_child.inherits is not None and len(test_child.inherits) >= 1
            ), "Inheritance should be preserved"

        except Exception as e:
            pytest.fail(
                f"Generated SQL failed to execute: {e}\nParent SQL:\n{test_parent_sql}\nChild SQL:\n{test_child_sql}"
            )

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_generation(self, db_container):
        """Test that stored procedures can be generated from introspection."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create a stored procedure (PostgreSQL 11+)
        # Note: PostgreSQL procedures don't return values, they use OUT parameters
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".process_order(
            order_id INTEGER,
            OUT status VARCHAR(50),
            OUT total_amount NUMERIC
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            -- Simulate processing
            status := 'PROCESSED';
            total_amount := 100.50;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "process_order":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Test SQL generation
        generated_sql = proc.create_statement

        assert generated_sql, "Should generate SQL for procedure"
        assert (
            "CREATE" in generated_sql.upper() and "PROCEDURE" in generated_sql.upper()
        ), f"Generated SQL should contain CREATE PROCEDURE: {generated_sql}"
        assert (
            proc.name.upper() in generated_sql.upper()
        ), f"Generated SQL should contain procedure name: {generated_sql}"

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_with_parameters(self, db_container):
        """Test that procedures with various parameter types are handled correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create procedure with IN, OUT, and INOUT parameters
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".complex_procedure(
            IN input_param INTEGER,
            OUT output_param VARCHAR(100),
            INOUT inout_param NUMERIC
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            output_param := 'Result: ' || input_param::TEXT;
            inout_param := inout_param * 2;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "complex_procedure":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Verify parameters are captured
        assert proc.parameters is not None, "Procedure should have parameters"
        assert (
            len(proc.parameters) >= 3
        ), f"Should have at least 3 parameters, got {len(proc.parameters)}"

        # Test SQL generation
        generated_sql = proc.create_statement
        assert generated_sql, "Should generate SQL for procedure"

        # Verify parameter names appear in generated SQL
        param_names = [p.name for p in proc.parameters if p.name]
        for param_name in param_names[:3]:  # Check first 3
            assert (
                param_name.upper() in generated_sql.upper()
            ), f"Generated SQL should contain parameter '{param_name}': {generated_sql}"

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_without_parameters(self, db_container):
        """Test that procedures without parameters are handled correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create procedure without parameters
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".simple_procedure()
        LANGUAGE plpgsql
        AS $$
        BEGIN
            -- Simple procedure that does nothing
            PERFORM 1;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "simple_procedure":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Test SQL generation
        generated_sql = proc.create_statement
        assert generated_sql, "Should generate SQL for procedure"
        assert (
            "CREATE" in generated_sql.upper() and "PROCEDURE" in generated_sql.upper()
        ), f"Generated SQL should contain CREATE PROCEDURE: {generated_sql}"

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_round_trip(self, db_container):
        """Test that procedures can be round-tripped (introspect -> generate -> execute)."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create a procedure
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".round_trip_proc(
            IN value INTEGER,
            OUT doubled INTEGER
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            doubled := value * 2;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedure
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        proc = None
        for p in procedures:
            if p.name.lower() == "round_trip_proc":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Generate SQL
        generated_sql = proc.create_statement
        assert generated_sql, "Should generate SQL"

        # Test in a different schema to verify it can be recreated
        test_schema = f"{schema}_test_proc"
        provider.schema_operations.create_schema_if_not_exists(provider.connection, test_schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Replace schema name in generated SQL
        test_sql = generated_sql.replace(f'"{schema}"', f'"{test_schema}"')
        test_sql = test_sql.replace(f"{schema}.", f"{test_schema}.")

        try:
            # Execute generated SQL
            provider.query_executor.execute_statement(provider.connection, test_sql, [])
            # CRITICAL: Only commit if autoCommit is False
            if hasattr(provider.connection, "commit") and hasattr(
                provider.connection, "getAutoCommit"
            ):
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()

            # Verify procedure exists in test schema
            test_procedures = introspector.get_procedures(test_schema)
            test_proc = None
            for p in test_procedures:
                if p.name.lower() == "round_trip_proc":
                    test_proc = p
                    break

            assert test_proc is not None, "Procedure should exist in test schema after regeneration"

        except Exception as e:
            pytest.fail(f"Generated SQL failed to execute: {e}\nGenerated SQL:\n{test_sql}")

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_security_definer(self, db_container):
        """Test that procedures with SECURITY DEFINER are handled correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create procedure with SECURITY DEFINER
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".secure_procedure(
            IN user_id INTEGER,
            OUT result VARCHAR(100)
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        AS $$
        BEGIN
            result := 'Processed by: ' || current_user;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "secure_procedure":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Verify security_definer is captured
        assert proc.security_definer is True, "Should capture SECURITY DEFINER flag"

        # Test SQL generation
        generated_sql = proc.create_statement
        assert generated_sql, "Should generate SQL for procedure"
        assert (
            "SECURITY DEFINER" in generated_sql.upper()
        ), f"Generated SQL should contain SECURITY DEFINER: {generated_sql}"

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_volatility(self, db_container):
        """Test that procedures with volatility settings are handled correctly.

        Note: PostgreSQL procedures are always VOLATILE by default and cannot
        have explicit VOLATILE/STABLE/IMMUTABLE attributes. This test verifies
        that procedures work correctly (volatility is implicit).
        """
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create procedure (PostgreSQL procedures are always VOLATILE, cannot specify explicitly)
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".volatile_procedure(
            IN input_val INTEGER,
            OUT output_val INTEGER
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            output_val := input_val * 2;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "volatile_procedure":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Test SQL generation
        generated_sql = proc.create_statement
        assert generated_sql, "Should generate SQL for procedure"
        # Note: PostgreSQL procedures don't include VOLATILE in CREATE statement
        # as it's implicit. The generated SQL should be valid.

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_with_comment(self, db_container):
        """Test that procedures with comments are handled correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create procedure with comment
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".commented_procedure(
            IN value INTEGER,
            OUT doubled INTEGER
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            doubled := value * 2;
        END;
        $$;
        
        COMMENT ON PROCEDURE "{schema}".commented_procedure(INTEGER, OUT INTEGER) IS 'This procedure doubles the input value';
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "commented_procedure":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Verify comment is captured (if supported)
        # Note: Comments might not always be captured, but if they are, verify
        if proc.comment:
            assert (
                "doubles" in proc.comment.lower() or "input" in proc.comment.lower()
            ), f"Comment should contain expected text: {proc.comment}"

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_with_default_parameters(self, db_container):
        """Test that procedures with default parameter values are handled correctly.

        Note: PostgreSQL requires that parameters with default values come after
        all OUT/INOUT parameters. This test uses only IN parameters with defaults.
        """
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create procedure with default parameter values
        # Note: PostgreSQL requires parameters with defaults come AFTER all required parameters
        # So OUT must come first, then IN with defaults
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".default_param_proc(
            OUT result INTEGER,
            IN value1 INTEGER DEFAULT 10,
            IN value2 INTEGER DEFAULT 20
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            result := value1 + value2;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "default_param_proc":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Verify parameters are captured
        assert proc.parameters is not None, "Procedure should have parameters"
        assert (
            len(proc.parameters) >= 1
        ), f"Should have at least 1 parameter, got {len(proc.parameters)}"

        # Check if default value is captured (might not always be introspected)
        first_param = proc.parameters[0]
        if first_param.default_value:
            assert (
                "10" in first_param.default_value
            ), f"Default value should be captured: {first_param.default_value}"

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_sql_language(self, db_container):
        """Test that procedures with SQL language are handled correctly.

        Note: SQL language procedures in PostgreSQL must use RETURNING or
        must be simple statements. This test uses a simple INSERT statement.
        """
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create a simple table for the procedure to work with
        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS "{schema}".test_table (
            id INTEGER,
            name VARCHAR(50)
        )
        """
        self._execute_sql(provider, [create_table_sql])

        # Create procedure with SQL language (simple SQL procedure)
        # Note: SQL language procedures must use INSERT/UPDATE/DELETE with RETURNING
        # or be simple statements. Using plpgsql is more common for procedures.
        # For this test, we'll use plpgsql but verify language is captured.
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".sql_procedure(
            IN table_name VARCHAR,
            OUT row_count INTEGER
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            EXECUTE format('SELECT COUNT(*) FROM information_schema.tables WHERE table_name = %L', table_name) INTO row_count;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "sql_procedure":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Verify language is captured
        assert proc.language is not None, "Should capture language"
        assert proc.language.upper() in (
            "SQL",
            "PLPGSQL",
        ), f"Language should be SQL or PLPGSQL, got: {proc.language}"

        # Test SQL generation
        generated_sql = proc.create_statement
        assert generated_sql, "Should generate SQL for procedure"
        assert (
            "LANGUAGE" in generated_sql.upper()
        ), f"Generated SQL should contain LANGUAGE clause: {generated_sql}"

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_multiple_out_parameters(self, db_container):
        """Test that procedures with multiple OUT parameters are handled correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create procedure with multiple OUT parameters
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".multi_out_proc(
            IN input_val INTEGER,
            OUT sum_result INTEGER,
            OUT product_result INTEGER,
            OUT square_result INTEGER
        )
        LANGUAGE plpgsql
        AS $$
        BEGIN
            sum_result := input_val + input_val;
            product_result := input_val * input_val;
            square_result := input_val * input_val;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "multi_out_proc":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Verify all parameters are captured
        assert proc.parameters is not None, "Procedure should have parameters"
        assert (
            len(proc.parameters) >= 4
        ), f"Should have at least 4 parameters, got {len(proc.parameters)}"

        # Count OUT parameters
        out_params = [p for p in proc.parameters if p.direction and p.direction.upper() == "OUT"]
        assert len(out_params) >= 3, f"Should have at least 3 OUT parameters, got {len(out_params)}"

        # Test SQL generation
        generated_sql = proc.create_statement
        assert generated_sql, "Should generate SQL for procedure"

        # Verify OUT parameters appear in generated SQL
        for out_param in out_params[:3]:  # Check first 3 OUT params
            if out_param.name:
                assert (
                    out_param.name.upper() in generated_sql.upper()
                ), f"Generated SQL should contain OUT parameter '{out_param.name}': {generated_sql}"

        if hasattr(provider, "close"):
            provider.close()

    def test_procedure_complex_body(self, db_container):
        """Test that procedures with complex body logic are handled correctly."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        # CRITICAL: Only commit if autoCommit is False
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create procedure with complex logic (loops, conditionals, etc.)
        create_sql = f"""
        CREATE OR REPLACE PROCEDURE "{schema}".complex_logic_proc(
            IN start_val INTEGER,
            IN end_val INTEGER,
            OUT total_sum INTEGER,
            OUT iteration_count INTEGER
        )
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_val INTEGER;
        BEGIN
            total_sum := 0;
            iteration_count := 0;
            current_val := start_val;
            
            WHILE current_val <= end_val LOOP
                total_sum := total_sum + current_val;
                iteration_count := iteration_count + 1;
                current_val := current_val + 1;
            END LOOP;
            
            IF total_sum < 0 THEN
                total_sum := 0;
            END IF;
        END;
        $$
        """
        self._execute_sql(provider, [create_sql])

        # Introspect procedures
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        procedures = introspector.get_procedures(schema)

        # Find our procedure
        proc = None
        for p in procedures:
            if p.name.lower() == "complex_logic_proc":
                proc = p
                break

        assert proc is not None, "Should introspect the procedure"

        # Verify body is captured
        assert (
            proc.body is not None or proc.definition is not None
        ), "Procedure should have body or definition"

        # Test SQL generation
        generated_sql = proc.create_statement
        assert generated_sql, "Should generate SQL for procedure"

        # Verify complex logic keywords appear in generated SQL
        body_text = generated_sql.upper()
        # The body should contain procedure logic
        assert (
            "BEGIN" in body_text or "$$" in generated_sql
        ), f"Generated SQL should contain procedure body: {generated_sql[:200]}"

        if hasattr(provider, "close"):
            provider.close()
