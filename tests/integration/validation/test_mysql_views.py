"""
MySQL Views Tests.

Tests for MySQL views: introspection and round-trip.
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
class TestMySQLViews:
    """MySQL views tests."""

    def test_simple_view_introspection(self, db_container):
        """Test introspection of a simple view."""
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
        log = ConsoleLog("mysql_views", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS `{schema}`.`active_users`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE `{schema}`.`users` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100),
                status VARCHAR(20) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create view
            create_view = f"""
            CREATE VIEW `{schema}`.`active_users` AS
            SELECT id, username, email
            FROM `{schema}`.`users`
            WHERE status = 'ACTIVE'
            """
            provider.execute_statement(create_view)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            views = introspector.get_views(schema)

            # Find our view
            test_view = None
            for view in views:
                if view.name.lower() == "active_users":
                    test_view = view
                    break

            assert test_view is not None, "View 'active_users' not found"
            # MySQL may format the query differently, check for the condition
            query_upper = test_view.query.upper()
            assert (
                "STATUS" in query_upper and "ACTIVE" in query_upper
            ), f"View query should contain STATUS and ACTIVE, got: {test_view.query}"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS `{schema}`.`active_users`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_view_round_trip(self, db_container):
        """Test round-trip for a view (introspection and SQL generation)."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from core.sql_generator.generator_factory import SqlGeneratorFactory
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
        log = ConsoleLog("mysql_view_round_trip", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS `{schema}`.`user_summary`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE `{schema}`.`users` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_table)

            # Create view
            create_view = f"""
            CREATE VIEW `{schema}`.`user_summary` AS
            SELECT 
                COUNT(*) as total_users,
                MAX(created_at) as latest_user
            FROM `{schema}`.`users`
            """
            provider.execute_statement(create_view)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect view
            introspector = IntrospectorFactory.create(provider, log=log)
            views = introspector.get_views(schema)

            # Find our view
            test_view = None
            for view in views:
                if view.name.lower() == "user_summary":
                    test_view = view
                    break

            assert test_view is not None, "View 'user_summary' not found"

            # Test SQL generation
            generator = SqlGeneratorFactory.create("mysql")
            sql = generator.generate_create_statement(test_view)
            assert sql is not None, "SQL generation should not return None"
            sql_upper = sql.upper()
            # MySQL view SQL may include ALGORITHM, DEFINER, etc., but should contain VIEW
            assert "VIEW" in sql_upper, f"Generated SQL should contain VIEW, got: {sql}"
            assert (
                "user_summary" in sql.lower()
            ), f"Generated SQL should contain view name, got: {sql}"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW IF EXISTS `{schema}`.`user_summary`")
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
