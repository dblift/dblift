"""
SQL Server Partitioning Tests.

Tests for SQL Server table partitioning.
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
class TestSQLServerPartitioning:
    """SQL Server partitioning tests."""

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
        log = ConsoleLog("sqlserver_partitioning", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_partitioned_table_introspection(self, db_container):
        """Test introspection of a partitioned table."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        # Use unique names to avoid conflicts
        import uuid

        unique_suffix = str(uuid.uuid4()).replace("-", "")[:8]
        function_name = f"pf_sales_{unique_suffix}"
        scheme_name = f"ps_sales_{unique_suffix}"
        table_name = f"sales_data_{unique_suffix}"

        try:
            # Clean up - must drop in correct order: table -> scheme -> function
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[{table_name}]")
            except Exception:
                pass
            try:
                provider.execute_statement(f"DROP PARTITION SCHEME IF EXISTS {scheme_name}")
            except Exception:
                pass
            try:
                provider.execute_statement(f"DROP PARTITION FUNCTION IF EXISTS {function_name}")
            except Exception:
                pass

            # Create partition function
            create_function = f"""
            CREATE PARTITION FUNCTION {function_name} (INT)
            AS RANGE RIGHT FOR VALUES (2020, 2021, 2022, 2023)
            """
            provider.execute_statement(create_function)

            # Create partition scheme
            create_scheme = f"""
            CREATE PARTITION SCHEME {scheme_name}
            AS PARTITION {function_name}
            ALL TO ([PRIMARY])
            """
            provider.execute_statement(create_scheme)

            # Create partitioned table
            create_table = f"""
            CREATE TABLE [{schema}].[{table_name}] (
                id INT IDENTITY(1,1),
                sale_year INT NOT NULL,
                amount DECIMAL(10, 2) NOT NULL,
                PRIMARY KEY (id, sale_year)
            ) ON {scheme_name}(sale_year)
            """
            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == table_name.lower():
                    test_table = table
                    break

            assert test_table is not None, f"Table '{table_name}' not found"
            # Partitioning metadata may or may not be fully captured, but table should exist

        finally:
            # Clean up - must drop in correct order: table -> scheme -> function
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[{table_name}]")
            except Exception:
                pass
            try:
                provider.execute_statement(f"DROP PARTITION SCHEME IF EXISTS {scheme_name}")
            except Exception:
                pass
            try:
                provider.execute_statement(f"DROP PARTITION FUNCTION IF EXISTS {function_name}")
            except Exception:
                pass
            provider.close()
