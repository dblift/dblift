"""
SQL Server XML and JSON Advanced Tests.

Tests for advanced XML and JSON features in SQL Server.
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
class TestSQLServerXmlJson:
    """SQL Server XML and JSON advanced tests."""

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
        log = ConsoleLog("sqlserver_xml_json", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_xml_column_introspection(self, db_container):
        """Test introspection of a table with XML column."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[products]")
            except Exception:
                pass

            # Create table with XML column
            create_table = f"""
            CREATE TABLE [{schema}].[products] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                metadata XML
            )
            """
            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "products":
                    test_table = table
                    break

            assert test_table is not None, "Table 'products' not found"

            # Check for XML column
            xml_columns = [col for col in test_table.columns if col.data_type.upper() == "XML"]
            assert (
                len(xml_columns) >= 1
            ), f"Expected at least 1 XML column, found {len(xml_columns)}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[products]")
            except Exception:
                pass
            provider.close()

    def test_json_column_advanced(self, db_container):
        """Test introspection of a table with JSON column (SQL Server 2016+)."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[users]")
            except Exception:
                pass

            # Create table with JSON column (stored as NVARCHAR(MAX) with CHECK constraint)
            # SQL Server doesn't have native JSON type, but supports JSON via NVARCHAR(MAX)
            create_table = f"""
            CREATE TABLE [{schema}].[users] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                username NVARCHAR(50) NOT NULL,
                profile_data NVARCHAR(MAX),
                CONSTRAINT chk_json CHECK (ISJSON(profile_data) = 1 OR profile_data IS NULL)
            )
            """
            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "users":
                    test_table = table
                    break

            assert test_table is not None, "Table 'users' not found"
            # Check for profile_data column
            profile_columns = [
                col for col in test_table.columns if col.name.lower() == "profile_data"
            ]
            assert len(profile_columns) >= 1, f"Column 'profile_data' not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[users]")
            except Exception:
                pass
            provider.close()
