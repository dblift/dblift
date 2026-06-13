"""
MySQL JSON Data Type Tests.

Tests for MySQL JSON data type (MySQL 5.7+): introspection and SQL generation.
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
class TestMySQLJSON:
    """MySQL JSON data type tests."""

    def test_json_column_introspection(self, db_container):
        """Test introspection of a table with JSON columns."""
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
        log = ConsoleLog("mysql_json", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`products`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with JSON column
            create_table = f"""
            CREATE TABLE `{schema}`.`products` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                metadata JSON,
                attributes JSON
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
                if table.name.lower() == "products":
                    test_table = table
                    break

            assert test_table is not None, "Table 'products' not found"

            # Find JSON columns
            json_columns = [col for col in test_table.columns if col.data_type.upper() == "JSON"]
            assert (
                len(json_columns) >= 2
            ), f"Expected at least 2 JSON columns, found {len(json_columns)}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`products`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_json_column_sql_generation(self, db_container):
        """Test SQL generation for JSON columns."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from core.sql_generator.generator_factory import SqlGeneratorFactory
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
        log = ConsoleLog("mysql_json_sql", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with JSON column
            create_table = f"""
            CREATE TABLE `{schema}`.`users` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                profile JSON
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
                if table.name.lower() == "users":
                    test_table = table
                    break

            assert test_table is not None, "Table 'users' not found"

            # Generate SQL
            generator = SqlGeneratorFactory.create("mysql")
            sql = generator.generate_create_statement(test_table)

            # Check that JSON is in the generated SQL
            assert "JSON" in sql.upper(), f"JSON not found in generated SQL: {sql}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
