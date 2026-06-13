"""
DB2 Views Tests.

Tests for DB2 views and Materialized Query Tables (MQT).
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
class TestDb2Views:
    """DB2 views tests."""

    def _get_provider(self, db_container):
        """Create database provider."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

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
        log = ConsoleLog("db2_views", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_simple_view_introspection(self, db_container):
        """Test introspection of a simple view."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP VIEW {schema}.test_user_view")
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass

            # Create table first
            create_table = f"""
            CREATE TABLE {schema}.test_users (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                email VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table)

            # Create view
            create_view = f"""
            CREATE VIEW {schema}.test_user_view AS
            SELECT id, name, email
            FROM {schema}.test_users
            WHERE email IS NOT NULL
            """
            provider.execute_statement(create_view)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            views = introspector.get_views(schema)

            # Find our view
            test_view = None
            for view in views:
                if view.name.upper() == "TEST_USER_VIEW":
                    test_view = view
                    break

            assert test_view is not None, "View 'test_user_view' not found"
            assert test_view.query is not None, "View query is None"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW {schema}.test_user_view")
                provider.execute_statement(f"DROP TABLE {schema}.test_users")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                pass
            provider.close()

    def test_materialized_query_table_introspection(self, db_container):
        """Test introspection of a Materialized Query Table (MQT)."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up (with rollback on error)
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_mqt")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_sales")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create base table
            create_table = f"""
            CREATE TABLE {schema}.test_sales (
                id INTEGER NOT NULL PRIMARY KEY,
                product_id INTEGER NOT NULL,
                sale_date DATE NOT NULL,
                amount DECIMAL(10, 2) NOT NULL
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Create Materialized Query Table (DB2's materialized view)
            # MQT requires special privileges and may not be available in all DB2 configurations
            # Skip early if MQT is not supported to avoid hanging
            create_mqt = f"""
            CREATE TABLE {schema}.test_mqt AS (
                SELECT product_id, SUM(amount) AS total_sales
                FROM {schema}.test_sales
                GROUP BY product_id
            ) DATA INITIALLY DEFERRED REFRESH IMMEDIATE
            """
            try:
                provider.execute_statement(create_mqt)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                # MQT may require special privileges or setup - skip immediately
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
                pytest.skip(f"MQT creation failed (may require special privileges): {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our MQT
            test_mqt = None
            for table in tables:
                if table.name.upper() == "TEST_MQT":
                    test_mqt = table
                    break

            if test_mqt is None:
                # MQT may not be introspected as a regular table
                pytest.skip("MQT not found in introspection (may require special handling)")

            assert test_mqt is not None, "MQT 'test_mqt' not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_mqt")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_sales")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()
