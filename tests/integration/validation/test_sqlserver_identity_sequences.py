"""
SQL Server Identity Columns and Sequences Tests.

Comprehensive tests for IDENTITY columns and SEQUENCE objects.
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
class TestSQLServerIdentitySequences:
    """SQL Server identity column and sequence tests."""

    def test_identity_column_introspection(self, db_container):
        """Test IDENTITY column introspection."""
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
        log = ConsoleLog("sqlserver_identity_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.users"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with IDENTITY column
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY IDENTITY(1,1),
                name NVARCHAR(100) NOT NULL,
                email NVARCHAR(255)
            )
            """

            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            assert len(tables) >= 1
            users_table = next((t for t in tables if t.name == "users"), None)
            assert users_table is not None

            # Find identity column
            id_col = next((c for c in users_table.columns if c.name == "id"), None)
            assert id_col is not None
            assert hasattr(id_col, "is_identity")
            assert id_col.is_identity is True

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.users")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_identity_column_with_seed_increment(self, db_container):
        """Test IDENTITY column with custom SEED and INCREMENT."""
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
        log = ConsoleLog("sqlserver_identity_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.orders"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with IDENTITY column (SEED=100, INCREMENT=10)
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY IDENTITY(100,10),
                order_date DATETIME NOT NULL,
                amount DECIMAL(10, 2) NOT NULL
            )
            """

            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            orders_table = next((t for t in tables if t.name == "orders"), None)
            assert orders_table is not None

            id_col = next((c for c in orders_table.columns if c.name == "id"), None)
            assert id_col is not None
            assert id_col.is_identity is True

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_sequence_introspection(self, db_container):
        """Test SEQUENCE object introspection (SQL Server 2012+)."""
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
        log = ConsoleLog("sqlserver_identity_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up if exists
            try:
                provider.execute_statement(f"DROP SEQUENCE IF EXISTS {schema}.user_id_seq")
            except Exception:
                pass

            # Create sequence
            create_sequence = f"""
            CREATE SEQUENCE {schema}.user_id_seq
            START WITH 1
            INCREMENT BY 1
            MINVALUE 1
            MAXVALUE 999999
            CYCLE
            """

            provider.execute_statement(create_sequence)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            sequences = introspector.get_sequences(schema)

            assert len(sequences) >= 1
            seq = next((s for s in sequences if s.name == "user_id_seq"), None)
            assert seq is not None

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP SEQUENCE IF EXISTS {schema}.user_id_seq")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_identity_round_trip(self, db_container):
        """Test that IDENTITY columns are preserved in round-trip."""
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
        log = ConsoleLog("sqlserver_identity_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            table_name = f"{schema}.products"

            # Clean up if exists
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with IDENTITY column
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY IDENTITY(1,1),
                name NVARCHAR(100) NOT NULL,
                price DECIMAL(10, 2) NOT NULL
            )
            """

            provider.execute_statement(create_table)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)

            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=schema + "_test",
                introspector=introspector,
                test_object_types=["tables"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('tables', {}).get('differences', [])}"
            )

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()
