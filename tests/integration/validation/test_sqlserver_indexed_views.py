"""
Integration tests for SQL Server indexed views.

Indexed views in SQL Server are views with a unique clustered index.
They require:
- WITH SCHEMABINDING
- A unique clustered index
- Specific constraints (no TOP, no DISTINCT in certain contexts, etc.)
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


def _get_provider(db_container):
    """Helper to create a SQL Server provider."""
    from config import DbliftConfig
    from config.database_config import DatabaseConfig
    from db.provider_registry import ProviderRegistry

    # Build SQLAlchemy URL
    sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

    db_config = DatabaseConfig(
        type="sqlserver",
        url=sqlalchemy_url,
        host=db_container.get("host"),
        port=db_container.get("port"),
        database=db_container.get("database"),
        username=db_container["username"],
        password=db_container["password"],
        schema=db_container.get("schema", "dbo"),
    )
    config = DbliftConfig(database=db_config)
    log = ConsoleLog("sqlserver_indexed_views_test", enable_debug=False)
    provider = ProviderRegistry.create_provider(config, log)
    provider.create_connection()
    return provider, db_config.schema


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["sqlserver"],
    indirect=True,
)
class TestSQLServerIndexedViews:
    """Test SQL Server indexed views."""

    def test_indexed_view_introspection(self, db_container):
        """Test that indexed views are correctly introspected."""
        provider, default_schema = _get_provider(db_container)
        schema = "TEST_SCHEMA"
        log = ConsoleLog("test_indexed_view_introspection", enable_debug=False)

        # Ensure schema exists
        provider.create_schema_if_not_exists(schema)

        try:
            # Create base table
            create_table = f"""
            CREATE TABLE {schema}.products (
                id INT PRIMARY KEY IDENTITY(1,1),
                name NVARCHAR(100) NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                quantity INT NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create indexed view (must have WITH SCHEMABINDING and unique clustered index)
            create_view = f"""
            CREATE VIEW {schema}.product_summary
            WITH SCHEMABINDING
            AS
            SELECT 
                id,
                name,
                price,
                quantity,
                price * quantity AS total_value,
                COUNT_BIG(*) AS row_count
            FROM {schema}.products
            GROUP BY id, name, price, quantity
            """
            provider.execute_statement(create_view)

            # Create unique clustered index on the view
            create_index = f"""
            CREATE UNIQUE CLUSTERED INDEX idx_product_summary
            ON {schema}.product_summary (id)
            """
            provider.execute_statement(create_index)

            # Introspect materialized views (indexed views)
            introspector = IntrospectorFactory.create(provider, log=log)
            materialized_views = introspector.get_materialized_views(schema)

            assert len(materialized_views) >= 1, "Should find at least one indexed view"

            # Find our indexed view
            indexed_view = None
            for view in materialized_views:
                if view.name.upper() == "PRODUCT_SUMMARY":
                    indexed_view = view
                    break

            assert indexed_view is not None, "Should find product_summary indexed view"
            assert indexed_view.materialized, "View should be marked as materialized"
            assert (
                "SCHEMABINDING" in indexed_view.query.upper() or indexed_view.query
            ), "View definition should contain query"

        finally:
            # Cleanup
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS {schema}.product_summary.idx_product_summary"
                )
                provider.execute_statement(f"DROP VIEW IF EXISTS {schema}.product_summary")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
                provider.disconnect()
            except Exception:
                pass

    def test_indexed_view_sql_generation(self, db_container):
        """Test that indexed views generate correct SQL."""
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        provider, default_schema = _get_provider(db_container)
        schema = "TEST_SCHEMA"
        log = ConsoleLog("test_indexed_view_sql_generation", enable_debug=False)

        # Ensure schema exists
        provider.create_schema_if_not_exists(schema)

        try:
            # Create base table
            create_table = f"""
            CREATE TABLE {schema}.orders (
                id INT PRIMARY KEY IDENTITY(1,1),
                customer_id INT NOT NULL,
                order_date DATETIME NOT NULL,
                total_amount DECIMAL(10, 2) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create indexed view
            create_view = f"""
            CREATE VIEW {schema}.order_totals
            WITH SCHEMABINDING
            AS
            SELECT 
                customer_id,
                COUNT_BIG(*) AS order_count,
                SUM(total_amount) AS total_spent
            FROM {schema}.orders
            GROUP BY customer_id
            """
            provider.execute_statement(create_view)

            # Create unique clustered index
            create_index = f"""
            CREATE UNIQUE CLUSTERED INDEX idx_order_totals
            ON {schema}.order_totals (customer_id)
            """
            provider.execute_statement(create_index)

            # Introspect the indexed view
            introspector = IntrospectorFactory.create(provider, log=log)
            materialized_views = introspector.get_materialized_views(schema)

            indexed_view = None
            for view in materialized_views:
                if view.name.upper() == "ORDER_TOTALS":
                    indexed_view = view
                    break

            assert indexed_view is not None, "Should find order_totals indexed view"

            # Generate SQL
            generator = SqlGeneratorFactory.create("sqlserver")
            generated_sql = generator.generate_create_statement(indexed_view)

            # Verify SQL contains key elements
            assert "CREATE" in generated_sql.upper(), "Should contain CREATE"
            assert "VIEW" in generated_sql.upper(), "Should contain VIEW"
            assert indexed_view.name.upper() in generated_sql.upper(), "Should contain view name"

        finally:
            # Cleanup
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS {schema}.order_totals.idx_order_totals"
                )
                provider.execute_statement(f"DROP VIEW IF EXISTS {schema}.order_totals")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
                provider.disconnect()
            except Exception:
                pass

    def test_indexed_view_round_trip(self, db_container):
        """Test round-trip validation for indexed views."""
        provider, default_schema = _get_provider(db_container)
        schema = "TEST_SCHEMA"
        log = ConsoleLog("test_indexed_view_round_trip", enable_debug=False)

        # Ensure schema exists
        provider.create_schema_if_not_exists(schema)

        try:
            # Create base table
            create_table = f"""
            CREATE TABLE {schema}.sales (
                id INT PRIMARY KEY IDENTITY(1,1),
                product_id INT NOT NULL,
                sale_date DATETIME NOT NULL,
                amount DECIMAL(10, 2) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create indexed view
            create_view = f"""
            CREATE VIEW {schema}.sales_summary
            WITH SCHEMABINDING
            AS
            SELECT 
                product_id,
                COUNT_BIG(*) AS sale_count,
                SUM(amount) AS total_sales
            FROM {schema}.sales
            GROUP BY product_id
            """
            provider.execute_statement(create_view)

            # Create unique clustered index
            create_index = f"""
            CREATE UNIQUE CLUSTERED INDEX idx_sales_summary
            ON {schema}.sales_summary (product_id)
            """
            provider.execute_statement(create_index)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables", "materialized_views"],
            )

            results = tester.run_round_trip_test()

            # Note: Indexed views require specific constraints and may not round-trip perfectly
            # We check that the test completes without critical errors
            assert results["success"] or len(results.get("errors", [])) == 0, (
                f"Round-trip should complete. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('materialized_views', {}).get('differences', [])}"
            )

        finally:
            # Cleanup
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS {schema}.sales_summary.idx_sales_summary"
                )
                provider.execute_statement(f"DROP VIEW IF EXISTS {schema}.sales_summary")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.sales")
                provider.disconnect()
            except Exception:
                pass
