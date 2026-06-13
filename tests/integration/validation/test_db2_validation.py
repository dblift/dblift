"""
DB2 Basic Validation Tests.

Tests for basic DB2 table introspection and constraints.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["db2"],
    indirect=True,
)
class TestDb2Validation:
    """DB2 basic validation tests."""

    def _get_provider(self, db_container):
        """Create database provider."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Build native URL
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
        log = ConsoleLog("db2_validation", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_simple_table_introspection(self, db_container):
        """Test basic table introspection."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE {schema}.test_users (
                id INTEGER NOT NULL PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_USERS":
                    test_table = table
                    break

            assert test_table is not None, f"Table 'test_users' not found in schema {schema}"
            assert (
                len(test_table.columns) >= 3
            ), f"Expected at least 3 columns, found {len(test_table.columns)}"

            # Check for primary key constraint
            pk_constraints = [
                c for c in test_table.constraints if c.constraint_type.value == "PRIMARY KEY"
            ]
            assert len(pk_constraints) >= 1, "Expected at least 1 PRIMARY KEY constraint"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_foreign_key_constraint(self, db_container):
        """Test foreign key constraint introspection."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_orders")
                provider.execute_statement(f"DROP TABLE {schema}.test_customers")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create parent table
            create_customers = f"""
            CREATE TABLE {schema}.test_customers (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_customers)

            # Create child table with foreign key
            create_orders = f"""
            CREATE TABLE {schema}.test_orders (
                id INTEGER NOT NULL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_date DATE NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES {schema}.test_customers(id)
            )
            """
            provider.execute_statement(create_orders)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find orders table
            orders_table = None
            for table in tables:
                if table.name.upper() == "TEST_ORDERS":
                    orders_table = table
                    break

            assert orders_table is not None, "Table 'test_orders' not found"

            # Check for foreign key constraint
            fk_constraints = [
                c for c in orders_table.constraints if c.constraint_type.value == "FOREIGN KEY"
            ]
            assert len(fk_constraints) >= 1, "Expected at least 1 FOREIGN KEY constraint"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_orders")
                provider.execute_statement(f"DROP TABLE {schema}.test_customers")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_check_constraint(self, db_container):
        """Test CHECK constraint introspection."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_products")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with CHECK constraint
            create_table = f"""
            CREATE TABLE {schema}.test_products (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                CHECK (price > 0)
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_PRODUCTS":
                    test_table = table
                    break

            assert test_table is not None, "Table 'test_products' not found"

            # Check for CHECK constraint
            check_constraints = [
                c for c in test_table.constraints if c.constraint_type.value == "CHECK"
            ]
            assert len(check_constraints) >= 1, "Expected at least 1 CHECK constraint"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_products")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
