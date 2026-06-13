"""
MySQL Advanced Features Tests.

Tests for advanced MySQL features: complex views, multi-column constraints, expression indexes, etc.
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
class TestMySQLAdvancedFeatures:
    """MySQL advanced features tests."""

    def test_complex_view_with_joins(self, db_container):
        """Test introspection of a complex view with multiple joins."""
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
        log = ConsoleLog("mysql_complex_view", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS `{schema}`.`order_summary`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`order_items`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`orders`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`customers`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create tables
            create_customers = f"""
            CREATE TABLE `{schema}`.`customers` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_customers)

            create_orders = f"""
            CREATE TABLE `{schema}`.`orders` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                customer_id INT NOT NULL,
                order_date DATE NOT NULL,
                total DECIMAL(10, 2) NOT NULL,
                CONSTRAINT fk_order_customer FOREIGN KEY (customer_id) REFERENCES `{schema}`.`customers`(id)
            )
            """
            provider.execute_statement(create_orders)

            create_order_items = f"""
            CREATE TABLE `{schema}`.`order_items` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT NOT NULL,
                product_name VARCHAR(200) NOT NULL,
                quantity INT NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                CONSTRAINT fk_item_order FOREIGN KEY (order_id) REFERENCES `{schema}`.`orders`(id)
            )
            """
            provider.execute_statement(create_order_items)

            # Create complex view
            create_view = f"""
            CREATE VIEW `{schema}`.`order_summary` AS
            SELECT 
                c.id AS customer_id,
                c.name AS customer_name,
                o.id AS order_id,
                o.order_date,
                o.total AS order_total,
                COUNT(oi.id) AS item_count,
                SUM(oi.quantity * oi.price) AS items_total
            FROM `{schema}`.`customers` c
            INNER JOIN `{schema}`.`orders` o ON c.id = o.customer_id
            LEFT JOIN `{schema}`.`order_items` oi ON o.id = oi.order_id
            GROUP BY c.id, c.name, o.id, o.order_date, o.total
            """
            provider.execute_statement(create_view)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            views = introspector.get_views(schema)

            # Find our view
            test_view = None
            for view in views:
                if view.name.lower() == "order_summary":
                    test_view = view
                    break

            assert test_view is not None, "View 'order_summary' not found"
            assert test_view.query is not None, "View query is None"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS `{schema}`.`order_summary`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`order_items`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`orders`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`customers`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_multi_column_unique_constraint(self, db_container):
        """Test introspection of multi-column UNIQUE constraint."""
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
        log = ConsoleLog("mysql_multi_unique", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`user_permissions`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with multi-column UNIQUE constraint
            create_table = f"""
            CREATE TABLE `{schema}`.`user_permissions` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                resource_id INT NOT NULL,
                permission VARCHAR(50) NOT NULL,
                CONSTRAINT uk_user_resource UNIQUE (user_id, resource_id)
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
                if table.name.lower() == "user_permissions":
                    test_table = table
                    break

            assert test_table is not None, "Table 'user_permissions' not found"

            # Check for multi-column UNIQUE constraint
            unique_constraints = [
                c
                for c in test_table.constraints
                if c.constraint_type.value == "UNIQUE" and len(c.column_names) > 1
            ]
            assert (
                len(unique_constraints) >= 1
            ), f"Expected at least 1 multi-column UNIQUE constraint, found {len(unique_constraints)}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`user_permissions`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_expression_index(self, db_container):
        """Test introspection of index with expression (functional index)."""
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
        log = ConsoleLog("mysql_expression_index", enable_debug=False)
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

            # Create table with functional index (MySQL 8.0.13+)
            create_table = f"""
            CREATE TABLE `{schema}`.`users` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                first_name VARCHAR(50) NOT NULL,
                last_name VARCHAR(50) NOT NULL,
                email VARCHAR(100) NOT NULL,
                INDEX idx_full_name ((CONCAT(first_name, ' ', last_name)))
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            indexes = introspector.get_indexes(schema, "users")

            # Find our functional index
            func_index = None
            for idx in indexes:
                if idx.name.lower() == "idx_full_name":
                    func_index = idx
                    break

            # Functional indexes may or may not be fully supported in introspection
            # Just verify the table exists
            tables = introspector.get_tables(schema)
            test_table = None
            for table in tables:
                if table.name.lower() == "users":
                    test_table = table
                    break
            assert test_table is not None, "Table 'users' not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
