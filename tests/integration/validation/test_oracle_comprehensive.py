"""
Oracle Comprehensive Tests.

Comprehensive round-trip tests combining multiple Oracle features.
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
class TestOracleComprehensive:
    """Oracle comprehensive tests."""

    def test_all_features_combined(self, db_container):
        """Test round-trip with all Oracle features combined."""
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
        log = ConsoleLog("oracle_comprehensive", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP SEQUENCE "{schema}"."order_seq"')
                provider.execute_statement(f'DROP VIEW "{schema}"."active_orders"')
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."order_items" CASCADE CONSTRAINTS'
                )
                provider.execute_statement(f'DROP TABLE "{schema}"."orders" CASCADE CONSTRAINTS')
                provider.execute_statement(f'DROP TABLE "{schema}"."customers" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create comprehensive schema
            create_customers = f"""
            CREATE TABLE "{schema}"."customers" (
                id NUMBER GENERATED AS IDENTITY PRIMARY KEY,
                name VARCHAR2(100) NOT NULL,
                email VARCHAR2(100),
                status VARCHAR2(20) DEFAULT 'ACTIVE',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_customers)

            create_orders = f"""
            CREATE TABLE "{schema}"."orders" (
                id NUMBER PRIMARY KEY,
                customer_id NUMBER NOT NULL,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total NUMBER(10, 2),
                subtotal NUMBER(10, 2) NOT NULL,
                tax NUMBER(10, 2) DEFAULT 0,
                final_total NUMBER GENERATED ALWAYS AS (subtotal + tax) VIRTUAL,
                CONSTRAINT fk_order_customer FOREIGN KEY (customer_id) REFERENCES "{schema}"."customers"(id),
                CONSTRAINT chk_total_positive CHECK (total > 0)
            )
            """
            provider.execute_statement(create_orders)

            create_order_items = f"""
            CREATE TABLE "{schema}"."order_items" (
                id NUMBER PRIMARY KEY,
                order_id NUMBER NOT NULL,
                product_name VARCHAR2(100) NOT NULL,
                quantity NUMBER NOT NULL,
                price NUMBER(10, 2) NOT NULL,
                CONSTRAINT fk_item_order FOREIGN KEY (order_id) REFERENCES "{schema}"."orders"(id) ON DELETE CASCADE
            )
            """
            provider.execute_statement(create_order_items)

            # Create sequence
            create_sequence = f"""
            CREATE SEQUENCE "{schema}"."order_seq"
            START WITH 1000
            INCREMENT BY 10
            CACHE 20
            NOCYCLE
            """
            provider.execute_statement(create_sequence)

            # Create view
            create_view = f"""
            CREATE OR REPLACE VIEW "{schema}"."active_orders" AS
            SELECT o.id, o.customer_id, o.order_date, o.total, c.name AS customer_name
            FROM "{schema}"."orders" o
            INNER JOIN "{schema}"."customers" c ON o.customer_id = c.id
            WHERE c.status = 'ACTIVE'
            """
            provider.execute_statement(create_view)

            # Create indexes
            provider.execute_statement(
                f'CREATE INDEX "{schema}"."idx_orders_customer" ON "{schema}"."orders"(customer_id)'
            )
            provider.execute_statement(
                f'CREATE INDEX "{schema}"."idx_orders_date" ON "{schema}"."orders"(order_date)'
            )

            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Ensure test schema exists
            test_schema = f"{schema}_TEST"
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
                test_object_types=["tables", "views", "sequences", "indexes"],
            )
            results = tester.run_round_trip_test()

            assert results["success"] is True, f"Round-trip failed: {results.get('errors', [])}"
            assert results["tables"]["reintrospected_count"] >= 3
            assert results["views"]["reintrospected_count"] >= 1
            assert results["sequences"]["reintrospected_count"] >= 1

        finally:
            try:
                provider.execute_statement(f'DROP SEQUENCE "{schema}"."order_seq"')
                provider.execute_statement(f'DROP VIEW "{schema}"."active_orders"')
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."order_items" CASCADE CONSTRAINTS'
                )
                provider.execute_statement(f'DROP TABLE "{schema}"."orders" CASCADE CONSTRAINTS')
                provider.execute_statement(f'DROP TABLE "{schema}"."customers" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
