"""
SQL Server Comprehensive Tests.

Tests combining multiple features in complex scenarios.
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
class TestSQLServerComprehensive:
    """SQL Server comprehensive feature tests."""

    def test_all_features_combined(self, db_container):
        """Test table with all features: IDENTITY, computed columns, indexes, constraints."""
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
        log = ConsoleLog("sqlserver_comprehensive_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.order_items"

            # Clean up if exists
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS {schema}.idx_active_items ON {table_name}"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with all features
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY IDENTITY(1,1),
                order_id INT NOT NULL,
                product_id INT NOT NULL,
                quantity INT NOT NULL,
                unit_price DECIMAL(10, 2) NOT NULL,
                line_total AS (quantity * unit_price) PERSISTED,
                status NVARCHAR(50) NOT NULL DEFAULT 'PENDING',
                created_date DATETIME NOT NULL DEFAULT GETDATE(),
                UNIQUE (order_id, product_id),
                CHECK (quantity > 0),
                CHECK (unit_price > 0)
            )
            """
            create_index = f"""
            CREATE INDEX idx_active_items ON {table_name}(order_id)
            INCLUDE (product_id, line_total)
            WHERE status = 'ACTIVE'
            """

            provider.execute_statement(create_table)
            provider.execute_statement(create_index)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)

            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables", "indexes"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('tables', {}).get('differences', [])}"
            )

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.order_items")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_complex_schema_round_trip(self, db_container):
        """Test complex schema with tables, views, procedures, functions, triggers."""
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
        log = ConsoleLog("sqlserver_comprehensive_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.audit_products")
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetProductById")
                provider.execute_statement(f"DROP FUNCTION IF EXISTS {schema}.CalculateDiscount")
                provider.execute_statement(f"DROP VIEW IF EXISTS {schema}.product_summary")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.audit_log")
            except Exception:
                pass

            # Create complex schema
            create_audit = f"""
            CREATE TABLE {schema}.audit_log (
                id INT PRIMARY KEY IDENTITY(1,1),
                table_name NVARCHAR(100),
                action NVARCHAR(50),
                timestamp DATETIME DEFAULT GETDATE()
            )
            """
            create_products = f"""
            CREATE TABLE {schema}.products (
                id INT PRIMARY KEY IDENTITY(1,1),
                name NVARCHAR(100) NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                discount DECIMAL(5, 2) DEFAULT 0,
                final_price AS (price * (1 - discount / 100)) PERSISTED
            )
            """
            create_view = f"""
            CREATE VIEW {schema}.product_summary AS
            SELECT id, name, final_price FROM {schema}.products
            """
            create_proc = f"""
            CREATE PROCEDURE {schema}.GetProductById
                @ProductId INT
            AS
            BEGIN
                SELECT * FROM {schema}.products WHERE id = @ProductId;
            END
            """
            create_func = f"""
            CREATE FUNCTION {schema}.CalculateDiscount(@price DECIMAL(10,2), @discount DECIMAL(5,2))
            RETURNS DECIMAL(10,2)
            AS
            BEGIN
                RETURN @price * (1 - @discount / 100);
            END
            """
            create_trigger = f"""
            CREATE TRIGGER {schema}.audit_products
            ON {schema}.products
            AFTER INSERT, UPDATE
            AS
            BEGIN
                INSERT INTO {schema}.audit_log (table_name, action, timestamp)
                VALUES ('products', 'INSERT/UPDATE', GETDATE());
            END
            """

            provider.execute_statement(create_audit)
            provider.execute_statement(create_products)
            provider.execute_statement(create_view)
            provider.execute_statement(create_proc)
            provider.execute_statement(create_func)
            provider.execute_statement(create_trigger)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)

            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables", "views", "procedures", "functions", "triggers"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('tables', {}).get('differences', [])}"
            )

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.audit_products")
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.GetProductById")
                provider.execute_statement(f"DROP FUNCTION IF EXISTS {schema}.CalculateDiscount")
                provider.execute_statement(f"DROP VIEW IF EXISTS {schema}.product_summary")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.audit_log")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()
