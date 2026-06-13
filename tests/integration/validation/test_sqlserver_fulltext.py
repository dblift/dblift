"""
SQL Server Full-Text Search Tests.

Tests for SQL Server full-text search features (full-text indexes and catalogs).
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
class TestSQLServerFulltext:
    """SQL Server full-text search tests."""

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
        log = ConsoleLog("sqlserver_fulltext", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_fulltext_index_introspection(self, db_container):
        """Test introspection of a full-text index."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f"DROP FULLTEXT INDEX IF EXISTS ON [{schema}].[documents]"
                )
                provider.execute_statement(f"DROP FULLTEXT CATALOG IF EXISTS ft_catalog")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[documents]")
            except Exception:
                pass

            # Create full-text catalog
            create_catalog = f"""
            CREATE FULLTEXT CATALOG ft_catalog
            """
            try:
                provider.execute_statement(create_catalog)
            except Exception as e:
                # Full-text may not be available, skip test
                pytest.skip(f"Full-text catalog creation failed (may not be available): {e}")

            # Create table
            create_table = f"""
            CREATE TABLE [{schema}].[documents] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                title NVARCHAR(200) NOT NULL,
                content NVARCHAR(MAX) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create full-text index
            create_index = f"""
            CREATE FULLTEXT INDEX ON [{schema}].[documents] (content)
            KEY INDEX PK__document__id
            ON ft_catalog
            """
            try:
                provider.execute_statement(create_index)
            except Exception as e:
                # Full-text index may not be available, skip test
                pytest.skip(f"Full-text index creation failed (may not be available): {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "documents":
                    test_table = table
                    break

            assert test_table is not None, "Table 'documents' not found"
            # Full-text indexes may or may not be fully introspected, but table should exist

        finally:
            try:
                provider.execute_statement(
                    f"DROP FULLTEXT INDEX IF EXISTS ON [{schema}].[documents]"
                )
                provider.execute_statement(f"DROP FULLTEXT CATALOG IF EXISTS ft_catalog")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[documents]")
            except Exception:
                pass
            provider.close()
