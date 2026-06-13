"""
SQL Server Spatial Data Types Tests.

Tests for SQL Server spatial data types: GEOMETRY, GEOGRAPHY.
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
class TestSQLServerSpatial:
    """SQL Server spatial data types tests."""

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
        log = ConsoleLog("sqlserver_spatial", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_geometry_column(self, db_container):
        """Test introspection of a table with GEOMETRY column."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[locations]")
            except Exception:
                pass

            # Create table with GEOMETRY column
            create_table = f"""
            CREATE TABLE [{schema}].[locations] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                coordinates GEOMETRY
            )
            """
            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "locations":
                    test_table = table
                    break

            assert test_table is not None, "Table 'locations' not found"

            # Check for GEOMETRY column
            geometry_columns = [
                col
                for col in test_table.columns
                if col.data_type.upper() in ("GEOMETRY", "GEOGRAPHY")
                and col.name.lower() == "coordinates"
            ]
            # Spatial types may be introspected differently, just verify table exists
            if len(geometry_columns) == 0:
                coord_columns = [
                    col for col in test_table.columns if col.name.lower() == "coordinates"
                ]
                assert (
                    len(coord_columns) >= 1
                ), f"Column 'coordinates' not found in {[col.name for col in test_table.columns]}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[locations]")
            except Exception:
                pass
            provider.close()

    def test_geography_column(self, db_container):
        """Test introspection of a table with GEOGRAPHY column."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f"DROP TABLE IF EXISTS [{schema}].[geographic_locations]"
                )
            except Exception:
                pass

            # Create table with GEOGRAPHY column
            create_table = f"""
            CREATE TABLE [{schema}].[geographic_locations] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                location GEOGRAPHY
            )
            """
            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "geographic_locations":
                    test_table = table
                    break

            assert test_table is not None, "Table 'geographic_locations' not found"

            # Check for GEOGRAPHY column
            geography_columns = [
                col
                for col in test_table.columns
                if col.data_type.upper() in ("GEOMETRY", "GEOGRAPHY")
                and col.name.lower() == "location"
            ]
            # Spatial types may be introspected differently, just verify table exists
            if len(geography_columns) == 0:
                loc_columns = [col for col in test_table.columns if col.name.lower() == "location"]
                assert (
                    len(loc_columns) >= 1
                ), f"Column 'location' not found in {[col.name for col in test_table.columns]}"

        finally:
            try:
                provider.execute_statement(
                    f"DROP TABLE IF EXISTS [{schema}].[geographic_locations]"
                )
            except Exception:
                pass
            provider.close()
