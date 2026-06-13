"""
DB2 Comprehensive Tests.

Tests for comprehensive DB2 schema introspection.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["db2"],
    indirect=True,
)
class TestDb2Comprehensive:
    """DB2 comprehensive tests."""

    def _get_provider(self, db_container):
        """Create database provider."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        database_url = (
            f"ibm_db_sa://{db_container['host']}:{db_container['port']}/{db_container['database']}"
        )

        db_config = DatabaseConfig(
            type=db_type,
            url=database_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=schema,
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("db2_comprehensive", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_complex_schema_introspection(self, db_container):
        """Test introspection of a complex schema with multiple objects."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP VIEW {schema}.test_order_summary")
                provider.execute_statement(f"DROP TABLE {schema}.test_order_items")
                provider.execute_statement(f"DROP TABLE {schema}.test_orders")
                provider.execute_statement(f"DROP TABLE {schema}.test_customers")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create customers table
            create_customers = f"""
            CREATE TABLE {schema}.test_customers (
                id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_customers)

            # Create orders table
            create_orders = f"""
            CREATE TABLE {schema}.test_orders (
                id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_date DATE NOT NULL,
                total DECIMAL(10, 2) NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES {schema}.test_customers(id)
            )
            """
            provider.execute_statement(create_orders)

            # Create order_items table
            create_order_items = f"""
            CREATE TABLE {schema}.test_order_items (
                id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                order_id INTEGER NOT NULL,
                product_name VARCHAR(100) NOT NULL,
                quantity INTEGER NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                FOREIGN KEY (order_id) REFERENCES {schema}.test_orders(id),
                CHECK (quantity > 0),
                CHECK (price >= 0)
            )
            """
            provider.execute_statement(create_order_items)

            # Create view
            create_view = f"""
            CREATE VIEW {schema}.test_order_summary AS
            SELECT 
                o.id AS order_id,
                c.name AS customer_name,
                o.order_date,
                o.total,
                COUNT(oi.id) AS item_count
            FROM {schema}.test_orders o
            INNER JOIN {schema}.test_customers c ON o.customer_id = c.id
            LEFT JOIN {schema}.test_order_items oi ON o.id = oi.order_id
            GROUP BY o.id, c.name, o.order_date, o.total
            """
            provider.execute_statement(create_view)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)
            views = introspector.get_views(schema)

            # Verify tables
            table_names = [t.name.upper() for t in tables]
            assert "TEST_CUSTOMERS" in table_names, "test_customers table not found"
            assert "TEST_ORDERS" in table_names, "test_orders table not found"
            assert "TEST_ORDER_ITEMS" in table_names, "test_order_items table not found"

            # Verify view
            view_names = [v.name.upper() for v in views]
            assert "TEST_ORDER_SUMMARY" in view_names, "test_order_summary view not found"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW {schema}.test_order_summary")
                provider.execute_statement(f"DROP TABLE {schema}.test_order_items")
                provider.execute_statement(f"DROP TABLE {schema}.test_orders")
                provider.execute_statement(f"DROP TABLE {schema}.test_customers")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_round_trip_simple_table(self, db_container):
        """Test round-trip validation for a simple table."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_round_trip")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create source table
            create_table = f"""
            CREATE TABLE {schema}.test_round_trip (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect source
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            source_table = None
            for table in tables:
                if table.name.upper() == "TEST_ROUND_TRIP":
                    source_table = table
                    break

            assert source_table is not None, "Source table 'test_round_trip' not found"

            # Generate SQL
            source_table.dialect = "db2"
            sql = source_table.create_statement

            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "CREATE TABLE" in sql.upper(), "Generated SQL should contain CREATE TABLE"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_round_trip")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
