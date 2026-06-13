"""
MySQL SQL Generation Tests.

Tests for SQL generation quality: procedures, functions, triggers, views.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.sql_generator.generator_factory import SqlGeneratorFactory


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["mysql"],
    indirect=True,
)
class TestMySQLSqlGeneration:
    """MySQL SQL generation quality tests."""

    def test_procedure_sql_generation(self, db_container):
        """Test SQL generation for stored procedures."""
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
        log = ConsoleLog("mysql_proc_sql", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS `{schema}`.`get_user_by_id`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create procedure
            create_procedure = f"""
            CREATE PROCEDURE `{schema}`.`get_user_by_id`(IN p_user_id INT)
            BEGIN
                SELECT id, username, email FROM `{schema}`.`users` WHERE id = p_user_id;
            END
            """
            provider.execute_statement(create_procedure)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            procedures = introspector.get_procedures(schema)

            # Find our procedure
            test_procedure = None
            for proc in procedures:
                if proc.name.lower() == "get_user_by_id":
                    test_procedure = proc
                    break

            assert test_procedure is not None, "Procedure 'get_user_by_id' not found"

            # Generate SQL
            generator = SqlGeneratorFactory.create("mysql")
            sql = generator.generate_create_statement(test_procedure)

            # Check that SQL is generated
            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "PROCEDURE" in sql.upper(), f"PROCEDURE not found in generated SQL: {sql[:200]}"

        finally:
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS `{schema}`.`get_user_by_id`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_function_sql_generation(self, db_container):
        """Test SQL generation for functions."""
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
        log = ConsoleLog("mysql_func_sql", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP FUNCTION IF EXISTS `{schema}`.`add_numbers`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create function
            create_function = f"""
            CREATE FUNCTION `{schema}`.`add_numbers`(a INT, b INT)
            RETURNS INT
            DETERMINISTIC
            BEGIN
                RETURN a + b;
            END
            """
            provider.execute_statement(create_function)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            functions = introspector.get_functions(schema)

            # Find our function
            test_function = None
            for func in functions:
                if func.name.lower() == "add_numbers":
                    test_function = func
                    break

            assert test_function is not None, "Function 'add_numbers' not found"

            # Generate SQL
            generator = SqlGeneratorFactory.create("mysql")
            sql = generator.generate_create_statement(test_function)

            # Check that SQL is generated
            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "FUNCTION" in sql.upper(), f"FUNCTION not found in generated SQL: {sql[:200]}"

        finally:
            try:
                provider.execute_statement(f"DROP FUNCTION IF EXISTS `{schema}`.`add_numbers`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_trigger_sql_generation(self, db_container):
        """Test SQL generation for triggers."""
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
        log = ConsoleLog("mysql_trigger_sql", enable_debug=False)
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
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
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
            triggers = introspector.get_triggers(schema, "products")

            # Find our trigger
            test_trigger = None
            for trig in triggers:
                if trig.name.lower() == "trg_update_timestamp":
                    test_trigger = trig
                    break

            assert test_trigger is not None, "Trigger 'trg_update_timestamp' not found"

            # Generate SQL
            generator = SqlGeneratorFactory.create("mysql")
            sql = generator.generate_create_statement(test_trigger)

            # Check that SQL is generated
            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "TRIGGER" in sql.upper(), f"TRIGGER not found in generated SQL: {sql[:200]}"

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
