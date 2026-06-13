"""
DB2 Stored Procedures and Functions Tests.

Tests for DB2 stored procedures and functions introspection.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["db2"],
    indirect=True,
)
class TestDb2ProceduresFunctions:
    """DB2 stored procedures and functions tests."""

    def _get_provider(self, db_container):
        """Create database provider."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

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
        log = ConsoleLog("db2_procedures", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_stored_procedure_introspection(self, db_container):
        """Test introspection of a stored procedure."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP PROCEDURE {schema}.test_get_user")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create table first (required for procedure)
            create_table = f"""
            CREATE TABLE {schema}.test_users (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Create stored procedure
            create_proc = f"""
            CREATE PROCEDURE {schema}.test_get_user(
                IN p_user_id INTEGER,
                OUT p_user_name VARCHAR(100)
            )
            LANGUAGE SQL
            BEGIN
                SELECT name INTO p_user_name
                FROM {schema}.test_users
                WHERE id = p_user_id;
            END
            """
            try:
                provider.execute_statement(create_proc)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                # Procedure creation may fail for other reasons
                pytest.skip(f"Procedure creation failed: {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            procedures = introspector.get_procedures(schema)

            # Find our procedure
            test_proc = None
            for proc in procedures:
                if proc.name.upper() == "TEST_GET_USER":
                    test_proc = proc
                    break

            assert (
                test_proc is not None
            ), f"Procedure 'test_get_user' not found. Available: {[p.name for p in procedures]}"

        finally:
            try:
                provider.execute_statement(f"DROP PROCEDURE {schema}.test_get_user")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_function_introspection(self, db_container):
        """Test introspection of a scalar function."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP FUNCTION {schema}.test_add_numbers")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create function
            create_func = f"""
            CREATE FUNCTION {schema}.test_add_numbers(
                a INTEGER,
                b INTEGER
            )
            RETURNS INTEGER
            LANGUAGE SQL
            DETERMINISTIC
            NO EXTERNAL ACTION
            RETURN a + b
            """
            try:
                provider.execute_statement(create_func)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                pytest.skip(f"Function creation failed: {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            functions = introspector.get_functions(schema)

            # Find our function
            test_func = None
            for func in functions:
                if func.name.upper() == "TEST_ADD_NUMBERS":
                    test_func = func
                    break

            assert (
                test_func is not None
            ), f"Function 'test_add_numbers' not found. Available: {[f.name for f in functions]}"

        finally:
            try:
                provider.execute_statement(f"DROP FUNCTION {schema}.test_add_numbers")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
