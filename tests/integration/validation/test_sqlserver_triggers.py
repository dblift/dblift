"""
SQL Server Triggers Tests.

Comprehensive tests for triggers (AFTER and INSTEAD OF).
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["sqlserver"],
    indirect=True,
)
class TestSQLServerTriggers:
    """SQL Server trigger tests."""

    def test_after_insert_trigger(self, db_container):
        """Test AFTER INSERT trigger."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build SQLAlchemy URL
        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type="sqlserver",
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "dbo"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_trigger_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.users"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.set_created_at")
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table and trigger
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                created_at DATETIME
            )
            """
            create_trigger = f"""
            CREATE TRIGGER {schema}.set_created_at
            ON {table_name}
            AFTER INSERT
            AS
            BEGIN
                UPDATE {table_name} SET created_at = GETDATE() WHERE id IN (SELECT id FROM inserted);
            END
            """

            provider.execute_statement(create_table)
            provider.execute_statement(create_trigger)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            triggers = introspector.get_triggers(schema, "users")

            assert len(triggers) >= 1
            trigger = next((t for t in triggers if t.name == "set_created_at"), None)
            assert trigger is not None
            assert trigger.timing == "AFTER"
            assert "INSERT" in trigger.events

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.set_created_at")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.users")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_after_update_trigger(self, db_container):
        """Test AFTER UPDATE trigger."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build SQLAlchemy URL
        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type="sqlserver",
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "dbo"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_trigger_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.products"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.update_timestamp")
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table and trigger
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                last_modified DATETIME
            )
            """
            create_trigger = f"""
            CREATE TRIGGER {schema}.update_timestamp
            ON {table_name}
            AFTER UPDATE
            AS
            BEGIN
                UPDATE {table_name} SET last_modified = GETDATE() WHERE id IN (SELECT id FROM inserted);
            END
            """

            provider.execute_statement(create_table)
            provider.execute_statement(create_trigger)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            triggers = introspector.get_triggers(schema, "products")

            assert len(triggers) >= 1
            trigger = next((t for t in triggers if t.name == "update_timestamp"), None)
            assert trigger is not None
            assert trigger.timing == "AFTER"
            assert "UPDATE" in trigger.events

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.update_timestamp")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_instead_of_trigger(self, db_container):
        """Test INSTEAD OF trigger."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build SQLAlchemy URL
        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type="sqlserver",
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "dbo"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_trigger_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            view_name = f"{schema}.user_view"
            table_name = f"{schema}.users"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.user_view_insert")
                provider.execute_statement(f"DROP VIEW IF EXISTS {view_name}")
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table, view, and INSTEAD OF trigger
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                name NVARCHAR(100) NOT NULL
            )
            """
            create_view = f"""
            CREATE VIEW {view_name} AS
            SELECT id, name FROM {table_name}
            """
            create_trigger = f"""
            CREATE TRIGGER {schema}.user_view_insert
            ON {view_name}
            INSTEAD OF INSERT
            AS
            BEGIN
                INSERT INTO {table_name} (id, name)
                SELECT id, name FROM inserted;
            END
            """

            provider.execute_statement(create_table)
            provider.execute_statement(create_view)
            provider.execute_statement(create_trigger)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            triggers = introspector.get_triggers(schema, "user_view")

            assert len(triggers) >= 1
            trigger = next((t for t in triggers if t.name == "user_view_insert"), None)
            assert trigger is not None
            assert trigger.timing == "INSTEAD OF"
            assert "INSERT" in trigger.events

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.user_view_insert")
                provider.execute_statement(f"DROP VIEW IF EXISTS {schema}.user_view")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.users")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_trigger_round_trip(self, db_container):
        """Test that triggers are preserved in round-trip."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build SQLAlchemy URL
        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type="sqlserver",
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "dbo"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_trigger_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.audit_log"
            users_table = f"{schema}.users"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.audit_users_insert")
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
                provider.execute_statement(f"DROP TABLE IF EXISTS {users_table}")
            except Exception:
                pass

            # Create tables and trigger
            create_audit = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY IDENTITY(1,1),
                table_name NVARCHAR(100),
                action NVARCHAR(50),
                timestamp DATETIME
            )
            """
            create_users = f"""
            CREATE TABLE {users_table} (
                id INT PRIMARY KEY,
                name NVARCHAR(100)
            )
            """
            create_trigger = f"""
            CREATE TRIGGER {schema}.audit_users_insert
            ON {users_table}
            AFTER INSERT
            AS
            BEGIN
                INSERT INTO {table_name} (table_name, action, timestamp)
                VALUES ('users', 'INSERT', GETDATE());
            END
            """

            provider.execute_statement(create_audit)
            provider.execute_statement(create_users)
            provider.execute_statement(create_trigger)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)

            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables", "triggers"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('triggers', {}).get('differences', [])}"
            )

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TRIGGER IF EXISTS {schema}.audit_users_insert")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.audit_log")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.users")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()
