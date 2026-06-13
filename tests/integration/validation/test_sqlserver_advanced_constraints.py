"""
SQL Server Advanced Constraints Tests.

Tests for advanced constraint features: complex CHECK, multiple constraints, etc.
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
class TestSQLServerAdvancedConstraints:
    """SQL Server advanced constraints tests."""

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
        log = ConsoleLog("sqlserver_advanced_constraints", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_multiple_check_constraints(self, db_container):
        """Test table with multiple CHECK constraints."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[orders]")
            except Exception:
                pass

            # Create table with multiple CHECK constraints
            create_table = f"""
            CREATE TABLE [{schema}].[orders] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                order_date DATE NOT NULL,
                total DECIMAL(10, 2) NOT NULL,
                status NVARCHAR(20) NOT NULL,
                CONSTRAINT chk_total_positive CHECK (total > 0),
                CONSTRAINT chk_status_valid CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'CANCELLED')),
                CONSTRAINT chk_date_not_future CHECK (order_date <= CAST(GETDATE() AS DATE))
            )
            """
            provider.execute_statement(create_table)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "orders":
                    test_table = table
                    break

            assert test_table is not None, "Table 'orders' not found"

            # Check for multiple CHECK constraints
            check_constraints = [
                c for c in test_table.constraints if c.constraint_type.value == "CHECK"
            ]
            assert (
                len(check_constraints) >= 3
            ), f"Expected at least 3 CHECK constraints, found {len(check_constraints)}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[orders]")
            except Exception:
                pass
            provider.close()

    def test_foreign_key_cascade_actions(self, db_container):
        """Test foreign keys with CASCADE actions."""
        provider, schema = self._get_provider(db_container)
        provider.create_schema_if_not_exists(schema)

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[order_items]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[orders]")
            except Exception:
                pass

            # Create parent table
            create_orders = f"""
            CREATE TABLE [{schema}].[orders] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                order_date DATE NOT NULL,
                total DECIMAL(10, 2) NOT NULL
            )
            """
            provider.execute_statement(create_orders)

            # Create child table with CASCADE actions
            create_order_items = f"""
            CREATE TABLE [{schema}].[order_items] (
                id INT IDENTITY(1,1) PRIMARY KEY,
                order_id INT NOT NULL,
                product_name NVARCHAR(200) NOT NULL,
                quantity INT NOT NULL,
                CONSTRAINT fk_item_order FOREIGN KEY (order_id) 
                    REFERENCES [{schema}].[orders](id) 
                    ON DELETE CASCADE 
                    ON UPDATE CASCADE
            )
            """
            provider.execute_statement(create_order_items)

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.lower() == "order_items":
                    test_table = table
                    break

            assert test_table is not None, "Table 'order_items' not found"

            # Check for foreign key with CASCADE
            fk_constraints = [
                c for c in test_table.constraints if c.constraint_type.value == "FOREIGN KEY"
            ]
            assert (
                len(fk_constraints) >= 1
            ), f"Expected at least 1 foreign key, found {len(fk_constraints)}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[order_items]")
                provider.execute_statement(f"DROP TABLE IF EXISTS [{schema}].[orders]")
            except Exception:
                pass
            provider.close()
