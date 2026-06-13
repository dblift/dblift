"""
DB2 Advanced Features Tests.

Tests for advanced DB2 features: partitioning, compression, XML, JSON, etc.
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
class TestDb2AdvancedFeatures:
    """DB2 advanced features tests."""

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
        log = ConsoleLog("db2_advanced", enable_debug=True)
        provider = ProviderRegistry.create_provider(config, log)
        provider.create_connection()
        return provider, db_config.schema

    def test_table_compression(self, db_container):
        """Test table with compression."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_compressed")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create table with compression
            create_table = f"""
            CREATE TABLE {schema}.test_compressed (
                id INTEGER NOT NULL PRIMARY KEY,
                data VARCHAR(1000) NOT NULL
            ) COMPRESS YES
            """
            try:
                provider.execute_statement(create_table)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                pytest.skip(f"Compression not available: {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_COMPRESSED":
                    test_table = table
                    break

            assert test_table is not None, "Table 'test_compressed' not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_compressed")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_xml_data_type(self, db_container):
        """Test XML data type."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_xml")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create table with XML column
            create_table = f"""
            CREATE TABLE {schema}.test_xml (
                id INTEGER NOT NULL PRIMARY KEY,
                xml_data XML
            )
            """
            try:
                provider.execute_statement(create_table)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                pytest.skip(f"XML data type not available: {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_XML":
                    test_table = table
                    break

            assert test_table is not None, "Table 'test_xml' not found"

            # Check for XML column
            xml_column = next(
                (col for col in test_table.columns if col.name.upper() == "XML_DATA"), None
            )
            assert xml_column is not None, "xml_data column not found"
            # XML type may be normalized, check if it contains XML
            assert (
                "XML" in xml_column.data_type.upper()
            ), f"Expected XML type, got: {xml_column.data_type}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_xml")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_json_data_type(self, db_container):
        """Test JSON data type (DB2 10.5+)."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_json")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create table with JSON column (DB2 10.5+)
            create_table = f"""
            CREATE TABLE {schema}.test_json (
                id INTEGER NOT NULL PRIMARY KEY,
                json_data JSON
            )
            """
            try:
                provider.execute_statement(create_table)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                pytest.skip(f"JSON data type not available (requires DB2 10.5+): {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_JSON":
                    test_table = table
                    break

            assert test_table is not None, "Table 'test_json' not found"

            # Check for JSON column
            json_column = next(
                (col for col in test_table.columns if col.name.upper() == "JSON_DATA"), None
            )
            assert json_column is not None, "json_data column not found"
            # JSON type may be normalized
            assert (
                "JSON" in json_column.data_type.upper()
            ), f"Expected JSON type, got: {json_column.data_type}"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_json")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_partitioned_table(self, db_container):
        """Test partitioned table (range partitioning)."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_partitioned")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create partitioned table
            create_table = f"""
            CREATE TABLE {schema}.test_partitioned (
                id INTEGER NOT NULL,
                sale_date DATE NOT NULL,
                amount DECIMAL(10, 2) NOT NULL,
                PRIMARY KEY (id, sale_date)
            )
            PARTITION BY RANGE(sale_date) (
                PARTITION p2023 STARTING FROM ('2023-01-01') ENDING ('2023-12-31'),
                PARTITION p2024 STARTING FROM ('2024-01-01') ENDING ('2024-12-31')
            )
            """
            try:
                provider.execute_statement(create_table)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                pytest.skip(f"Partitioning not available: {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_PARTITIONED":
                    test_table = table
                    break

            assert test_table is not None, "Table 'test_partitioned' not found"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_partitioned")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()

    def test_generated_column(self, db_container):
        """Test generated column (GENERATED ALWAYS AS)."""
        provider, schema = self._get_provider(db_container)
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if not provider.connection.getAutoCommit():
            provider.connection.commit()

        try:
            # Clean up
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_generated")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()

            # Create table with generated column
            create_table = f"""
            CREATE TABLE {schema}.test_generated (
                id INTEGER NOT NULL PRIMARY KEY,
                price DECIMAL(10, 2) NOT NULL,
                quantity INTEGER NOT NULL,
                total DECIMAL(10, 2) GENERATED ALWAYS AS (price * quantity)
            )
            """
            try:
                provider.execute_statement(create_table)
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception as e:
                pytest.skip(f"Generated columns not available: {e}")

            # Introspect
            introspector = IntrospectorFactory.create(provider, log=provider.log)
            tables = introspector.get_tables(schema)

            # Find our table
            test_table = None
            for table in tables:
                if table.name.upper() == "TEST_GENERATED":
                    test_table = table
                    break

            assert test_table is not None, "Table 'test_generated' not found"

            # Check for generated column
            total_column = next(
                (col for col in test_table.columns if col.name.upper() == "TOTAL"), None
            )
            assert total_column is not None, "total column not found"
            # Check if it's marked as computed/generated
            is_computed = (
                getattr(total_column, "is_computed", False)
                or getattr(total_column, "computed_expression", None) is not None
            )
            assert is_computed, "total column should be a generated/computed column"

        finally:
            try:
                provider.execute_statement(f"DROP TABLE {schema}.test_generated")
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            except Exception:
                if not provider.connection.getAutoCommit():
                    provider.connection.rollback()
            provider.close()
