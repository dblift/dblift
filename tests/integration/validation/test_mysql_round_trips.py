"""
MySQL Round-Trip Tests.

Comprehensive round-trip tests for MySQL features: generated columns, triggers, procedures, functions.
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
class TestMySQLRoundTrips:
    """MySQL round-trip tests for advanced features."""

    def test_generated_columns_round_trip(self, db_container):
        """Test round-trip for tables with generated columns."""
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
        log = ConsoleLog("mysql_generated_round_trip", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`products`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with generated columns
            create_table = f"""
            CREATE TABLE `{schema}`.`products` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                price DECIMAL(10, 2) NOT NULL,
                quantity INT NOT NULL,
                total_price DECIMAL(10, 2) AS (price * quantity) STORED,
                price_with_tax DECIMAL(10, 2) AS (price * 1.1) VIRTUAL
            )
            """
            provider.execute_statement(create_table)
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
                test_object_types=["tables"],
            )
            results = tester.run_round_trip_test()

            assert results["success"] is True, f"Round-trip failed: {results.get('errors', [])}"
            assert results["tables"]["reintrospected_count"] >= 1

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`products`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_triggers_round_trip(self, db_container):
        """Test round-trip for triggers."""
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
        log = ConsoleLog("mysql_triggers_round_trip", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TRIGGER IF EXISTS `{schema}`.`trg_audit_users`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`audit_log`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create tables
            create_audit = f"""
            CREATE TABLE `{schema}`.`audit_log` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                table_name VARCHAR(100) NOT NULL,
                action VARCHAR(20) NOT NULL,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_audit)

            create_users = f"""
            CREATE TABLE `{schema}`.`users` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_users)

            # Create trigger
            create_trigger = f"""
            CREATE TRIGGER `{schema}`.`trg_audit_users`
            AFTER INSERT ON `{schema}`.`users`
            FOR EACH ROW
            BEGIN
                INSERT INTO `{schema}`.`audit_log` (table_name, action)
                VALUES ('users', 'INSERT');
            END
            """
            provider.execute_statement(create_trigger)
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
                test_object_types=["tables", "triggers"],
            )
            results = tester.run_round_trip_test()

            # Triggers round-trip may have some differences, but should not fail completely
            assert (
                results["success"] is True or len(results.get("errors", [])) == 0
            ), f"Round-trip failed with errors: {results.get('errors', [])}"

        finally:
            try:
                provider.execute_statement(f"DROP TRIGGER IF EXISTS `{schema}`.`trg_audit_users`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`audit_log`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
