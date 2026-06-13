"""
SQL Server Index Tests.

Comprehensive tests for filtered indexes and included columns.
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
class TestSQLServerIndexes:
    """SQL Server index tests."""

    def test_filtered_index_introspection(self, db_container):
        """Test filtered index with WHERE clause."""
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
        log = ConsoleLog("sqlserver_index_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema
            table_name = f"{schema}.orders"

            # Clean up if exists
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS {schema}.idx_active_orders ON {table_name}"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table and filtered index
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                status NVARCHAR(50) NOT NULL,
                order_date DATETIME NOT NULL,
                amount DECIMAL(10, 2) NOT NULL
            )
            """
            create_index = f"""
            CREATE INDEX idx_active_orders ON {table_name}(order_date)
            WHERE status = 'ACTIVE'
            """

            provider.execute_statement(create_table)
            provider.execute_statement(create_index)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            indexes = introspector.get_indexes(schema, "orders")

            assert len(indexes) >= 1
            filtered_idx = next((i for i in indexes if i.name == "idx_active_orders"), None)
            assert filtered_idx is not None
            assert hasattr(filtered_idx, "condition")
            assert filtered_idx.condition is not None
            # SQL Server returns filter conditions with brackets, normalize for comparison
            condition_upper = filtered_idx.condition.upper().replace("[", "").replace("]", "")
            assert "STATUS" in condition_upper and "ACTIVE" in condition_upper

        finally:
            try:
                schema = db_config.schema
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.orders")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.products")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.employees")
                provider.execute_statement(f"DROP TABLE IF EXISTS {schema}.customers")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_included_columns_index(self, db_container):
        """Test index with included columns."""
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
        log = ConsoleLog("sqlserver_index_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema
            table_name = f"{schema}.products"

            # Clean up if exists
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS {schema}.idx_category ON {table_name}"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table and index with included columns
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                category_id INT NOT NULL,
                name NVARCHAR(100) NOT NULL,
                price DECIMAL(10, 2) NOT NULL,
                description NVARCHAR(MAX)
            )
            """
            create_index = f"""
            CREATE INDEX idx_category ON {table_name}(category_id)
            INCLUDE (name, price)
            """

            provider.execute_statement(create_table)
            provider.execute_statement(create_index)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            indexes = introspector.get_indexes(schema, "products")

            assert len(indexes) >= 1
            idx = next((i for i in indexes if i.name == "idx_category"), None)
            assert idx is not None
            assert hasattr(idx, "include_columns")
            assert idx.include_columns is not None
            assert len(idx.include_columns) == 2
            # SQL Server returns column names in uppercase, normalize for comparison
            include_cols_upper = [c.upper() for c in idx.include_columns]
            assert "NAME" in include_cols_upper
            assert "PRICE" in include_cols_upper

        finally:
            try:
                provider.execute_statement("DROP TABLE IF EXISTS products")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_filtered_index_with_included_columns(self, db_container):
        """Test filtered index with included columns."""
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
        log = ConsoleLog("sqlserver_index_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema
            table_name = f"{schema}.employees"

            # Clean up if exists
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS {schema}.idx_active_dept ON {table_name}"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table and complex index
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                department_id INT NOT NULL,
                status NVARCHAR(50) NOT NULL,
                salary DECIMAL(10, 2) NOT NULL,
                hire_date DATETIME NOT NULL
            )
            """
            create_index = f"""
            CREATE INDEX idx_active_dept ON {table_name}(department_id)
            INCLUDE (salary, hire_date)
            WHERE status = 'ACTIVE'
            """

            provider.execute_statement(create_table)
            provider.execute_statement(create_index)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=log)
            indexes = introspector.get_indexes(schema, "employees")

            idx = next((i for i in indexes if i.name == "idx_active_dept"), None)
            assert idx is not None
            assert hasattr(idx, "condition")
            assert idx.condition is not None
            assert hasattr(idx, "include_columns")
            assert len(idx.include_columns) == 2

        finally:
            try:
                provider.execute_statement("DROP TABLE IF EXISTS employees")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()

    def test_index_round_trip(self, db_container):
        """Test that indexes are preserved in round-trip."""
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
        log = ConsoleLog("sqlserver_index_test", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()

        # Ensure schema exists
        schema = db_config.schema
        provider.create_schema_if_not_exists(schema)

        try:
            schema = db_config.schema
            table_name = f"{schema}.customers"

            # Clean up if exists
            try:
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS {schema}.idx_email ON {table_name}"
                )
                provider.execute_statement(
                    f"DROP INDEX IF EXISTS {schema}.idx_active_customers ON {table_name}"
                )
                provider.execute_statement(f"DROP TABLE IF EXISTS {table_name}")
            except Exception:
                pass

            # Create table with multiple indexes
            create_table = f"""
            CREATE TABLE {table_name} (
                id INT PRIMARY KEY,
                email NVARCHAR(255) NOT NULL,
                status NVARCHAR(50) NOT NULL,
                created_date DATETIME NOT NULL,
                last_login DATETIME
            )
            """
            create_indexes = [
                f"""
                CREATE INDEX idx_email ON {table_name}(email)
                """,
                f"""
                CREATE INDEX idx_active_customers ON {table_name}(created_date)
                INCLUDE (last_login)
                WHERE status = 'ACTIVE'
                """,
            ]

            provider.execute_statement(create_table)
            for idx_sql in create_indexes:
                provider.execute_statement(idx_sql)

            # Run round-trip test
            introspector = IntrospectorFactory.create(provider, log=log)

            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=db_config.schema,
                test_schema=db_config.schema + "_test",
                introspector=introspector,
                test_object_types=["tables", "indexes"],
            )

            results = tester.run_round_trip_test()

            assert results["success"], (
                f"Round-trip failed. Errors: {results.get('errors', [])}, "
                f"Differences: {results.get('indexes', {}).get('differences', [])}"
            )

        finally:
            try:
                provider.execute_statement("DROP TABLE IF EXISTS customers")
            except Exception:
                pass
            if hasattr(provider, "close"):
                provider.close()
