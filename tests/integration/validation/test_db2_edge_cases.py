"""
DB2 Edge Cases and Advanced Scenarios Tests.

Tests for edge cases, complex scenarios, and advanced DB2 features.
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
class TestDb2EdgeCases:
    """DB2 edge cases and advanced scenarios tests."""

    def _get_provider(self, db_container):
        """Create database provider."""
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")
        from config import DbliftConfig
        from config.database_config import DatabaseConfig
        from db.provider_registry import ProviderRegistry

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
        log = ConsoleLog("db2_edge_cases", enable_debug=False)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_composite_primary_key(self, db_container):
        """Test table with composite primary key."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_composite_pk")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create table with composite primary key
            create_table = f"""
            CREATE TABLE {schema}.test_composite_pk (
                part1 INTEGER NOT NULL,
                part2 INTEGER NOT NULL,
                data VARCHAR(100) NOT NULL,
                PRIMARY KEY (part1, part2)
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_COMPOSITE_PK":
                    test_table = table
                    break

            assert test_table is not None, "Table not found"

            # Check for composite primary key
            pk_constraints = [
                c for c in test_table.constraints if c.constraint_type.value == "PRIMARY KEY"
            ]
            assert len(pk_constraints) >= 1, "Expected PRIMARY KEY constraint"
            pk_constraint = pk_constraints[0]
            assert (
                len(pk_constraint.column_names) >= 2
            ), "Expected composite primary key with at least 2 columns"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_composite_pk")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_multiple_foreign_keys(self, db_container):
        """Test table with multiple foreign keys."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_multi_fk")
                provider.execute_statement(f"DROP TABLE {schema}.test_table2")
                provider.execute_statement(f"DROP TABLE {schema}.test_table1")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create parent tables
            create_table1 = f"""
            CREATE TABLE {schema}.test_table1 (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_table1)

            create_table2 = f"""
            CREATE TABLE {schema}.test_table2 (
                id INTEGER NOT NULL PRIMARY KEY,
                code VARCHAR(50) NOT NULL
            )
            """
            provider.execute_statement(create_table2)

            # Create child table with multiple foreign keys
            create_multi_fk = f"""
            CREATE TABLE {schema}.test_multi_fk (
                id INTEGER NOT NULL PRIMARY KEY,
                table1_id INTEGER NOT NULL,
                table2_id INTEGER NOT NULL,
                FOREIGN KEY (table1_id) REFERENCES {schema}.test_table1(id),
                FOREIGN KEY (table2_id) REFERENCES {schema}.test_table2(id)
            )
            """
            provider.execute_statement(create_multi_fk)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_MULTI_FK":
                    test_table = table
                    break

            assert test_table is not None, "Table not found"

            # Check for multiple foreign keys
            fk_constraints = [
                c for c in test_table.constraints if c.constraint_type.value == "FOREIGN KEY"
            ]
            assert (
                len(fk_constraints) >= 2
            ), f"Expected at least 2 FOREIGN KEY constraints, found: {len(fk_constraints)}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_multi_fk")
                provider.execute_statement(f"DROP TABLE {schema}.test_table2")
                provider.execute_statement(f"DROP TABLE {schema}.test_table1")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_complex_check_constraint(self, db_container):
        """Test table with complex CHECK constraint."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_complex_check")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create table with complex CHECK constraint
            create_table = f"""
            CREATE TABLE {schema}.test_complex_check (
                id INTEGER NOT NULL PRIMARY KEY,
                price DECIMAL(10, 2) NOT NULL,
                discount DECIMAL(10, 2) NOT NULL,
                final_price DECIMAL(10, 2) NOT NULL,
                CHECK (price > 0 AND discount >= 0 AND discount <= price AND final_price = price - discount)
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_COMPLEX_CHECK":
                    test_table = table
                    break

            assert test_table is not None, "Table not found"

            # Check for CHECK constraint
            check_constraints = [
                c for c in test_table.constraints if c.constraint_type.value == "CHECK"
            ]
            assert len(check_constraints) >= 1, "Expected at least 1 CHECK constraint"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_complex_check")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_default_with_function(self, db_container):
        """Test column with DEFAULT using function."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_default_func")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create table with DEFAULT using function
            create_table = f"""
            CREATE TABLE {schema}.test_default_func (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_DEFAULT_FUNC":
                    test_table = table
                    break

            assert test_table is not None, "Table not found"

            # Check for columns with DEFAULT
            created_at_col = next(
                (col for col in test_table.columns if col.name.upper() == "CREATED_AT"), None
            )
            assert created_at_col is not None, "created_at column not found"
            assert (
                created_at_col.default_value is not None
            ), "created_at should have a default value"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_default_func")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_view_with_join(self, db_container):
        """Test view with JOIN."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP VIEW {schema}.test_view_join")
                provider.execute_statement(f"DROP TABLE {schema}.test_orders_v")
                provider.execute_statement(f"DROP TABLE {schema}.test_customers_v")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create tables
            create_customers = f"""
            CREATE TABLE {schema}.test_customers_v (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL
            )
            """
            provider.execute_statement(create_customers)

            create_orders = f"""
            CREATE TABLE {schema}.test_orders_v (
                id INTEGER NOT NULL PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_date DATE NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES {schema}.test_customers_v(id)
            )
            """
            provider.execute_statement(create_orders)

            # Create view with JOIN
            create_view = f"""
            CREATE VIEW {schema}.test_view_join AS
            SELECT 
                o.id AS order_id,
                c.name AS customer_name,
                o.order_date
            FROM {schema}.test_orders_v o
            INNER JOIN {schema}.test_customers_v c ON o.customer_id = c.id
            """
            provider.execute_statement(create_view)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            views = introspector.get_views(schema)

            test_view = None
            for view in views:
                if view.name.upper() == "TEST_VIEW_JOIN":
                    test_view = view
                    break

            assert test_view is not None, "View not found"
            assert test_view.query is not None, "View query is None"
            assert "JOIN" in test_view.query.upper(), "View should contain JOIN"

        finally:
            try:
                provider.execute_statement(f"DROP VIEW {schema}.test_view_join")
                provider.execute_statement(f"DROP TABLE {schema}.test_orders_v")
                provider.execute_statement(f"DROP TABLE {schema}.test_customers_v")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_sequence_with_options(self, db_container):
        """Test sequence with custom options."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP SEQUENCE {schema}.test_seq_options")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create sequence with options
            create_sequence = f"""
            CREATE SEQUENCE {schema}.test_seq_options
            START WITH 100
            INCREMENT BY 5
            MAXVALUE 1000
            MINVALUE 10
            CYCLE
            """
            provider.execute_statement(create_sequence)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            sequences = introspector.get_sequences(schema)

            test_sequence = None
            for seq in sequences:
                if seq.name.upper() == "TEST_SEQ_OPTIONS":
                    test_sequence = seq
                    break

            assert test_sequence is not None, "Sequence not found"

        finally:
            try:
                provider.execute_statement(f"DROP SEQUENCE {schema}.test_seq_options")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_unique_constraint_multi_column(self, db_container):
        """Test multi-column UNIQUE constraint."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_unique_multi")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create table with multi-column UNIQUE constraint
            create_table = f"""
            CREATE TABLE {schema}.test_unique_multi (
                id INTEGER NOT NULL PRIMARY KEY,
                code VARCHAR(50) NOT NULL,
                version INTEGER NOT NULL,
                UNIQUE (code, version)
            )
            """
            provider.execute_statement(create_table)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_UNIQUE_MULTI":
                    test_table = table
                    break

            assert test_table is not None, "Table not found"

            # Check for UNIQUE constraint
            unique_constraints = [
                c for c in test_table.constraints if c.constraint_type.value == "UNIQUE"
            ]
            assert len(unique_constraints) >= 1, "Expected at least 1 UNIQUE constraint"
            unique_constraint = unique_constraints[0]
            assert (
                len(unique_constraint.column_names) >= 2
            ), "Expected multi-column UNIQUE constraint"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_unique_multi")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()
