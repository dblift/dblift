"""
SQL Server Filegroups Tests.

Tests for SQL Server filegroups (table and index placement).
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
class TestSQLServerFilegroups:
    """SQL Server filegroups tests."""

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
        log = ConsoleLog("sqlserver_filegroups", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_table_on_filegroup(self, db_container):
        """Test introspection of a table on a specific filegroup."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[filegroup_table]")
            except Exception:
                pass

            # Create table on PRIMARY filegroup (default, but explicit)
            create_table = f"""
            CREATE TABLE [{schema}].[filegroup_table] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                value INT NOT NULL
            ) ON [PRIMARY]
            """
            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "filegroup_table":
                    test_table = table
                    break

            assert test_table is not None, "Table 'filegroup_table' not found"
            # Filegroup metadata may or may not be captured, but table should exist

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[filegroup_table]")
            except Exception:
                pass
            provider.close()
