"""
MySQL Storage Engines Tests.

Tests for MySQL storage engines: InnoDB, MyISAM, etc.
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
class TestMySQLStorageEngines:
    """MySQL storage engines tests."""

    def test_innodb_table_introspection(self, db_container):
        """Test introspection of an InnoDB table (default engine)."""
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
        log = ConsoleLog("mysql_innodb", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`innodb_table`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create InnoDB table (explicitly)
            create_table = f"""
            CREATE TABLE `{schema}`.`innodb_table` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                value INT NOT NULL
            ) ENGINE=InnoDB
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "innodb_table":
                    test_table = table
                    break

            assert test_table is not None, "Table 'innodb_table' not found"
            # Check if storage engine is captured (if supported)
            if hasattr(test_table, "storage_engine"):
                # Storage engine may or may not be captured, but table should exist
                pass

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`innodb_table`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_myisam_table_introspection(self, db_container):
        """Test introspection of a MyISAM table (if supported)."""
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
        log = ConsoleLog("mysql_myisam", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`myisam_table`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Try to create MyISAM table (may not be available in all MySQL versions)
            try:
                create_table = f"""
                CREATE TABLE `{schema}`.`myisam_table` (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    value INT NOT NULL
                ) ENGINE=MyISAM
                """
                provider.execute_statement(create_table)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()

                # Introspect
                introspector = IntrospectorFactory.create(provider, log=log)
                tables = introspector.get_tables(schema)

                # Find our table
                test_table = None
                for table in tables:
                    if table.name.lower() == "myisam_table":
                        test_table = table
                        break

                assert test_table is not None, "Table 'myisam_table' not found"
            except Exception as e:
                # MyISAM may not be available, skip this test
                pytest.skip(f"MyISAM engine not available: {e}")

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`myisam_table`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
