"""
DB2 Synonyms (ALIAS) Tests.

Tests for DB2 synonym/alias introspection.
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
class TestDb2Synonyms:
    """DB2 synonyms tests."""

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
        log = ConsoleLog("db2_synonyms", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_table_alias_introspection(self, db_container):
        """Test introspection of a table alias (synonym)."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP ALIAS {schema}.test_users_alias")
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table first
            create_table = f"""
            CREATE TABLE {schema}.test_users (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create alias (synonym)
            create_alias = f"""
            CREATE ALIAS {schema}.test_users_alias FOR {schema}.test_users
            """
            try:
                provider.execute_statement(create_alias)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                pytest.skip(f"Alias creation failed: {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            synonyms = introspector.get_synonyms(schema)

            # Find our alias
            test_alias = None
            for syn in synonyms:
                if syn.name.upper() == "TEST_USERS_ALIAS":
                    test_alias = syn
                    break

            assert (
                test_alias is not None
            ), f"Alias 'test_users_alias' not found. Available: {[s.name for s in synonyms]}"

        finally:
            try:
                provider.execute_statement(f"DROP ALIAS {schema}.test_users_alias")
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
