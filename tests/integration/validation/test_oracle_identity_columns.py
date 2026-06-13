"""
Oracle Identity Columns Tests.

Comprehensive tests for Oracle identity columns (GENERATED AS IDENTITY, Oracle 12c+).
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
class TestOracleIdentityColumns:
    """Oracle identity column tests."""

    def test_identity_column_introspection(self, db_container):
        """Test identity column introspection."""
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
        log = ConsoleLog("oracle_identity_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with identity column (Oracle 12c+)
            create_table = f"""
            CREATE TABLE "{schema}"."users" (
                id NUMBER GENERATED AS IDENTITY PRIMARY KEY,
                username VARCHAR2(50) NOT NULL,
                email VARCHAR2(100)
            )
            """

            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            assert len(tables) >= 1
            users_table = next((t for t in tables if t.name.upper() == "USERS"), None)
            assert users_table is not None

            # Find identity column
            id_col = next((c for c in users_table.columns if c.name.upper() == "ID"), None)
            assert id_col is not None
            assert hasattr(id_col, "is_identity")
            assert id_col.is_identity is True

        finally:
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_identity_column_with_custom_seed(self, db_container):
        """Test identity column with custom seed and increment."""
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
        log = ConsoleLog("oracle_identity_seed", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."customers" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with identity column with custom seed/increment
            create_table = f"""
            CREATE TABLE "{schema}"."customers" (
                id NUMBER GENERATED AS IDENTITY (START WITH 100 INCREMENT BY 5) PRIMARY KEY,
                name VARCHAR2(100) NOT NULL
            )
            """

            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            assert len(tables) >= 1
            customers_table = next((t for t in tables if t.name.upper() == "CUSTOMERS"), None)
            assert customers_table is not None

            # Find identity column
            id_col = next((c for c in customers_table.columns if c.name.upper() == "ID"), None)
            assert id_col is not None
            assert hasattr(id_col, "is_identity")
            assert id_col.is_identity is True

        finally:
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."customers" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_identity_column_round_trip(self, db_container):
        """Test identity column round-trip."""
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
        log = ConsoleLog("oracle_identity_rt", enable_debug=False)
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

            # Create table with identity column
            create_table = f"""
            CREATE TABLE "{schema}"."orders" (
                id NUMBER GENERATED AS IDENTITY PRIMARY KEY,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                total NUMBER(10, 2)
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
