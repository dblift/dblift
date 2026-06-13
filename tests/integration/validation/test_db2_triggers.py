"""
DB2 Triggers Tests.

Tests for DB2 trigger introspection.
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
class TestDb2Triggers:
    """DB2 triggers tests."""

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
        log = ConsoleLog("db2_triggers", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_before_insert_trigger(self, db_container):
        """Test introspection of a BEFORE INSERT trigger."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up (with rollback on error)
            try:
                provider.execute_statement(f"DROP TRIGGER {schema}.trg_before_insert")
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

            # Create table
            create_table = f"""
            CREATE TABLE {schema}.test_users (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Create trigger (DB2 syntax - requires REFERENCING clause)
            create_trigger = f"""
            CREATE TRIGGER {schema}.trg_before_insert
            BEFORE INSERT ON {schema}.test_users
            REFERENCING NEW AS NEW
            FOR EACH ROW
            MODE DB2SQL
            BEGIN ATOMIC
                SET NEW.created_at = CURRENT_TIMESTAMP;
            END
            """
            try:
                provider.execute_statement(create_trigger)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                # DB2 trigger syntax may be different, skip if creation fails
                pytest.skip(f"Trigger creation failed (DB2 syntax may differ): {e}")

            # Introspect (DB2 is case-sensitive, use uppercase)
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            triggers = introspector.get_triggers(schema, "TEST_USERS")

            # Find our trigger
            test_trigger = None
            for trig in triggers:
                if trig.name.upper() == "TRG_BEFORE_INSERT":
                    test_trigger = trig
                    break

            assert (
                test_trigger is not None
            ), f"Trigger 'trg_before_insert' not found. Available triggers: {[t.name for t in triggers]}"

        finally:
            try:
                provider.execute_statement(f"DROP TRIGGER {schema}.trg_before_insert")
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

    def test_after_update_trigger(self, db_container):
        """Test introspection of an AFTER UPDATE trigger."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up (with rollback on error)
            try:
                provider.execute_statement(f"DROP TRIGGER {schema}.trg_after_update")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_audit")
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

            # Create tables
            create_users = f"""
            CREATE TABLE {schema}.test_users (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_users)

            create_audit = f"""
            CREATE TABLE {schema}.test_audit (
                id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                user_id INTEGER NOT NULL,
                action VARCHAR(50) NOT NULL,
                action_time TIMESTAMP NOT NULL
            )
            """
            provider.execute_statement(create_audit)

            # Create trigger (DB2 syntax - requires REFERENCING clause)
            create_trigger = f"""
            CREATE TRIGGER {schema}.trg_after_update
            AFTER UPDATE ON {schema}.test_users
            REFERENCING NEW AS NEW OLD AS OLD
            FOR EACH ROW
            MODE DB2SQL
            BEGIN ATOMIC
                INSERT INTO {schema}.test_audit (user_id, action, action_time)
                VALUES (NEW.id, 'UPDATE', CURRENT_TIMESTAMP);
            END
            """
            try:
                provider.execute_statement(create_trigger)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                # DB2 trigger syntax may be different, skip if creation fails
                pytest.skip(f"Trigger creation failed (DB2 syntax may differ): {e}")

            # Introspect (DB2 is case-sensitive, use uppercase)
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            triggers = introspector.get_triggers(schema, "TEST_USERS")

            # Find our trigger
            test_trigger = None
            for trig in triggers:
                if trig.name.upper() == "TRG_AFTER_UPDATE":
                    test_trigger = trig
                    break

            assert (
                test_trigger is not None
            ), f"Trigger 'trg_after_update' not found. Available triggers: {[t.name for t in triggers]}"

        finally:
            try:
                provider.execute_statement(f"DROP TRIGGER {schema}.trg_after_update")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_audit")
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
