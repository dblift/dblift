"""
SQL Server SQL Generation Quality Tests.

Tests for SQL generation quality: views, procedures, functions, triggers.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.sql_generator.generator_factory import SqlGeneratorFactory


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["sqlserver"],
    indirect=True,
)
class TestSQLServerSqlGenerationQuality:
    """SQL Server SQL generation quality tests."""

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
        log = ConsoleLog("sqlserver_sql_gen", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_view_sql_generation_quality(self, db_container):
        """Test SQL generation quality for views."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS [{schema}].[customer_summary]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[customers]")
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE [{schema}].[customers] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                email NVARCHAR(100) NOT NULL,
                status NVARCHAR(20) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create view
            create_view = f"""
            CREATE VIEW [{schema}].[customer_summary] AS
            SELECT 
                id,
                name,
                email,
                status
            FROM [{schema}].[customers]
            WHERE status = 'ACTIVE'
            """
            provider.execute_statement(create_view)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            views = introspector.get_views(schema)

            # Find our view
            test_view = None
            for view in views:
                if view.name.lower() == "customer_summary":
                    test_view = view
                    break

            assert test_view is not None, "View 'customer_summary' not found"

            # Generate SQL
            generator = SqlGeneratorFactory.create("sqlserver")
            sql = generator.generate_create_statement(test_view)

            # Check that SQL is generated and contains key elements
            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "VIEW" in sql.upper(), f"VIEW not found in generated SQL: {sql[:200]}"
            assert "SELECT" in sql.upper() or test_view.query is not None, "View query not found"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS [{schema}].[customer_summary]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[customers]")
            except Exception:
                pass
            provider.close()

    def test_procedure_sql_generation_quality(self, db_container):
        """Test SQL generation quality for stored procedures."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f"DROP PROCEDURE IF EXISTS [{schema}].[get_customer_by_id]"
                )
            except Exception:
                pass

            # Create procedure
            create_procedure = f"""
            CREATE PROCEDURE [{schema}].[get_customer_by_id]
                @customer_id INT
            AS
            BEGIN
                SELECT id, name, email FROM [{schema}].[customers] WHERE id = @customer_id;
            END
            """
            provider.execute_statement(create_procedure)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            procedures = introspector.get_procedures(schema)

            # Find our procedure
            test_procedure = None
            for proc in procedures:
                if proc.name.lower() == "get_customer_by_id":
                    test_procedure = proc
                    break

            assert test_procedure is not None, "Procedure 'get_customer_by_id' not found"

            # Generate SQL
            generator = SqlGeneratorFactory.create("sqlserver")
            sql = generator.generate_create_statement(test_procedure)

            # Check that SQL is generated
            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "PROCEDURE" in sql.upper(), f"PROCEDURE not found in generated SQL: {sql[:200]}"

        finally:
            try:
                provider.execute_statement(
                    f"DROP PROCEDURE IF EXISTS [{schema}].[get_customer_by_id]"
                )
            except Exception:
                pass
            provider.close()

    def test_function_sql_generation_quality(self, db_container):
        """Test SQL generation quality for functions."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP FUNCTION IF EXISTS [{schema}].[calculate_total]")
            except Exception:
                pass

            # Create function
            create_function = f"""
            CREATE FUNCTION [{schema}].[calculate_total] (@price DECIMAL(10,2), @quantity INT)
            RETURNS DECIMAL(10,2)
            AS
            BEGIN
                RETURN @price * @quantity;
            END
            """
            provider.execute_statement(create_function)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            functions = introspector.get_functions(schema)

            # Find our function
            test_function = None
            for func in functions:
                if func.name.lower() == "calculate_total":
                    test_function = func
                    break

            assert test_function is not None, "Function 'calculate_total' not found"

            # Generate SQL
            generator = SqlGeneratorFactory.create("sqlserver")
            sql = generator.generate_create_statement(test_function)

            # Check that SQL is generated
            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "FUNCTION" in sql.upper(), f"FUNCTION not found in generated SQL: {sql[:200]}"

        finally:
            try:
                provider.execute_statement(f"DROP FUNCTION IF EXISTS [{schema}].[calculate_total]")
            except Exception:
                pass
            provider.close()
