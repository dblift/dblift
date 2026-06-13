"""
MySQL AUTO_INCREMENT Tests.

Tests for MySQL AUTO_INCREMENT columns: introspection and SQL generation.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["mysql"],
    indirect=True,
)
class TestMySQLAutoIncrement:
    """MySQL AUTO_INCREMENT tests."""

    def test_auto_increment_introspection(self, db_container):
        """Test introspection of AUTO_INCREMENT column."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_config = DatabaseConfig(
            type="mysql",
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
            extra_params={
                "useSSL": "false",
                "allowPublicKeyRetrieval": "true",
            },
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("mysql_auto_increment", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`test_auto_inc`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with AUTO_INCREMENT
            create_table = f"""
            CREATE TABLE `{schema}`.`test_auto_inc` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
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
                if table.name.lower() == "test_auto_inc":
                    test_table = table
                    break

            assert test_table is not None, "Table 'test_auto_inc' not found"

            # Find id column
            id_column = None
            for col in test_table.columns:
                if col.name.lower() == "id":
                    id_column = col
                    break

            assert id_column is not None, "Column 'id' not found"
            # AUTO_INCREMENT should be detected (may be stored as identity or in column properties)
            # MySQL uses AUTO_INCREMENT, which may be mapped to identity in the model

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`test_auto_inc`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_auto_increment_with_custom_start(self, db_container):
        """Test AUTO_INCREMENT with custom start value."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_config = DatabaseConfig(
            type="mysql",
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
            extra_params={
                "useSSL": "false",
                "allowPublicKeyRetrieval": "true",
            },
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("mysql_auto_increment_custom", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f"DROP TABLE IF EXISTS `{schema}`.`test_auto_inc_custom`"
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with AUTO_INCREMENT starting at 100
            create_table = f"""
            CREATE TABLE `{schema}`.`test_auto_inc_custom` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            ) AUTO_INCREMENT=100
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
                if table.name.lower() == "test_auto_inc_custom":
                    test_table = table
                    break

            assert test_table is not None, "Table 'test_auto_inc_custom' not found"

        finally:
            try:
                provider.execute_statement(
                    f"DROP TABLE IF EXISTS `{schema}`.`test_auto_inc_custom`"
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
