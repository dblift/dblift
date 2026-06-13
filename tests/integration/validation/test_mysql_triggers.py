"""
MySQL Triggers Tests.

Tests for MySQL triggers: BEFORE/AFTER triggers, introspection and SQL generation.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["mysql"],
    indirect=True,
)
class TestMySQLTriggers:
    """MySQL triggers tests."""

    def test_after_insert_trigger_introspection(self, db_container):
        """Test introspection of AFTER INSERT trigger."""
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
        log = ConsoleLog("mysql_triggers", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TRIGGER IF EXISTS `{schema}`.`trg_user_audit`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`user_audit`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create tables
            create_users = f"""
            CREATE TABLE `{schema}`.`users` (
                id INT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100)
            )
            """
            provider.execute_statement(create_users)

            create_audit = f"""
            CREATE TABLE `{schema}`.`user_audit` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                action VARCHAR(20),
                action_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_audit)

            # Create trigger
            create_trigger = f"""
            CREATE TRIGGER `{schema}`.`trg_user_audit`
            AFTER INSERT ON `{schema}`.`users`
            FOR EACH ROW
            BEGIN
                INSERT INTO `{schema}`.`user_audit` (user_id, action)
                VALUES (NEW.id, 'INSERT');
            END
            """
            provider.execute_statement(create_trigger)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            triggers = introspector.get_triggers(schema)

            # Find our trigger
            test_trigger = None
            for trigger in triggers:
                if trigger.name.lower() == "trg_user_audit":
                    test_trigger = trigger
                    break

            assert test_trigger is not None, "Trigger 'trg_user_audit' not found"
            assert test_trigger.table_name.lower() == "users", "Trigger should be on 'users' table"
            # MySQL triggers have timing (BEFORE/AFTER) and event (INSERT/UPDATE/DELETE)

        finally:
            try:
                provider.execute_statement(f"DROP TRIGGER IF EXISTS `{schema}`.`trg_user_audit`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`user_audit`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_before_update_trigger_introspection(self, db_container):
        """Test introspection of BEFORE UPDATE trigger."""
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
        log = ConsoleLog("mysql_before_update_trigger", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f"DROP TRIGGER IF EXISTS `{schema}`.`trg_update_timestamp`"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`products`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE `{schema}`.`products` (
                id INT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                price DECIMAL(10, 2),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_table)

            # Create trigger
            create_trigger = f"""
            CREATE TRIGGER `{schema}`.`trg_update_timestamp`
            BEFORE UPDATE ON `{schema}`.`products`
            FOR EACH ROW
            BEGIN
                SET NEW.updated_at = CURRENT_TIMESTAMP;
            END
            """
            provider.execute_statement(create_trigger)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            triggers = introspector.get_triggers(schema)

            # Find our trigger
            test_trigger = None
            for trigger in triggers:
                if trigger.name.lower() == "trg_update_timestamp":
                    test_trigger = trigger
                    break

            assert test_trigger is not None, "Trigger 'trg_update_timestamp' not found"
            assert (
                test_trigger.table_name.lower() == "products"
            ), "Trigger should be on 'products' table"

        finally:
            try:
                provider.execute_statement(
                    f"DROP TRIGGER IF EXISTS `{schema}`.`trg_update_timestamp`"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`products`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
