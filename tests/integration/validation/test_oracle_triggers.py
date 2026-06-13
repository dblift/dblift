"""
Oracle Triggers Tests.

Comprehensive tests for Oracle triggers.
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
class TestOracleTriggers:
    """Oracle trigger tests."""

    def test_after_insert_trigger_introspection(self, db_container):
        """Test AFTER INSERT trigger introspection."""
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
        log = ConsoleLog("oracle_trigger_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP TRIGGER "{schema}"."audit_users_insert"')
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                provider.execute_statement(f'DROP TABLE "{schema}"."audit_log" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create tables
            create_users = f"""
            CREATE TABLE "{schema}"."users" (
                id NUMBER PRIMARY KEY,
                username VARCHAR2(50) NOT NULL
            )
            """
            provider.execute_statement(create_users)

            create_audit = f"""
            CREATE TABLE "{schema}"."audit_log" (
                id NUMBER PRIMARY KEY,
                table_name VARCHAR2(50),
                action VARCHAR2(20),
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_audit)

            # Create trigger
            create_trigger = f"""
            CREATE OR REPLACE TRIGGER "{schema}"."audit_users_insert"
            AFTER INSERT ON "{schema}"."users"
            FOR EACH ROW
            BEGIN
                INSERT INTO "{schema}"."audit_log" (id, table_name, action)
                VALUES (audit_seq.NEXTVAL, 'users', 'INSERT');
            END;
            """

            provider.execute_statement(create_trigger)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            triggers = introspector.get_triggers(schema)

            assert len(triggers) >= 1
            audit_trigger = next(
                (t for t in triggers if t.name.upper() == "AUDIT_USERS_INSERT"), None
            )
            assert audit_trigger is not None
            assert audit_trigger.table_name.upper() == "USERS"
            assert "AFTER" in audit_trigger.timing.upper() if audit_trigger.timing else False

        finally:
            try:
                provider.execute_statement(f'DROP TRIGGER "{schema}"."audit_users_insert"')
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                provider.execute_statement(f'DROP TABLE "{schema}"."audit_log" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_before_update_trigger_introspection(self, db_container):
        """Test BEFORE UPDATE trigger introspection."""
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
        log = ConsoleLog("oracle_trigger_before", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP TRIGGER "{schema}"."validate_users_update"')
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_users = f"""
            CREATE TABLE "{schema}"."users" (
                id NUMBER PRIMARY KEY,
                username VARCHAR2(50) NOT NULL,
                status VARCHAR2(20) DEFAULT 'ACTIVE'
            )
            """
            provider.execute_statement(create_users)

            # Create trigger
            create_trigger = f"""
            CREATE OR REPLACE TRIGGER "{schema}"."validate_users_update"
            BEFORE UPDATE ON "{schema}"."users"
            FOR EACH ROW
            BEGIN
                IF :NEW.status NOT IN ('ACTIVE', 'INACTIVE', 'PENDING') THEN
                    RAISE_APPLICATION_ERROR(-20001, 'Invalid status');
                END IF;
            END;
            """

            provider.execute_statement(create_trigger)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            triggers = introspector.get_triggers(schema)

            assert len(triggers) >= 1
            validate_trigger = next(
                (t for t in triggers if t.name.upper() == "VALIDATE_USERS_UPDATE"), None
            )
            assert validate_trigger is not None
            assert "BEFORE" in validate_trigger.timing.upper() if validate_trigger.timing else False

        finally:
            try:
                provider.execute_statement(f'DROP TRIGGER "{schema}"."validate_users_update"')
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_trigger_round_trip(self, db_container):
        """Test trigger round-trip."""
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
        log = ConsoleLog("oracle_trigger_rt", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP TRIGGER "{schema}"."set_updated_at"')
                provider.execute_statement(f'DROP TABLE "{schema}"."products" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE "{schema}"."products" (
                id NUMBER PRIMARY KEY,
                name VARCHAR2(100) NOT NULL,
                updated_at TIMESTAMP
            )
            """
            provider.execute_statement(create_table)

            # Create trigger
            create_trigger = f"""
            CREATE OR REPLACE TRIGGER "{schema}"."set_updated_at"
            BEFORE UPDATE ON "{schema}"."products"
            FOR EACH ROW
            BEGIN
                :NEW.updated_at := CURRENT_TIMESTAMP;
            END;
            """

            provider.execute_statement(create_trigger)
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
                test_object_types=["tables", "triggers"],
            )
            results = tester.run_round_trip_test()

            assert results["success"] is True, f"Round-trip failed: {results.get('errors', [])}"
            assert results["triggers"]["reintrospected_count"] >= 1

        finally:
            try:
                provider.execute_statement(f'DROP TRIGGER "{schema}"."set_updated_at"')
                provider.execute_statement(f'DROP TABLE "{schema}"."products" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
