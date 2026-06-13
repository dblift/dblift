"""
MySQL Partitioning Tests.

Tests for MySQL table partitioning features: RANGE, LIST, HASH, KEY partitioning.
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
class TestMySQLPartitioning:
    """MySQL partitioning tests."""

    def test_range_partitioned_table_introspection(self, db_container):
        """Test introspection of a RANGE partitioned table."""
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
        log = ConsoleLog("mysql_partitioning", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`sales_by_year`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create RANGE partitioned table
            # Note: MySQL requires PRIMARY KEY to include all partitioning columns
            # Since we partition by YEAR(sale_date), we need a composite PK or use sale_date in PK
            create_table = f"""
            CREATE TABLE `{schema}`.`sales_by_year` (
                id INT AUTO_INCREMENT,
                sale_date DATE NOT NULL,
                amount DECIMAL(10, 2) NOT NULL,
                region VARCHAR(50) NOT NULL,
                PRIMARY KEY (id, sale_date)
            )
            PARTITION BY RANGE (YEAR(sale_date)) (
                PARTITION p2020 VALUES LESS THAN (2021),
                PARTITION p2021 VALUES LESS THAN (2022),
                PARTITION p2022 VALUES LESS THAN (2023),
                PARTITION p2023 VALUES LESS THAN (2024),
                PARTITION pmax VALUES LESS THAN MAXVALUE
            )
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
                if table.name.lower() == "sales_by_year":
                    test_table = table
                    break

            assert test_table is not None, "Table 'sales_by_year' not found"
            # Check if partitioning info is captured (if supported)
            # Note: Partitioning metadata may not be fully captured yet

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`sales_by_year`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_hash_partitioned_table_introspection(self, db_container):
        """Test introspection of a HASH partitioned table."""
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
        log = ConsoleLog("mysql_hash_partitioning", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users_by_id`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create HASH partitioned table
            create_table = f"""
            CREATE TABLE `{schema}`.`users_by_id` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                email VARCHAR(100) NOT NULL
            )
            PARTITION BY HASH(id)
            PARTITIONS 4
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
                if table.name.lower() == "users_by_id":
                    test_table = table
                    break

            assert test_table is not None, "Table 'users_by_id' not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`users_by_id`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_list_partitioned_table_introspection(self, db_container):
        """Test introspection of a LIST partitioned table."""
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
        log = ConsoleLog("mysql_list_partitioning", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`sales_by_region`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create LIST partitioned table
            create_table = f"""
            CREATE TABLE `{schema}`.`sales_by_region` (
                id INT AUTO_INCREMENT,
                region_code INT NOT NULL,
                sale_date DATE NOT NULL,
                amount DECIMAL(10, 2) NOT NULL,
                PRIMARY KEY (id, region_code)
            )
            PARTITION BY LIST (region_code) (
                PARTITION p_north VALUES IN (1, 2, 3),
                PARTITION p_south VALUES IN (4, 5, 6),
                PARTITION p_east VALUES IN (7, 8, 9),
                PARTITION p_west VALUES IN (10, 11, 12)
            )
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
                if table.name.lower() == "sales_by_region":
                    test_table = table
                    break

            assert test_table is not None, "Table 'sales_by_region' not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`sales_by_region`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_key_partitioned_table_introspection(self, db_container):
        """Test introspection of a KEY partitioned table."""
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
        log = ConsoleLog("mysql_key_partitioning", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`logs_by_id`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create KEY partitioned table
            create_table = f"""
            CREATE TABLE `{schema}`.`logs_by_id` (
                id INT AUTO_INCREMENT PRIMARY KEY,
                log_message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            PARTITION BY KEY(id)
            PARTITIONS 4
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
                if table.name.lower() == "logs_by_id":
                    test_table = table
                    break

            assert test_table is not None, "Table 'logs_by_id' not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS `{schema}`.`logs_by_id`")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
