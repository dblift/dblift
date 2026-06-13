"""
Oracle Basic Validation Tests.

Comprehensive tests for basic Oracle features: tables, constraints, indexes.
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
class TestOracleValidation:
    """Oracle basic validation tests."""

    def test_round_trip_simple_table(self, db_container):
        """Test round-trip for a simple table with basic columns."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build native URL
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
        log = ConsoleLog("oracle_validation_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema.upper()  # Oracle uses uppercase
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up if exists
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create simple table
            create_table = f"""
            CREATE TABLE "{schema}"."users" (
                id NUMBER PRIMARY KEY,
                username VARCHAR2(50) NOT NULL,
                email VARCHAR2(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_round_trip_with_check_constraints(self, db_container):
        """Test round-trip for table with CHECK constraints."""
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
        log = ConsoleLog("oracle_check_test", enable_debug=False)
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

            # Create table with CHECK constraints
            create_table = f"""
            CREATE TABLE "{schema}"."products" (
                id NUMBER PRIMARY KEY,
                name VARCHAR2(100) NOT NULL,
                price NUMBER(10, 2) NOT NULL,
                status VARCHAR2(20) DEFAULT 'ACTIVE',
                CONSTRAINT chk_price_positive CHECK (price > 0),
                CONSTRAINT chk_status_valid CHECK (status IN ('ACTIVE', 'INACTIVE', 'PENDING'))
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
                provider.execute_statement(f'DROP TABLE "{schema}"."products" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_round_trip_with_foreign_keys(self, db_container):
        """Test round-trip for tables with foreign keys."""
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
        log = ConsoleLog("oracle_fk_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up (drop in reverse order)
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."orders" CASCADE CONSTRAINTS')
                provider.execute_statement(f'DROP TABLE "{schema}"."customers" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create parent table
            create_customers = f"""
            CREATE TABLE "{schema}"."customers" (
                id NUMBER PRIMARY KEY,
                name VARCHAR2(100) NOT NULL
            )
            """
            provider.execute_statement(create_customers)

            # Create child table with foreign key
            create_orders = f"""
            CREATE TABLE "{schema}"."orders" (
                id NUMBER PRIMARY KEY,
                customer_id NUMBER NOT NULL,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_order_customer FOREIGN KEY (customer_id) REFERENCES "{schema}"."customers"(id)
            )
            """
            provider.execute_statement(create_orders)
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
            assert results["tables"]["reintrospected_count"] >= 2

        finally:
            try:
                provider.execute_statement(f'DROP TABLE "{schema}"."orders" CASCADE CONSTRAINTS')
                provider.execute_statement(f'DROP TABLE "{schema}"."customers" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_check_constraint_extraction(self, db_container):
        """Test that CHECK constraints are correctly extracted."""
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
        log = ConsoleLog("oracle_check_extraction", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."test_check" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with named and unnamed CHECK constraints
            create_table = f"""
            CREATE TABLE "{schema}"."test_check" (
                id NUMBER PRIMARY KEY,
                age NUMBER,
                status VARCHAR2(20),
                CONSTRAINT chk_age_positive CHECK (age > 0),
                CHECK (status IN ('ACTIVE', 'INACTIVE'))
            )
            """

            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            # Debug: Print all found tables
            print(f"Found {len(tables)} tables:")
            for t in tables:
                print(f"  - {t.name}")

            # Oracle preserves case for quoted identifiers, but converts unquoted to uppercase
            # Try both cases
            test_table = next((t for t in tables if t.name.upper() == "TEST_CHECK"), None)
            assert (
                test_table is not None
            ), f"Table 'TEST_CHECK' not found. Found tables: {[t.name for t in tables]}"

            # Get CHECK constraints using the exact table name from introspection
            table_name = test_table.name
            check_constraints = introspector.get_check_constraints(schema, table_name)

            # Debug: Print all found constraints
            print(f"Found {len(check_constraints)} CHECK constraints:")
            for c in check_constraints:
                print(
                    f"  - {c.name}: {getattr(c, 'check_expression', getattr(c, 'definition', 'N/A'))}"
                )

            # Should have at least 2 CHECK constraints
            assert (
                len(check_constraints) >= 2
            ), f"Expected at least 2 CHECK constraints, found {len(check_constraints)}"

            # Find named constraint
            named_constraint = next(
                (c for c in check_constraints if c.name and c.name.upper() == "CHK_AGE_POSITIVE"),
                None,
            )
            assert (
                named_constraint is not None
            ), f"Named CHECK constraint 'CHK_AGE_POSITIVE' not found. Found constraints: {[c.name for c in check_constraints]}"

            # Find unnamed constraint (system-generated name)
            unnamed_constraints = [c for c in check_constraints if c.name != "CHK_AGE_POSITIVE"]
            assert (
                len(unnamed_constraints) >= 1
            ), f"Unnamed CHECK constraint not found. Found constraints: {[c.name for c in check_constraints]}"

        finally:
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."test_check" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
