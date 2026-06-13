"""
MySQL Full-Text Index Tests.

Tests for MySQL FULLTEXT indexes: introspection and SQL generation.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["mysql"],
    indirect=True,
)
class TestMySQLFulltextIndexes:
    """MySQL full-text index tests."""

    def test_fulltext_index_introspection(self, db_container):
        """Test introspection of a FULLTEXT index."""
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
        log = ConsoleLog("mysql_fulltext", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`articles`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with FULLTEXT index
            create_table = f"""
            CREATE TABLE `{schema}`.`articles` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                content TEXT NOT NULL,
                FULLTEXT KEY `idx_fulltext_title_content` (title, content)
            ) ENGINE=InnoDB
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            indexes = introspector.get_indexes(schema, "articles")

            # Find our FULLTEXT index
            fulltext_index = None
            for idx in indexes:
                if idx.name.lower() == "idx_fulltext_title_content":
                    fulltext_index = idx
                    break

            assert (
                fulltext_index is not None
            ), "FULLTEXT index 'idx_fulltext_title_content' not found"
            # Check index type (if available)
            if hasattr(fulltext_index, "type"):
                assert (
                    fulltext_index.type.upper() == "FULLTEXT"
                ), f"Expected FULLTEXT, got {fulltext_index.type}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`articles`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_fulltext_index_sql_generation(self, db_container):
        """Test SQL generation for FULLTEXT indexes."""
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
        log = ConsoleLog("mysql_fulltext_sql", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`documents`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table with FULLTEXT index
            create_table = f"""
            CREATE TABLE `{schema}`.`documents` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                body TEXT NOT NULL,
                FULLTEXT KEY `ft_idx_body` (body)
            ) ENGINE=InnoDB
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            indexes = introspector.get_indexes(schema, "documents")

            # Find our FULLTEXT index
            fulltext_index = None
            for idx in indexes:
                if idx.name.lower() == "ft_idx_body":
                    fulltext_index = idx
                    break

            assert fulltext_index is not None, "FULLTEXT index 'ft_idx_body' not found"

            # Generate SQL
            generator = SqlGeneratorFactory.create("mysql")
            sql = generator.generate_create_statement(fulltext_index)

            # Check that FULLTEXT is in the generated SQL
            assert "FULLTEXT" in sql.upper(), f"FULLTEXT not found in generated SQL: {sql}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`documents`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
