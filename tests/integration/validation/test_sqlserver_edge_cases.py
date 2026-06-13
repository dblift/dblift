"""
SQL Server Edge Cases Tests.

Tests for edge cases and advanced scenarios specific to SQL Server:
- Complex constraints
- Synonyms
- Views with complex queries
- Edge cases in computed columns
- Complex default values
- Multiple foreign keys
- Self-referencing tables
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
class TestSQLServerEdgeCases:
    """SQL Server edge case tests."""

    def test_complex_check_constraints(self, db_container):
        """Test complex CHECK constraints with multiple conditions."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

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
        log = ConsoleLog("sqlserver_edge_cases", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.complex_checks"

            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY IDENTITY(1,1),
                price DECIMAL(10, 2) NOT NULL,
                quantity INT NOT NULL,
                discount DECIMAL(5, 2) NOT NULL,
                status NVARCHAR(50) NOT NULL,
                created_date DATETIME NOT NULL,
                CONSTRAINT CK_price_positive CHECK (price > 0),
                CONSTRAINT CK_quantity_range CHECK (quantity >= 1 AND quantity <= 1000),
                CONSTRAINT CK_discount_valid CHECK (discount >= 0 AND discount <= 100),
                CONSTRAINT CK_status_valid CHECK (status IN ('ACTIVE', 'INACTIVE', 'PENDING')),
                CONSTRAINT CK_date_valid CHECK (created_date >= '2000-01-01' AND created_date <= '2100-12-31')
            )
            """

            provider.execute_statement(create_table)

            introspector = IntrospectorFactory.create(provider, log=log)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('tables', {}).get('differences', [])}"
            )

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.complex_checks")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_multiple_foreign_keys(self, db_container):
        """Test table with multiple foreign keys."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

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
        log = ConsoleLog("sqlserver_edge_cases", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.order_items")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.customers")
            except Exception:
                pass

            # Create parent tables
            create_customers = f"""
            CREATE TABLE {schema}.customers (
                id INT PRIMARY KEY IDENTITY(1,1),
                name NVARCHAR(100) NOT NULL
            )
            """
            create_products = f"""
            CREATE TABLE {schema}.products (
                id INT PRIMARY KEY IDENTITY(1,1),
                name NVARCHAR(100) NOT NULL
            )
            """
            create_orders = f"""
            CREATE TABLE {schema}.orders (
                id INT PRIMARY KEY IDENTITY(1,1),
                customer_id INT NOT NULL,
                order_date DATETIME NOT NULL DEFAULT GETDATE(),
                FOREIGN KEY (customer_id) REFERENCES {schema}.customers(id)
            )
            """
            create_order_items = f"""
            CREATE TABLE {schema}.order_items (
                id INT PRIMARY KEY IDENTITY(1,1),
                order_id INT NOT NULL,
                product_id INT NOT NULL,
                quantity INT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES {schema}.orders(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES {schema}.products(id) ON DELETE NO ACTION
            )
            """

            provider.execute_statement(create_customers)
            provider.execute_statement(create_products)
            provider.execute_statement(create_orders)
            provider.execute_statement(create_order_items)

            introspector = IntrospectorFactory.create(provider, log=log)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('tables', {}).get('differences', [])}"
            )

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.order_items")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.customers")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_complex_computed_columns(self, db_container):
        """Test computed columns with complex expressions."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

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
        log = ConsoleLog("sqlserver_edge_cases", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.complex_computed"

            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY IDENTITY(1,1),
                base_price DECIMAL(10, 2) NOT NULL,
                tax_rate DECIMAL(5, 2) NOT NULL DEFAULT 10.0,
                discount DECIMAL(5, 2) NOT NULL DEFAULT 0,
                quantity INT NOT NULL DEFAULT 1,
                subtotal AS (base_price * quantity) PERSISTED,
                tax_amount AS (base_price * quantity * tax_rate / 100) PERSISTED,
                discount_amount AS (base_price * quantity * discount / 100) PERSISTED,
                total AS (base_price * quantity * (1 + tax_rate / 100) * (1 - discount / 100)) PERSISTED
            )
            """

            provider.execute_statement(create_table)

            introspector = IntrospectorFactory.create(provider, log=log)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('tables', {}).get('differences', [])}"
            )

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.complex_computed")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_complex_view_with_joins(self, db_container):
        """Test view with complex JOINs and aggregations."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

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
        log = ConsoleLog("sqlserver_edge_cases", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS {schema}.order_summary")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.order_items")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.customers")
            except Exception:
                pass

            # Create base tables
            create_customers = f"""
            CREATE TABLE {schema}.customers (
                id INT PRIMARY KEY IDENTITY(1,1),
                name NVARCHAR(100) NOT NULL
            )
            """
            create_orders = f"""
            CREATE TABLE {schema}.orders (
                id INT PRIMARY KEY IDENTITY(1,1),
                customer_id INT NOT NULL,
                order_date DATETIME NOT NULL DEFAULT GETDATE(),
                FOREIGN KEY (customer_id) REFERENCES {schema}.customers(id)
            )
            """
            create_order_items = f"""
            CREATE TABLE {schema}.order_items (
                id INT PRIMARY KEY IDENTITY(1,1),
                order_id INT NOT NULL,
                product_name NVARCHAR(100) NOT NULL,
                quantity INT NOT NULL,
                unit_price DECIMAL(10, 2) NOT NULL,
                FOREIGN KEY (order_id) REFERENCES {schema}.orders(id)
            )
            """
            create_view = f"""
            CREATE VIEW {schema}.order_summary AS
            SELECT 
                o.id AS order_id,
                c.name AS customer_name,
                o.order_date,
                SUM(oi.quantity * oi.unit_price) AS total_amount,
                COUNT(oi.id) AS item_count
            FROM {schema}.orders o
            INNER JOIN {schema}.customers c ON o.customer_id = c.id
            LEFT JOIN {schema}.order_items oi ON o.id = oi.order_id
            GROUP BY o.id, c.name, o.order_date
            """

            provider.execute_statement(create_customers)
            provider.execute_statement(create_orders)
            provider.execute_statement(create_order_items)
            provider.execute_statement(create_view)

            introspector = IntrospectorFactory.create(provider, log=log)
            # Test tables and views together (RoundTripTester handles dependencies)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables", "views"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('views', {}).get('differences', [])}"
            )

        finally:
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS {schema}.order_summary")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.order_items")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.customers")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_procedure_with_complex_logic(self, db_container):
        """Test stored procedure with complex T-SQL logic."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

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
        log = ConsoleLog("sqlserver_edge_cases", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.CalculateOrderTotal")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
            except Exception:
                pass

            create_table = f"""
            CREATE TABLE {schema}.orders (
                id INT PRIMARY KEY IDENTITY(1,1),
                customer_id INT NOT NULL,
                order_date DATETIME NOT NULL DEFAULT GETDATE(),
                status NVARCHAR(50) NOT NULL DEFAULT 'PENDING'
            )
            """
            create_proc = f"""
            CREATE PROCEDURE {schema}.CalculateOrderTotal
                @OrderId INT,
                @Total DECIMAL(10,2) OUTPUT,
                @ItemCount INT OUTPUT
            AS
            BEGIN
                SET NOCOUNT ON;
                
                SELECT 
                    @Total = ISNULL(SUM(quantity * unit_price), 0),
                    @ItemCount = COUNT(*)
                FROM {schema}.order_items
                WHERE order_id = @OrderId;
                
                IF @Total = 0
                BEGIN
                    SET @Total = NULL;
                    SET @ItemCount = 0;
                END
            END
            """

            provider.execute_statement(create_table)
            provider.execute_statement(create_proc)

            introspector = IntrospectorFactory.create(provider, log=log)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["procedures"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('procedures', {}).get('differences', [])}"
            )

        finally:
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS {schema}.CalculateOrderTotal")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_identity_with_custom_seed(self, db_container):
        """Test IDENTITY columns with custom seed and increment values."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

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
        log = ConsoleLog("sqlserver_edge_cases", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.custom_identity"

            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            create_table = f"""
            CREATE TABLE {table_name} (
                id INT IDENTITY(100, 5) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                code INT NOT NULL
            )
            """

            provider.execute_statement(create_table)

            introspector = IntrospectorFactory.create(provider, log=log)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('tables', {}).get('differences', [])}"
            )

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.custom_identity")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()
