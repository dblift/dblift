"""
SQL Server Computed Columns Tests.

Comprehensive tests for computed columns (PERSISTED and NON-PERSISTED).
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
class TestSQLServerComputedColumns:
    """SQL Server computed column tests."""

    def test_persisted_computed_column_introspection(self, db_container):
        """Test PERSISTED computed column introspection."""
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
        log = ConsoleLog("sqlserver_computed_test", enable_debug=False)
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
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with PERSISTED computed column
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                price DECIMAL(10, 2) NOT NULL,
                quantity INT NOT NULL,
                total AS (price * quantity) PERSISTED
            )
            """

            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            assert len(tables) >= 1
            products_table = next((t for t in tables if t.name == "products"), None)
            assert products_table is not None

            # Find computed column
            computed_col = next((c for c in products_table.columns if c.name == "total"), None)
            assert computed_col is not None
            assert hasattr(computed_col, "is_computed")
            assert computed_col.is_computed is True
            assert hasattr(computed_col, "computed_expression")
            assert computed_col.computed_expression is not None
            # SQL Server returns expressions with brackets, normalize for comparison
            expr_upper = (
                computed_col.computed_expression.upper()
                .replace("[", "")
                .replace("]", "")
                .replace(" ", "")
            )
            assert "PRICE" in expr_upper and "QUANTITY" in expr_upper and "*" in expr_upper
            assert hasattr(computed_col, "computed_stored")
            assert computed_col.computed_stored is True

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.invoices")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.line_items")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.calculations")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_non_persisted_computed_column_introspection(self, db_container):
        """Test NON-PERSISTED computed column introspection."""
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
        log = ConsoleLog("sqlserver_computed_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema
            table_name = f"{schema}.orders"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with NON-PERSISTED computed column
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                subtotal DECIMAL(10, 2) NOT NULL,
                tax_rate DECIMAL(5, 4) NOT NULL,
                tax AS (subtotal * tax_rate)
            )
            """

            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            assert len(tables) >= 1
            orders_table = next((t for t in tables if t.name == "orders"), None)
            assert orders_table is not None

            # Find computed column
            computed_col = next((c for c in orders_table.columns if c.name == "tax"), None)
            assert computed_col is not None
            assert hasattr(computed_col, "is_computed")
            assert computed_col.is_computed is True
            assert hasattr(computed_col, "computed_stored")
            # NON-PERSISTED means computed_stored should be False
            assert computed_col.computed_stored is False

        finally:
            try:
                provider.execute_statement("DROP TABLE IF EXISTS orders")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_computed_columns_sql_generation(self, db_container):
        """Test that computed columns are correctly generated in SQL."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from core.sql_generator.generator_factory import SqlGeneratorFactory
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
        log = ConsoleLog("sqlserver_computed_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema
            table_name = f"{schema}.invoices"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with both PERSISTED and NON-PERSISTED computed columns
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                amount DECIMAL(10, 2) NOT NULL,
                discount DECIMAL(5, 2) NOT NULL,
                discounted_amount AS (amount * (1 - discount / 100)) PERSISTED,
                final_total AS (amount * (1 - discount / 100) * 1.1)
            )
            """

            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            invoices_table = next((t for t in tables if t.name == "invoices"), None)
            assert invoices_table is not None

            # Generate SQL
            generator = SqlGeneratorFactory.create("sqlserver")
            sql = generator.generate_create_statement(invoices_table)
            sql_upper = sql.upper()

            # Verify PERSISTED computed column
            assert "discounted_amount" in sql.lower()
            assert "PERSISTED" in sql_upper
            # SQL Server adds extra parentheses and brackets, normalize for comparison
            normalized_sql = sql_upper.replace("[", "").replace("]", "").replace(" ", "")
            assert (
                "AMOUNT" in normalized_sql
                and "DISCOUNT" in normalized_sql
                and "100" in normalized_sql
            )

            # Verify NON-PERSISTED computed column (should not have PERSISTED)
            assert "final_total" in sql
            # NON-PERSISTED columns should not have PERSISTED keyword
            final_total_index = sql.upper().find("FINAL_TOTAL")
            persisted_after_final = (
                "PERSISTED" in sql.upper()[final_total_index : final_total_index + 200]
            )
            # The PERSISTED keyword should only appear for discounted_amount, not final_total
            assert not persisted_after_final or sql.upper().count("PERSISTED") == 1

        finally:
            try:
                provider.execute_statement("DROP TABLE IF EXISTS invoices")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_computed_columns_round_trip(self, db_container):
        """Test that computed columns are preserved in round-trip."""
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
        log = ConsoleLog("sqlserver_computed_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema
            table_name = f"{schema}.line_items"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with computed columns
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                unit_price DECIMAL(10, 2) NOT NULL,
                quantity INT NOT NULL,
                line_total AS (unit_price * quantity) PERSISTED,
                discount_percent DECIMAL(5, 2) NOT NULL,
                final_price AS (unit_price * quantity * (1 - discount_percent / 100))
            )
            """

            provider.execute_statement(create_table)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)

            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=db_config.schema,
                test_schema=db_config.schema + "_test",
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
                provider.execute_statement("DROP TABLE IF EXISTS line_items")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_computed_columns_complex_expressions(self, db_container):
        """Test computed columns with complex expressions."""
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
        log = ConsoleLog("sqlserver_computed_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema
            table_name = f"{schema}.calculations"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with complex computed column expressions
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                base_value DECIMAL(10, 2) NOT NULL,
                multiplier DECIMAL(5, 2) NOT NULL,
                offset_value DECIMAL(10, 2) NOT NULL,
                result AS ((base_value * multiplier) + offset_value) PERSISTED,
                formatted_result AS (CAST((base_value * multiplier) + offset_value AS VARCHAR(50)))
            )
            """

            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            calculations_table = next((t for t in tables if t.name == "calculations"), None)
            assert calculations_table is not None

            # Verify both computed columns exist
            computed_cols = [
                c for c in calculations_table.columns if hasattr(c, "is_computed") and c.is_computed
            ]
            assert len(computed_cols) == 2

            result_col = next((c for c in computed_cols if c.name == "result"), None)
            assert result_col is not None
            assert result_col.computed_stored is True

            formatted_col = next((c for c in computed_cols if c.name == "formatted_result"), None)
            assert formatted_col is not None
            assert formatted_col.computed_stored is False

        finally:
            try:
                provider.execute_statement("DROP TABLE IF EXISTS calculations")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()
