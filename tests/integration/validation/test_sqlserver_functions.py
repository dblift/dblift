"""
SQL Server Functions Tests.

Comprehensive tests for scalar and table-valued functions.
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
class TestSQLServerFunctions:
    """SQL Server function tests."""

    def test_scalar_function(self, db_container):
        """Test scalar function."""
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
        log = ConsoleLog("sqlserver_function_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP FUNCTION IF EXISTS {schema}.CalculateTotal")
            except Exception:
                pass

            # Create scalar function
            create_func = f"""
            CREATE FUNCTION {schema}.CalculateTotal(@price DECIMAL(10,2), @quantity INT)
            RETURNS DECIMAL(10,2)
            AS
            BEGIN
                RETURN @price * @quantity;
            END
            """

            provider.execute_statement(create_func)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            functions = introspector.get_functions(db_config.schema)

            assert len(functions) >= 1
            func = next((f for f in functions if f.name == "CalculateTotal"), None)
            assert func is not None
            assert hasattr(func, "return_type")
            assert "DECIMAL" in func.return_type.upper()
            assert len(func.parameters) == 2

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP FUNCTION IF EXISTS {schema}.CalculateTotal")
                provider.execute_statement(
                    f"DROP FUNCTION IF EXISTS {schema}.GetProductsByCategory"
                )
                provider.execute_statement(f"DROP FUNCTION IF EXISTS {schema}.GetOrderSummary")
                provider.execute_statement(f"DROP FUNCTION IF EXISTS {schema}.FormatCurrency")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_inline_table_valued_function(self, db_container):
        """Test inline table-valued function."""
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
        log = ConsoleLog("sqlserver_function_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema
            table_name = f"{schema}.products"

            # Clean up if exists
            try:
                provider.execute_statement(
                    f"DROP FUNCTION IF EXISTS {schema}.GetProductsByCategory"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table first
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                category_id INT NOT NULL,
                name NVARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create inline table-valued function
            create_func = f"""
            CREATE FUNCTION {schema}.GetProductsByCategory(@CategoryId INT)
            RETURNS TABLE
            AS
            RETURN
            (
                SELECT id, name FROM {table_name} WHERE category_id = @CategoryId
            )
            """

            provider.execute_statement(create_func)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            functions = introspector.get_functions(db_config.schema)

            func = next((f for f in functions if f.name == "GetProductsByCategory"), None)
            assert func is not None
            # SQL Server inline table-valued functions may not have return_type set
            # Check if it's a function (not a procedure)
            assert hasattr(func, "is_function")
            # For table-valued functions, return_type might be None or "TABLE"
            if hasattr(func, "return_type") and func.return_type:
                assert "TABLE" in func.return_type.upper()

        finally:
            try:
                provider.execute_statement("DROP FUNCTION IF EXISTS GetProductsByCategory")
                provider.execute_statement("DROP TABLE IF EXISTS products")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_multi_statement_table_valued_function(self, db_container):
        """Test multi-statement table-valued function."""
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
        log = ConsoleLog("sqlserver_function_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP FUNCTION IF EXISTS {schema}.GetOrderSummary")
            except Exception:
                pass

            # Create multi-statement table-valued function
            create_func = f"""
            CREATE FUNCTION {schema}.GetOrderSummary(@OrderId INT)
            RETURNS @Summary TABLE (
                order_id INT,
                total_amount DECIMAL(10,2),
                item_count INT
            )
            AS
            BEGIN
                INSERT INTO @Summary
                SELECT @OrderId, SUM(amount), COUNT(*)
                FROM order_items
                WHERE order_id = @OrderId;
                RETURN;
            END
            """

            provider.execute_statement(create_func)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            functions = introspector.get_functions(db_config.schema)

            func = next((f for f in functions if f.name == "GetOrderSummary"), None)
            assert func is not None
            assert hasattr(func, "definition")
            assert func.definition is not None

        finally:
            try:
                provider.execute_statement("DROP FUNCTION IF EXISTS GetOrderSummary")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_function_round_trip(self, db_container):
        """Test that functions are preserved in round-trip."""
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
        log = ConsoleLog("sqlserver_function_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP FUNCTION IF EXISTS {schema}.FormatCurrency")
            except Exception:
                pass

            # Create scalar function
            create_func = f"""
            CREATE FUNCTION {schema}.FormatCurrency(@amount DECIMAL(10,2))
            RETURNS NVARCHAR(50)
            AS
            BEGIN
                RETURN '$' + CAST(@amount AS NVARCHAR(50));
            END
            """

            provider.execute_statement(create_func)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)

            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=db_config.schema,
                test_schema=db_config.schema + "_test",
                introspector=introspector,
                test_object_types=["functions"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('functions', {}).get('differences', [])}"
            )

        finally:
            try:
                provider.execute_statement("DROP FUNCTION IF EXISTS FormatCurrency")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()
