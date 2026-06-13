"""
DB2 Indexes Tests.

Tests for DB2 index introspection.
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
class TestDb2Indexes:
    """DB2 indexes tests."""

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
        log = ConsoleLog("db2_indexes", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_unique_index_introspection(self, db_container):
        """Test introspection of a unique index."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP INDEX {schema}.idx_unique_email")
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE {schema}.test_users (
                id INTEGER NOT NULL PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create unique index
            create_index = f"""
            CREATE UNIQUE INDEX {schema}.idx_unique_email ON {schema}.test_users(email)
            """
            provider.execute_statement(create_index)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect (DB2 is case-sensitive, use uppercase)
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            indexes = introspector.get_indexes(schema, "TEST_USERS")

            # Find our index
            test_index = None
            for idx in indexes:
                if idx.name.upper() == "IDX_UNIQUE_EMAIL":
                    test_index = idx
                    break

            assert (
                test_index is not None
            ), f"Index 'idx_unique_email' not found. Available indexes: {[idx.name for idx in indexes]}"
            # Check if index is unique (may be stored in different attribute)
            is_unique = getattr(test_index, "is_unique", None) or getattr(
                test_index, "unique", False
            )
            assert (
                is_unique is True or is_unique == "Y" or is_unique == "YES"
            ), f"Index should be unique, got: {is_unique}"

        finally:
            try:
                provider.execute_statement(f"DROP INDEX {schema}.idx_unique_email")
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_multi_column_index(self, db_container):
        """Test introspection of a multi-column index."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP INDEX {schema}.idx_name_email")
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table
            create_table = f"""
            CREATE TABLE {schema}.test_users (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create multi-column index
            create_index = f"""
            CREATE INDEX {schema}.idx_name_email ON {schema}.test_users(name, email)
            """
            provider.execute_statement(create_index)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect (DB2 is case-sensitive, use uppercase)
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            indexes = introspector.get_indexes(schema, "TEST_USERS")

            # Find our index
            test_index = None
            for idx in indexes:
                if idx.name.upper() == "IDX_NAME_EMAIL":
                    test_index = idx
                    break

            assert (
                test_index is not None
            ), f"Index 'idx_name_email' not found. Available indexes: {[idx.name for idx in indexes]}"
            # Check column names (may be in columns or column_names attribute)
            col_names = getattr(test_index, "column_names", None) or getattr(
                test_index, "columns", []
            )
            assert len(col_names) >= 2, f"Index should have at least 2 columns, found: {col_names}"

        finally:
            try:
                provider.execute_statement(f"DROP INDEX {schema}.idx_name_email")
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
