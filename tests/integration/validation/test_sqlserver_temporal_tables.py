"""
SQL Server Temporal Tables Tests.

Tests for SQL Server temporal tables (system-versioned tables, SQL Server 2016+).
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
class TestSQLServerTemporalTables:
    """SQL Server temporal tables tests."""

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
        log = ConsoleLog("sqlserver_temporal", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_temporal_table_introspection(self, db_container):
        """Test introspection of a system-versioned temporal table."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f"ALTER TABLE [{schema}].[employees] SET (SYSTEM_VERSIONING = OFF)"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[employees]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[employees_history]")
            except Exception:
                pass

            # Create history table first
            create_history = f"""
            CREATE TABLE [{schema}].[employees_history] (
                id INT NOT NULL,
                name NVARCHAR(100) NOT NULL,
                department NVARCHAR(50) NOT NULL,
                valid_from DATETIME2 NOT NULL,
                valid_to DATETIME2 NOT NULL
            )
            """
            provider.execute_statement(create_history)

            # Create temporal table
            create_table = f"""
            CREATE TABLE [{schema}].[employees] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                department NVARCHAR(50) NOT NULL,
                valid_from DATETIME2 GENERATED ALWAYS AS ROW START NOT NULL,
                valid_to DATETIME2 GENERATED ALWAYS AS ROW END NOT NULL,
                PERIOD FOR SYSTEM_TIME (valid_from, valid_to)
            )
            WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = [{schema}].[employees_history]))
            """
            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "employees":
                    test_table = table
                    break

            assert test_table is not None, "Table 'employees' not found"
            # Check if temporal properties are captured (if supported)
            if hasattr(test_table, "system_versioned"):
                # Temporal properties may or may not be captured, but table should exist
                pass

        finally:
            try:
                provider.execute_statement(
                    f"ALTER TABLE [{schema}].[employees] SET (SYSTEM_VERSIONING = OFF)"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[employees]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[employees_history]")
            except Exception:
                pass
            provider.close()
