"""
Oracle Virtual Columns Tests.

Comprehensive tests for Oracle virtual columns (GENERATED ALWAYS AS ... VIRTUAL).
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
class TestOracleVirtualColumns:
    """Oracle virtual column tests."""

    def test_virtual_column_introspection(self, db_container):
        """Test virtual column introspection."""
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
        log = ConsoleLog("oracle_virtual_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."products" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with virtual column
            create_table = f"""
            CREATE TABLE "{schema}"."products" (
                id NUMBER PRIMARY KEY,
                price NUMBER(10, 2) NOT NULL,
                quantity NUMBER NOT NULL,
                total NUMBER GENERATED ALWAYS AS (price * quantity) VIRTUAL
            )
            """

            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            assert len(tables) >= 1
            products_table = next((t for t in tables if t.name.upper() == "PRODUCTS"), None)
            assert products_table is not None

            # Find virtual column
            total_col = next((c for c in products_table.columns if c.name.upper() == "TOTAL"), None)
            assert total_col is not None
            assert hasattr(total_col, "is_computed")
            assert total_col.is_computed is True
            assert hasattr(total_col, "computed_expression")
            assert total_col.computed_expression is not None
            # Oracle virtual columns are not stored
            assert hasattr(total_col, "computed_stored")
            assert total_col.computed_stored is False

        finally:
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."products" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_virtual_column_round_trip(self, db_container):
        """Test virtual column round-trip."""
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
        log = ConsoleLog("oracle_virtual_rt", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."orders" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with virtual column
            create_table = f"""
            CREATE TABLE "{schema}"."orders" (
                id NUMBER PRIMARY KEY,
                subtotal NUMBER(10, 2) NOT NULL,
                tax_rate NUMBER(5, 4) DEFAULT 0.1,
                total NUMBER GENERATED ALWAYS AS (subtotal * (1 + tax_rate)) VIRTUAL
            )
            """

            provider.execute_statement(create_table)
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
                test_object_types=["tables"],
            )
            results = tester.run_round_trip_test()

            assert results["success"] is True, f"Round-trip failed: {results.get('errors', [])}"
            assert results["tables"]["reintrospected_count"] >= 1

        finally:
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."orders" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
