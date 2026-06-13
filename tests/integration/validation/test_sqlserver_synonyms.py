"""
SQL Server Synonyms Tests.

Tests for SQL Server synonyms: introspection and SQL generation.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["sqlserver"],
    indirect=True,
)
class TestSQLServerSynonyms:
    """SQL Server synonyms tests."""

    def _get_provider(self, db_container):
        """Create database provider."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        sqlalchemy_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"

        db_config = DatabaseConfig(
            type=db_type,
            url=sqlalchemy_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=schema,
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("sqlserver_synonyms", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_synonym_introspection(self, db_container):
        """Test introspection of a synonym."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP SYNONYM IF EXISTS [{schema}].[syn_users]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[users]")
            except Exception:
                pass

            # Create base table
            create_table = f"""
            CREATE TABLE [{schema}].[users] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                username NVARCHAR(50) NOT NULL,
                email NVARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create synonym
            create_synonym = f"""
            CREATE SYNONYM [{schema}].[syn_users] FOR [{schema}].[users]
            """
            provider.execute_statement(create_synonym)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            # Check if get_synonyms method exists
            if not hasattr(introspector, "get_synonyms"):
                pytest.skip("get_synonyms method not available for SQL Server")
            synonyms = introspector.get_synonyms(schema)

            # Find our synonym
            test_synonym = None
            for syn in synonyms:
                if syn.name.lower() == "syn_users":
                    test_synonym = syn
                    break

            assert test_synonym is not None, "Synonym 'syn_users' not found"
            assert test_synonym.target_full_name is not None, "Synonym target is None"

        finally:
            try:
                provider.execute_statement(f"DROP SYNONYM IF EXISTS [{schema}].[syn_users]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[users]")
            except Exception:
                pass
            provider.close()

    def test_synonym_sql_generation(self, db_container):
        """Test SQL generation for synonyms."""
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP SYNONYM IF EXISTS [{schema}].[syn_products]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[products]")
            except Exception:
                pass

            # Create base table
            create_table = f"""
            CREATE TABLE [{schema}].[products] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL,
                price DECIMAL(10, 2) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create synonym
            create_synonym = f"""
            CREATE SYNONYM [{schema}].[syn_products] FOR [{schema}].[products]
            """
            provider.execute_statement(create_synonym)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            # Check if get_synonyms method exists
            if not hasattr(introspector, "get_synonyms"):
                pytest.skip("get_synonyms method not available for SQL Server")
            synonyms = introspector.get_synonyms(schema)

            # Find our synonym
            test_synonym = None
            for syn in synonyms:
                if syn.name.lower() == "syn_products":
                    test_synonym = syn
                    break

            assert test_synonym is not None, "Synonym 'syn_products' not found"

            # Generate SQL
            generator = SqlGeneratorFactory.create("sqlserver")
            sql = generator.generate_create_statement(test_synonym)

            # Check that SQL is generated
            assert sql is not None and len(sql) > 0, "Generated SQL is empty"
            assert "SYNONYM" in sql.upper(), f"SYNONYM not found in generated SQL: {sql[:200]}"

        finally:
            try:
                provider.execute_statement(f"DROP SYNONYM IF EXISTS [{schema}].[syn_products]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[products]")
            except Exception:
                pass
            provider.close()
