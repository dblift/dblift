"""
SQL Server Advanced Views Tests.

Tests for advanced view features: WITH CHECK OPTION, SCHEMABINDING, etc.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["sqlserver"],
    indirect=True,
)
class TestSQLServerViewsAdvanced:
    """SQL Server advanced views tests."""

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
        log = ConsoleLog("sqlserver_views_advanced", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_view_with_check_option(self, db_container):
        """Test introspection of a view with WITH CHECK OPTION."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS [{schema}].[active_customers]")
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

            # Create view with WITH CHECK OPTION
            create_view = f"""
            CREATE VIEW [{schema}].[active_customers]
            WITH SCHEMABINDING
            AS
            SELECT id, name, email, status
            FROM [{schema}].[customers]
            WHERE status = 'ACTIVE'
            WITH CHECK OPTION
            """
            provider.execute_statement(create_view)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            views = introspector.get_views(schema)

            # Find our view
            test_view = None
            for view in views:
                if view.name.lower() == "active_customers":
                    test_view = view
                    break

            assert test_view is not None, "View 'active_customers' not found"
            assert test_view.query is not None, "View query is None"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS [{schema}].[active_customers]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[customers]")
            except Exception:
                pass
            provider.close()

    def test_view_with_schemabinding(self, db_container):
        """Test introspection of a view with SCHEMABINDING."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS [{schema}].[product_summary]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[products]")
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE [{schema}].[products] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                category NVARCHAR(50) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create view with SCHEMABINDING
            create_view = f"""
            CREATE VIEW [{schema}].[product_summary]
            WITH SCHEMABINDING
            AS
            SELECT 
                category,
                COUNT(*) AS product_count,
                AVG(price) AS avg_price
            FROM [{schema}].[products]
            GROUP BY category
            """
            provider.execute_statement(create_view)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            views = introspector.get_views(schema)

            # Find our view
            test_view = None
            for view in views:
                if view.name.lower() == "product_summary":
                    test_view = view
                    break

            assert test_view is not None, "View 'product_summary' not found"
            assert test_view.query is not None, "View query is None"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS [{schema}].[product_summary]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[products]")
            except Exception:
                pass
            provider.close()
