"""
SQL Server Graph Tables Tests.

Tests for SQL Server graph database features (node and edge tables, SQL Server 2017+).
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
class TestSQLServerGraphTables:
    """SQL Server graph tables tests."""

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
        log = ConsoleLog("sqlserver_graph", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_node_table_introspection(self, db_container):
        """Test introspection of a node table (SQL Server 2017+)."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[Person]")
            except Exception:
                pass

            # Create node table (SQL Server 2017+)
            create_table = f"""
            CREATE TABLE [{schema}].[Person] (
                ID INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL
            ) AS NODE
            """
            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "person":
                    test_table = table
                    break

            assert test_table is not None, "Table 'Person' not found"
            # Graph table properties may or may not be captured, but table should exist

        except Exception as e:
            # Graph tables require SQL Server 2017+, may not be available
            if "AS NODE" in str(e) or "syntax" in str(e).lower():
                pytest.skip(f"Graph tables may not be supported in this SQL Server version: {e}")
            raise
        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[Person]")
            except Exception:
                pass
            provider.close()

    def test_edge_table_introspection(self, db_container):
        """Test introspection of an edge table (SQL Server 2017+)."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[knows]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[Person]")
            except Exception:
                pass

            # Create node table first
            create_node = f"""
            CREATE TABLE [{schema}].[Person] (
                ID INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL
            ) AS NODE
            """
            provider.execute_statement(create_node)

            # Create edge table
            create_edge = f"""
            CREATE TABLE [{schema}].[knows] (
                since DATE
            ) AS EDGE
            """
            provider.execute_statement(create_edge)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our edge table
            test_table = None
            for table in tables:
                if table.name.lower() == "knows":
                    test_table = table
                    break

            assert test_table is not None, "Table 'knows' not found"

        except Exception as e:
            # Graph tables require SQL Server 2017+, may not be available
            if "AS EDGE" in str(e) or "AS NODE" in str(e) or "syntax" in str(e).lower():
                pytest.skip(f"Graph tables may not be supported in this SQL Server version: {e}")
            raise
        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[knows]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[Person]")
            except Exception:
                pass
            provider.close()
