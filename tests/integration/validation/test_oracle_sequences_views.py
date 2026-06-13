"""
Oracle Sequences and Views Tests.

Comprehensive tests for Oracle sequences and views.
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
class TestOracleSequencesViews:
    """Oracle sequences and views tests."""

    def test_sequence_introspection(self, db_container):
        """Test sequence introspection."""
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
        log = ConsoleLog("oracle_sequence_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP SEQUENCE "{schema}"."test_seq"')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create sequence
            create_sequence = f"""
            CREATE SEQUENCE "{schema}"."test_seq"
            START WITH 1
            INCREMENT BY 1
            MINVALUE 1
            MAXVALUE 999999999
            CACHE 20
            CYCLE
            """

            provider.execute_statement(create_sequence)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            sequences = introspector.get_sequences(schema)

            assert len(sequences) >= 1
            test_seq = next((s for s in sequences if s.name.upper() == "TEST_SEQ"), None)
            assert test_seq is not None
            assert test_seq.start_with == 1
            assert test_seq.increment_by == 1

        finally:
            try:
                provider.execute_statement(f'DROP SEQUENCE "{schema}"."test_seq"')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_sequence_round_trip(self, db_container):
        """Test sequence round-trip."""
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
        log = ConsoleLog("oracle_sequence_rt", enable_debug=False)
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
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create sequence
            create_sequence = f"""
            CREATE SEQUENCE "{schema}"."order_seq"
            START WITH 100
            INCREMENT BY 5
            CACHE 10
            NOCYCLE
            """

            provider.execute_statement(create_sequence)
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
                test_object_types=["sequences"],
            )
            results = tester.run_round_trip_test()

            assert results["success"] is True, f"Round-trip failed: {results.get('errors', [])}"
            assert results["sequences"]["reintrospected_count"] >= 1

        finally:
            try:
                provider.execute_statement(f'DROP SEQUENCE "{schema}"."order_seq"')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_simple_view_introspection(self, db_container):
        """Test simple view introspection."""
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
        log = ConsoleLog("oracle_view_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP VIEW "{schema}"."active_users"')
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE "{schema}"."users" (
                id NUMBER PRIMARY KEY,
                username VARCHAR2(50) NOT NULL,
                status VARCHAR2(20) DEFAULT 'ACTIVE'
            )
            """
            provider.execute_statement(create_table)

            # Create view
            create_view = f"""
            CREATE OR REPLACE VIEW "{schema}"."active_users" AS
            SELECT id, username FROM "{schema}"."users" WHERE status = 'ACTIVE'
            """
            provider.execute_statement(create_view)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            views = introspector.get_views(schema)

            assert len(views) >= 1
            active_view = next((v for v in views if v.name.upper() == "ACTIVE_USERS"), None)
            assert active_view is not None
            assert active_view.query is not None
            query_upper = active_view.query.upper()
            assert "STATUS = 'ACTIVE'" in query_upper or "STATUS='ACTIVE'" in query_upper

        finally:
            try:
                provider.execute_statement(f'DROP VIEW "{schema}"."active_users"')
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_view_round_trip(self, db_container):
        """Test view round-trip."""
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
        log = ConsoleLog("oracle_view_rt", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f'DROP VIEW "{schema}"."user_summary"')
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE "{schema}"."users" (
                id NUMBER PRIMARY KEY,
                username VARCHAR2(50) NOT NULL,
                email VARCHAR2(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_table)

            # Create view
            create_view = f"""
            CREATE OR REPLACE VIEW "{schema}"."user_summary" AS
            SELECT id, username, email FROM "{schema}"."users" WHERE created_at >= SYSDATE - 30
            """
            provider.execute_statement(create_view)
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
                test_object_types=["tables", "views"],
            )
            results = tester.run_round_trip_test()

            assert results["success"] is True, f"Round-trip failed: {results.get('errors', [])}"
            assert results["views"]["reintrospected_count"] >= 1

        finally:
            try:
                provider.execute_statement(f'DROP VIEW "{schema}"."user_summary"')
                provider.execute_statement(f'DROP TABLE "{schema}"."users" CASCADE CONSTRAINTS')
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
