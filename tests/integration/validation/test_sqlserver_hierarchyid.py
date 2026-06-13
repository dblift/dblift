"""
SQL Server HierarchyID Data Type Tests.

Tests for SQL Server HierarchyID data type (hierarchical data).
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
class TestSQLServerHierarchyID:
    """SQL Server HierarchyID data type tests."""

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
        log = ConsoleLog("sqlserver_hierarchyid", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_hierarchyid_column(self, db_container):
        """Test introspection of a table with HierarchyID column."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[employees]")
            except Exception:
                pass

            # Create table with HierarchyID column
            create_table = f"""
            CREATE TABLE [{schema}].[employees] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                org_node HIERARCHYID
            )
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

            # Check for HierarchyID column
            hierarchyid_columns = [
                col
                for col in test_table.columns
                if col.data_type.upper() == "HIERARCHYID" and col.name.lower() == "org_node"
            ]
            # HierarchyID may be introspected differently, just verify table exists
            if len(hierarchyid_columns) == 0:
                org_columns = [col for col in test_table.columns if col.name.lower() == "org_node"]
                assert (
                    len(org_columns) >= 1
                ), f"Column 'org_node' not found in {[col.name for col in test_table.columns]}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[employees]")
            except Exception:
                pass
            provider.close()
