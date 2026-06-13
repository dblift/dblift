"""
MySQL Indexes Tests.

Tests for MySQL indexes: basic indexes, unique indexes, multi-column indexes.
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
class TestMySQLIndexes:
    """MySQL indexes tests."""

    def test_basic_index_introspection(self, db_container):
        """Test introspection of a basic B-tree index."""
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
        log = ConsoleLog("mysql_indexes", enable_debug=False)
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

            # Create table with index
            create_table = f"""
            CREATE TABLE `{schema}`.`users` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100) NOT NULL,
                INDEX idx_email (email)
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            indexes = introspector.get_indexes(schema, "users")

            # Find our index
            email_index = None
            for idx in indexes:
                if idx.name.lower() == "idx_email":
                    email_index = idx
                    break

            assert email_index is not None, "Index 'idx_email' not found"
            assert "email" in [
                c.lower() for c in email_index.columns
            ], "Index should contain 'email' column"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_unique_index_introspection(self, db_container):
        """Test introspection of a unique index."""
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
        log = ConsoleLog("mysql_unique_index", enable_debug=False)
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

            # Create table with unique index
            create_table = f"""
            CREATE TABLE `{schema}`.`products` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sku VARCHAR(50) NOT NULL,
                name VARCHAR(100) NOT NULL,
                UNIQUE INDEX idx_sku (sku)
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            indexes = introspector.get_indexes(schema, "products")

            # Find our index
            sku_index = None
            for idx in indexes:
                if idx.name.lower() == "idx_sku":
                    sku_index = idx
                    break

            assert sku_index is not None, "Index 'idx_sku' not found"
            assert sku_index.unique is True, "Index should be unique"
            assert "sku" in [
                c.lower() for c in sku_index.columns
            ], "Index should contain 'sku' column"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`products`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_multi_column_index_introspection(self, db_container):
        """Test introspection of a multi-column index."""
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
        log = ConsoleLog("mysql_multi_column_index", enable_debug=False)
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

            # Create table with multi-column index
            create_table = f"""
            CREATE TABLE `{schema}`.`orders` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                customer_id INT NOT NULL,
                order_date DATE NOT NULL,
                status VARCHAR(20) NOT NULL,
                INDEX idx_customer_date (customer_id, order_date)
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            indexes = introspector.get_indexes(schema, "orders")

            # Find our index
            customer_date_index = None
            for idx in indexes:
                if idx.name.lower() == "idx_customer_date":
                    customer_date_index = idx
                    break

            assert customer_date_index is not None, "Index 'idx_customer_date' not found"
            assert len(customer_date_index.columns) >= 2, "Index should have at least 2 columns"
            assert "customer_id" in [
                c.lower() for c in customer_date_index.columns
            ], "Index should contain 'customer_id'"
            assert "order_date" in [
                c.lower() for c in customer_date_index.columns
            ], "Index should contain 'order_date'"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`orders`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
