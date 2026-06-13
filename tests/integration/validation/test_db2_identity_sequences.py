"""
DB2 Identity Columns and Sequences Tests.

Tests for DB2 identity columns (GENERATED ALWAYS AS IDENTITY) and sequences.
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
class TestDb2IdentitySequences:
    """DB2 identity columns and sequences tests."""

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
        log = ConsoleLog("db2_identity", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_identity_column_introspection(self, db_container):
        """Test introspection of a table with identity column."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_identity")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with identity column
            create_table = f"""
            CREATE TABLE {schema}.test_identity (
                id INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1) PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_IDENTITY":
                    test_table = table
                    break

            assert test_table is not None, "Table 'test_identity' not found"

            # Check for identity column
            id_column = next((col for col in test_table.columns if col.name.upper() == "ID"), None)
            assert id_column is not None, "id column not found"
            # Check if identity is detected (may be via is_identity attribute)
            assert (
                getattr(id_column, "is_identity", False)
                or "IDENTITY" in str(id_column.data_type).upper()
            ), "id column should be an identity column"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_identity")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_sequence_introspection(self, db_container):
        """Test introspection of a sequence."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP SEQUENCE {schema}.test_seq")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create sequence
            create_sequence = f"""
            CREATE SEQUENCE {schema}.test_seq
            START WITH 1
            INCREMENT BY 1
            NO MAXVALUE
            NO CYCLE
            """
            provider.execute_statement(create_sequence)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            sequences = introspector.get_sequences(schema)

            # Find our sequence
            test_sequence = None
            for seq in sequences:
                if seq.name.upper() == "TEST_SEQ":
                    test_sequence = seq
                    break

            assert test_sequence is not None, "Sequence 'test_seq' not found"

        finally:
            try:
                provider.execute_statement(f"DROP SEQUENCE {schema}.test_seq")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
