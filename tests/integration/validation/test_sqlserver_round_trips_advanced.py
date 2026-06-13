"""
SQL Server Advanced Round-Trip Tests.

Comprehensive round-trip tests for advanced SQL Server features.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["sqlserver"],
    indirect=True,
)
class TestSQLServerRoundTripsAdvanced:
    """SQL Server advanced round-trip tests."""

    def _get_provider(self, db_container):
        """Create database provider."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type=db_type,
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=schema,
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_round_trip_advanced", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_computed_columns_round_trip(self, db_container):
        """Test round-trip for tables with computed columns."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[products]")
            except Exception:
                pass

            # Create table with computed columns
            create_table = f"""
            CREATE TABLE [{schema}].[products] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                price DECIMAL(10, 2) NOT NULL,
                quantity INT NOT NULL,
                total_price AS (price * quantity) PERSISTED,
                price_with_tax AS (price * 1.1)
            )
            """
            provider.execute_statement(create_table)

            # Ensure test schema exists
            test_schema = f"{schema}_test"
            provider.create_schema_if_not_exists(test_schema)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=test_schema,
                introspector=introspector,
                test_object_types=["tables"],
            )
            results = tester.run_round_trip_test()

            assert results["success"] is True, f"Round-trip failed: {results.get('errors', [])}"
            assert results["tables"]["reintrospected_count"] >= 1

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[products]")
            except Exception:
                pass
            provider.close()

    def test_filtered_indexes_round_trip(self, db_container):
        """Test round-trip for tables with filtered indexes."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS [{schema}].[orders].[idx_active_orders]"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[orders]")
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE [{schema}].[orders] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                customer_id INT NOT NULL,
                status NVARCHAR(20) NOT NULL,
                order_date DATE NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create filtered index
            create_index = f"""
            CREATE NONCLUSTERED INDEX [idx_active_orders] ON [{schema}].[orders] (order_date)
            WHERE status = 'ACTIVE'
            """
            provider.execute_statement(create_index)

            # Ensure test schema exists
            test_schema = f"{schema}_test"
            provider.create_schema_if_not_exists(test_schema)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=test_schema,
                introspector=introspector,
                test_object_types=["tables", "indexes"],
            )
            results = tester.run_round_trip_test()

            # Round-trip should succeed
            assert (
                results["success"] is True or len(results.get("errors", [])) == 0
            ), f"Round-trip failed with errors: {results.get('errors', [])}"

        finally:
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS [{schema}].[orders].[idx_active_orders]"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[orders]")
            except Exception:
                pass
            provider.close()
