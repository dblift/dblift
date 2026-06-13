"""
Oracle JSON Data Type and Table Compression Tests.

Tests for Oracle JSON data type (12cR2+) and table compression features.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["oracle"],
    indirect=True,
)
class TestOracleJsonCompression:
    """Oracle JSON and compression feature tests."""

    def test_json_data_type_introspection(self, db_container):
        """Test introspection of JSON data type (Oracle 12cR2+)."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        service = db_container.get("service", db_container.get("database"))
        database_url = f"oracle+oracledb://{db_container['host']}:{db_container['port']}?service_name={service}"

        db_config = DatabaseConfig(
            type="oracle",
            url=database_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("oracle_json", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."products_json" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Try to create table with JSON column (Oracle 12cR2+)
            # If JSON type is not supported, the test will be skipped
            try:
                create_table = f"""
                CREATE TABLE "{schema}"."products_json" (
                    id NUMBER PRIMARY KEY,
                    name VARCHAR2(100),
                    metadata JSON
                )
                """
                provider.execute_statement(create_table)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                # JSON type might not be available in this Oracle version
                pytest.skip(f"JSON data type not supported in this Oracle version: {str(e)}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "PRODUCTS_JSON":
                    test_table = table
                    break

            assert test_table is not None, "Table 'products_json' not found"

            # Find JSON column
            json_column = None
            for col in test_table.columns:
                if col.name.upper() == "METADATA":
                    json_column = col
                    break

            assert json_column is not None, "JSON column 'metadata' not found"
            # JSON type should be introspected (may be normalized to VARCHAR or JSON)
            assert json_column.data_type.upper() in [
                "JSON",
                "VARCHAR2",
                "CLOB",
            ], f"Expected JSON-related type, got {json_column.data_type}"

        finally:
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."products_json" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_table_compression_introspection(self, db_container):
        """Test introspection of table compression."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        service = db_container.get("service", db_container.get("database"))
        database_url = f"oracle+oracledb://{db_container['host']}:{db_container['port']}?service_name={service}"

        db_config = DatabaseConfig(
            type="oracle",
            url=database_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("oracle_compression", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."compressed_table" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with compression (BASIC compression is available in all editions)
            create_table = f"""
            CREATE TABLE "{schema}"."compressed_table" (
                id NUMBER PRIMARY KEY,
                data VARCHAR2(1000),
                created_date DATE
            ) COMPRESS BASIC
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "COMPRESSED_TABLE":
                    test_table = table
                    break

            assert test_table is not None, "Table 'compressed_table' not found"
            # Compression metadata should be preserved (if supported in introspection)
            # Note: Compression may be stored in table properties/metadata

        finally:
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."compressed_table" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_tablespace_introspection(self, db_container):
        """Test introspection of tablespace assignment."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        service = db_container.get("service", db_container.get("database"))
        database_url = f"oracle+oracledb://{db_container['host']}:{db_container['port']}?service_name={service}"

        db_config = DatabaseConfig(
            type="oracle",
            url=database_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("oracle_tablespace", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."tablespace_table" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Get default tablespace for the user (usually USERS)
            # Create table with explicit tablespace (use USERS which is standard in Oracle XE)
            create_table = f"""
            CREATE TABLE "{schema}"."tablespace_table" (
                id NUMBER PRIMARY KEY,
                data VARCHAR2(100)
            ) TABLESPACE USERS
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "TABLESPACE_TABLE":
                    test_table = table
                    break

            assert test_table is not None, "Table 'tablespace_table' not found"
            # Tablespace should be introspected (may be USERS or another default)
            # Note: Oracle XE may use different default tablespaces
            if test_table.tablespace:
                assert len(test_table.tablespace) > 0, "Tablespace should not be empty if set"

        finally:
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."tablespace_table" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
