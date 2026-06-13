"""
DB2 Round-Trip Tests.

Tests for comprehensive round-trip validation.
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
class TestDb2RoundTrip:
    """DB2 round-trip tests."""

    def _commit(self, provider):
        connection = provider.connection
        if hasattr(connection, "getAutoCommit") and connection.getAutoCommit():
            return
        connection.commit()

    def _rollback(self, provider):
        connection = provider.connection
        if hasattr(connection, "getAutoCommit") and connection.getAutoCommit():
            return
        connection.rollback()

    def _get_provider(self, db_container):
        """Create database provider."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

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
        log = ConsoleLog("db2_round_trip", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_round_trip_with_identity(self, db_container):
        """Test round-trip for table with identity column."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        self._commit(provider)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_round_trip_identity")
                self._commit(provider)
            except Exception:
                self._rollback(provider)

            # Create source table with identity
            create_table = f"""
            CREATE TABLE {schema}.test_round_trip_identity (
                id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)
            self._commit(provider)

            # Introspect source
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            source_table = None
            for table in tables:
                if table.name.upper() == "TEST_ROUND_TRIP_IDENTITY":
                    source_table = table
                    break

            assert source_table is not None, "Source table not found"

            # Generate SQL
            source_table.dialect = "db2"
            sql = source_table.create_statement

            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "CREATE TABLE" in sql.upper(), "Generated SQL should contain CREATE TABLE"
            assert "IDENTITY" in sql.upper(), "Generated SQL should contain IDENTITY"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_round_trip_identity")
                self._commit(provider)
            except Exception:
                self._rollback(provider)
            provider.close()

    def test_round_trip_with_foreign_keys(self, db_container):
        """Test round-trip for tables with foreign key relationships."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        self._commit(provider)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_orders_fk")
                provider.execute_statement(f"DROP TABLE {schema}.test_customers_fk")
                self._commit(provider)
            except Exception:
                self._rollback(provider)

            # Create parent table
            create_customers = f"""
            CREATE TABLE {schema}.test_customers_fk (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_customers)

            # Create child table with foreign key
            create_orders = f"""
            CREATE TABLE {schema}.test_orders_fk (
                id INTEGER NOT NULL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_date DATE NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES {schema}.test_customers_fk(id)
            )
            """
            provider.execute_statement(create_orders)
            self._commit(provider)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find orders table
            orders_table = None
            for table in tables:
                if table.name.upper() == "TEST_ORDERS_FK":
                    orders_table = table
                    break

            assert orders_table is not None, "Orders table not found"

            # Check for foreign key constraint
            fk_constraints = [
                c for c in orders_table.constraints if c.constraint_type.value == "FOREIGN KEY"
            ]
            assert len(fk_constraints) >= 1, "Expected at least 1 FOREIGN KEY constraint"

            # Generate SQL
            orders_table.dialect = "db2"
            sql = orders_table.create_statement

            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "FOREIGN KEY" in sql.upper(), "Generated SQL should contain FOREIGN KEY"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_orders_fk")
                provider.execute_statement(f"DROP TABLE {schema}.test_customers_fk")
                self._commit(provider)
            except Exception:
                self._rollback(provider)
            provider.close()

    def test_round_trip_with_indexes(self, db_container):
        """Test round-trip for table with indexes."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        self._commit(provider)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP INDEX {schema}.idx_test_email")
                provider.execute_statement(f"DROP TABLE {schema}.test_indexed")
                self._commit(provider)
            except Exception:
                self._rollback(provider)

            # Create table
            create_table = f"""
            CREATE TABLE {schema}.test_indexed (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create index
            create_index = f"""
            CREATE INDEX {schema}.idx_test_email ON {schema}.test_indexed(email)
            """
            provider.execute_statement(create_index)
            self._commit(provider)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)
            indexes = introspector.get_indexes(schema, "TEST_INDEXED")

            # Verify table and index
            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_INDEXED":
                    test_table = table
                    break

            assert test_table is not None, "Table not found"
            assert len(indexes) >= 1, f"Expected at least 1 index, found: {len(indexes)}"

        finally:
            try:
                provider.execute_statement(f"DROP INDEX {schema}.idx_test_email")
                provider.execute_statement(f"DROP TABLE {schema}.test_indexed")
                self._commit(provider)
            except Exception:
                self._rollback(provider)
            provider.close()
