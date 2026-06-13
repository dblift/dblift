"""
MySQL Comprehensive Tests.

Comprehensive tests combining multiple MySQL features in one schema.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["mysql"],
    indirect=True,
)
class TestMySQLComprehensive:
    """MySQL comprehensive tests."""

    def test_comprehensive_schema_round_trip(self, db_container):
        """Test round-trip for a comprehensive schema with multiple features."""
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
        log = ConsoleLog("mysql_comprehensive", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`order_items`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`orders`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`customers`")
                provider.execute_statement(f"DROP VIEW IF EXISTS `{schema}`.`customer_orders`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create comprehensive schema
            # 1. Customers table with CHECK constraint
            create_customers = f"""
            CREATE TABLE `{schema}`.`customers` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                status VARCHAR(20) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_status CHECK (status IN ('ACTIVE', 'INACTIVE'))
            )
            """
            provider.execute_statement(create_customers)

            # 2. Orders table with foreign key and JSON
            create_orders = f"""
            CREATE TABLE `{schema}`.`orders` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                customer_id INT NOT NULL,
                order_date DATE NOT NULL,
                total DECIMAL(10, 2) NOT NULL,
                metadata JSON,
                CONSTRAINT fk_order_customer FOREIGN KEY (customer_id) REFERENCES `{schema}`.`customers`(id)
            )
            """
            provider.execute_statement(create_orders)

            # 3. Order items table with multiple foreign keys
            create_order_items = f"""
            CREATE TABLE `{schema}`.`order_items` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                order_id INT NOT NULL,
                product_name VARCHAR(200) NOT NULL,
                quantity INT NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                CONSTRAINT fk_item_order FOREIGN KEY (order_id) REFERENCES `{schema}`.`orders`(id) ON DELETE CASCADE
            )
            """
            provider.execute_statement(create_order_items)

            # 4. View combining tables
            create_view = f"""
            CREATE VIEW `{schema}`.`customer_orders` AS
            SELECT 
                c.id AS customer_id,
                c.name AS customer_name,
                o.id AS order_id,
                o.order_date,
                o.total
            FROM `{schema}`.`customers` c
            INNER JOIN `{schema}`.`orders` o ON c.id = o.customer_id
            """
            provider.execute_statement(create_view)

            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Ensure test schema exists
            test_schema = f"{schema}_test"
            provider.schema_operations.create_schema_if_not_exists(provider.connection, test_schema)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=test_schema,
                introspector=introspector,
                test_object_types=["tables", "views"],
            )
            results = tester.run_round_trip_test()

            # Check results
            assert results["success"] is True, f"Round-trip failed: {results.get('errors', [])}"
            assert (
                results["tables"]["reintrospected_count"] >= 3
            ), f"Expected at least 3 tables, got {results['tables']['reintrospected_count']}"
            assert (
                results["views"]["reintrospected_count"] >= 1
            ), f"Expected at least 1 view, got {results['views']['reintrospected_count']}"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS `{schema}`.`customer_orders`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`order_items`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`orders`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`customers`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
