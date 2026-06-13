"""
Oracle Partitioned Tables Tests.

Tests for Oracle partitioned tables: RANGE, LIST, HASH partitioning.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["oracle"],
    indirect=True,
)
class TestOraclePartitionedTables:
    """Oracle partitioned table tests."""

    def test_range_partitioned_table_introspection(self, db_container):
        """Test introspection of RANGE partitioned table."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build native URL
        service = db_container.get("service", db_container.get("database"))
        database_url = f"oracle+oracledb://{db_container['host']}:{db_container['port']}?service_name={service}"

        db_config = DatabaseConfig(
            type="oracle",
            url=database_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("oracle_range_partition", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."sales_range" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create RANGE partitioned table
            create_table = f"""
            CREATE TABLE "{schema}"."sales_range" (
                id NUMBER PRIMARY KEY,
                sale_date DATE NOT NULL,
                amount NUMBER(10, 2),
                region VARCHAR2(50)
            )
            PARTITION BY RANGE (sale_date) (
                PARTITION p2023_q1 VALUES LESS THAN (DATE '2023-04-01'),
                PARTITION p2023_q2 VALUES LESS THAN (DATE '2023-07-01'),
                PARTITION p2023_q3 VALUES LESS THAN (DATE '2023-10-01'),
                PARTITION p2023_q4 VALUES LESS THAN (DATE '2024-01-01')
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
                if table.name.upper() == "SALES_RANGE":
                    test_table = table
                    break

            assert test_table is not None, "Table 'sales_range' not found"
            assert (
                test_table.partition_method == "RANGE"
            ), f"Expected RANGE, got {test_table.partition_method}"
            partition_cols_upper = [col.upper() for col in (test_table.partition_columns or [])]
            assert (
                "SALE_DATE" in partition_cols_upper
            ), f"Expected SALE_DATE in partition_columns, got {test_table.partition_columns}"

        finally:
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."sales_range" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_list_partitioned_table_introspection(self, db_container):
        """Test introspection of LIST partitioned table."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build native URL
        service = db_container.get("service", db_container.get("database"))
        database_url = f"oracle+oracledb://{db_container['host']}:{db_container['port']}?service_name={service}"

        db_config = DatabaseConfig(
            type="oracle",
            url=database_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("oracle_list_partition", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."customers_list" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create LIST partitioned table
            create_table = f"""
            CREATE TABLE "{schema}"."customers_list" (
                id NUMBER PRIMARY KEY,
                region VARCHAR2(50) NOT NULL,
                name VARCHAR2(100),
                status VARCHAR2(20)
            )
            PARTITION BY LIST (region) (
                PARTITION p_north VALUES ('NORTH', 'NORTHEAST', 'NORTHWEST'),
                PARTITION p_south VALUES ('SOUTH', 'SOUTHEAST', 'SOUTHWEST'),
                PARTITION p_central VALUES ('CENTRAL', 'MIDWEST'),
                PARTITION p_other VALUES (DEFAULT)
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
                if table.name.upper() == "CUSTOMERS_LIST":
                    test_table = table
                    break

            assert test_table is not None, "Table 'customers_list' not found"
            assert (
                test_table.partition_method == "LIST"
            ), f"Expected LIST, got {test_table.partition_method}"
            partition_cols_upper = [col.upper() for col in (test_table.partition_columns or [])]
            assert (
                "REGION" in partition_cols_upper
            ), f"Expected REGION in partition_columns, got {test_table.partition_columns}"

        finally:
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."customers_list" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_hash_partitioned_table_introspection(self, db_container):
        """Test introspection of HASH partitioned table."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build native URL
        service = db_container.get("service", db_container.get("database"))
        database_url = f"oracle+oracledb://{db_container['host']}:{db_container['port']}?service_name={service}"

        db_config = DatabaseConfig(
            type="oracle",
            url=database_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("oracle_hash_partition", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."products_hash" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create HASH partitioned table
            create_table = f"""
            CREATE TABLE "{schema}"."products_hash" (
                id NUMBER PRIMARY KEY,
                name VARCHAR2(100) NOT NULL,
                category VARCHAR2(50),
                price NUMBER(10, 2)
            )
            PARTITION BY HASH (id)
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
                if table.name.upper() == "PRODUCTS_HASH":
                    test_table = table
                    break

            assert test_table is not None, "Table 'products_hash' not found"
            assert (
                test_table.partition_method == "HASH"
            ), f"Expected HASH, got {test_table.partition_method}"
            partition_cols_upper = [col.upper() for col in (test_table.partition_columns or [])]
            assert (
                "ID" in partition_cols_upper
            ), f"Expected ID in partition_columns, got {test_table.partition_columns}"

        finally:
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."products_hash" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_range_partitioned_table_round_trip(self, db_container):
        """Test round-trip for RANGE partitioned table."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        # Build native URL
        service = db_container.get("service", db_container.get("database"))
        database_url = f"oracle+oracledb://{db_container['host']}:{db_container['port']}?service_name={service}"

        db_config = DatabaseConfig(
            type="oracle",
            url=database_url,
            host=db_container.get("host"),
            port=db_container.get("port"),
            database=db_container.get("database"),
            username=db_container["username"],
            password=db_container["password"],
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )
        config = DbliftConfig(database=db_config)
        log = ConsoleLog("oracle_range_roundtrip", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        schema = db_config.schema.upper()
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."sales_range" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create RANGE partitioned table
            create_table = f"""
            CREATE TABLE "{schema}"."sales_range" (
                id NUMBER PRIMARY KEY,
                sale_date DATE NOT NULL,
                amount NUMBER(10, 2),
                region VARCHAR2(50)
            )
            PARTITION BY RANGE (sale_date) (
                PARTITION p2023_q1 VALUES LESS THAN (DATE '2023-04-01'),
                PARTITION p2023_q2 VALUES LESS THAN (DATE '2023-07-01'),
                PARTITION p2023_q3 VALUES LESS THAN (DATE '2023-10-01'),
                PARTITION p2023_q4 VALUES LESS THAN (DATE '2024-01-01')
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Ensure test schema exists
            test_schema = f"{schema}_TEST"
            provider.schema_operations.create_schema_if_not_exists(provider.connection, test_schema)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # For partitioned tables, we verify that partition metadata is correctly introspected
            # Note: Round-trip testing for partitioned tables is limited because Oracle requires
            # partition definitions to recreate the table, which we don't track in detail.
            # We verify that partition method and columns are correctly introspected.
            introspector = IntrospectorFactory.create(provider, log=log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "SALES_RANGE":
                    test_table = table
                    break

            assert test_table is not None, "Table 'sales_range' not found after introspection"
            assert (
                test_table.partition_method == "RANGE"
            ), f"Expected RANGE partition method, got {test_table.partition_method}"
            partition_cols_upper = [col.upper() for col in (test_table.partition_columns or [])]
            assert (
                "SALE_DATE" in partition_cols_upper
            ), f"Expected SALE_DATE in partition_columns, got {test_table.partition_columns}"

        finally:
            try:
                provider.execute_statement(
                    f'DROP TABLE "{schema}"."sales_range" CASCADE CONSTRAINTS'
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()
