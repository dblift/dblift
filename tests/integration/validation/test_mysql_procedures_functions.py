"""
MySQL Procedures and Functions Tests.

Tests for MySQL stored procedures and functions: introspection and SQL generation.
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
class TestMySQLProceduresFunctions:
    """MySQL procedures and functions tests."""

    def test_simple_procedure_introspection(self, db_container):
        """Test introspection of a simple stored procedure."""
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
        log = ConsoleLog("mysql_procedures", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS `{schema}`.`get_user_count`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create procedure
            create_procedure = f"""
            CREATE PROCEDURE `{schema}`.`get_user_count`()
            BEGIN
                SELECT COUNT(*) as total FROM `{schema}`.`users`;
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
                if proc.name.lower() == "get_user_count":
                    test_procedure = proc
                    break

            assert test_procedure is not None, "Procedure 'get_user_count' not found"

        finally:
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS `{schema}`.`get_user_count`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_procedure_with_parameters(self, db_container):
        """Test introspection of procedure with IN/OUT parameters."""
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
        log = ConsoleLog("mysql_procedure_params", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS `{schema}`.`add_user`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create procedure with parameters
            create_procedure = f"""
            CREATE PROCEDURE `{schema}`.`add_user`(
                IN p_username VARCHAR(50),
                IN p_email VARCHAR(100),
                OUT p_user_id INT
            )
            BEGIN
                INSERT INTO `{schema}`.`users` (username, email)
                VALUES (p_username, p_email);
                SET p_user_id = LAST_INSERT_ID();
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
                if proc.name.lower() == "add_user":
                    test_procedure = proc
                    break

            assert test_procedure is not None, "Procedure 'add_user' not found"
            # Check parameters (if supported)
            if hasattr(test_procedure, "parameters") and test_procedure.parameters:
                assert (
                    len(test_procedure.parameters) >= 3
                ), f"Expected at least 3 parameters, found {len(test_procedure.parameters)}"

        finally:
            try:
                provider.execute_statement(f"DROP PROCEDURE IF EXISTS `{schema}`.`add_user`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_scalar_function_introspection(self, db_container):
        """Test introspection of a scalar function."""
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
        log = ConsoleLog("mysql_functions", enable_debug=False)
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
                    f"DROP FUNCTION IF EXISTS `{schema}`.`calculate_discount`"
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create function
            create_function = f"""
            CREATE FUNCTION `{schema}`.`calculate_discount`(
                price DECIMAL(10, 2),
                discount_rate DECIMAL(5, 2)
            )
            RETURNS DECIMAL(10, 2)
            DETERMINISTIC
            BEGIN
                RETURN price * (1 - discount_rate);
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
                if func.name.lower() == "calculate_discount":
                    test_function = func
                    break

            assert test_function is not None, "Function 'calculate_discount' not found"

        finally:
            try:
                provider.execute_statement(
                    f"DROP FUNCTION IF EXISTS `{schema}`.`calculate_discount`"
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
