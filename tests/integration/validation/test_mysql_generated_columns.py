"""
MySQL Generated Columns Tests.

Tests for MySQL generated columns (VIRTUAL and STORED): introspection and SQL generation.
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
class TestMySQLGeneratedColumns:
    """MySQL generated columns tests."""

    def test_virtual_generated_column_introspection(self, db_container):
        """Test introspection of VIRTUAL generated column (MySQL 5.7+)."""
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
        log = ConsoleLog("mysql_generated_columns", enable_debug=False)
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

            # Create table with VIRTUAL generated column
            create_table = f"""
            CREATE TABLE `{schema}`.`products` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                price DECIMAL(10, 2) NOT NULL,
                tax_rate DECIMAL(5, 2) NOT NULL DEFAULT 0.20,
                total_price DECIMAL(10, 2) AS (price * (1 + tax_rate)) VIRTUAL
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

            # Find total_price column
            total_price_col = None
            for col in test_table.columns:
                if col.name.lower() == "total_price":
                    total_price_col = col
                    break

            assert total_price_col is not None, "Column 'total_price' not found"
            # Generated column should be detected (may be stored as computed or generated)
            # MySQL uses GENERATED ALWAYS AS ... VIRTUAL/STORED

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`products`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_stored_generated_column_introspection(self, db_container):
        """Test introspection of STORED generated column (MySQL 5.7+)."""
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
        log = ConsoleLog("mysql_stored_generated", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`orders`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with STORED generated column
            create_table = f"""
            CREATE TABLE `{schema}`.`orders` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                quantity INT NOT NULL,
                unit_price DECIMAL(10, 2) NOT NULL,
                total DECIMAL(10, 2) AS (quantity * unit_price) STORED
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
                if table.name.lower() == "orders":
                    test_table = table
                    break

            assert test_table is not None, "Table 'orders' not found"

            # Find total column
            total_col = None
            for col in test_table.columns:
                if col.name.lower() == "total":
                    total_col = col
                    break

            assert total_col is not None, "Column 'total' not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`orders`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
