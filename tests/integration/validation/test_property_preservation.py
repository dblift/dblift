"""
Property-level validation tests.

Tests that individual properties are preserved during round-trip operations.
"""

from typing import Any, Dict

import pytest

from config import DbliftConfig
from config.database_config import DatabaseConfig
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester
from db.provider_registry import ProviderRegistry
from tests.integration.helpers.database_helper import execute_sql


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "mysql", "sqlserver", "oracle", "db2"],
    indirect=True,
)
class TestPropertyPreservation:
    """Tests for property preservation during round-trip."""

    def _get_provider(self, db_container):
        """Create database provider."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Build native URL
        if db_type == "sqlserver":
            database_url = f"mssql+pymssql://{db_container['host']}:{db_container['port']}/{db_container['database']}?encrypt=false"
        elif db_type == "oracle":
            service = db_container.get("service", db_container.get("database"))
            database_url = f"oracle+oracledb://{db_container['host']}:{db_container['port']}?service_name={service}"
        elif db_type == "mysql":
            database_url = f"mysql+pymysql://{db_container['host']}:{db_container['port']}/{db_container['database']}"
        elif db_type == "db2":
            database_url = f"ibm_db_sa://{db_container['host']}:{db_container['port']}/{db_container['database']}"
        elif db_type == "postgresql":
            database_url = f"postgresql+psycopg://{db_container['host']}:{db_container['port']}/{db_container['database']}"
        else:
            database_url = db_container.get("url")

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
        log = ConsoleLog("property_test", enable_debug=False)
        return ProviderRegistry.create_provider(config, log=log)

    def test_data_type_preservation(self, db_container):
        """Test that all data types are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")
        db_type = db_container["type"]

        # For Oracle, convert schema to uppercase (Oracle convention)
        if db_type == "oracle":
            schema = schema.upper()

        # Ensure schema exists
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Clean up any existing table before creating new one
        table_name = "DATA_TYPES_TEST" if db_type in ("oracle", "db2") else "data_types_test"
        if hasattr(provider, "_drop_table_if_exists"):
            provider._drop_table_if_exists(provider, db_type, schema, table_name)
        else:
            # Fallback: try to drop directly
            try:
                if db_type == "oracle":
                    clean_schema = schema.replace('"', "").strip().upper()
                    clean_table = table_name.replace('"', "").strip().upper()
                    qualified_table = f"{clean_schema}.{clean_table}"
                    drop_sql = f"DROP TABLE {qualified_table} CASCADE CONSTRAINTS PURGE"
                    provider.query_executor.execute_statement(provider.connection, drop_sql, [])
                    if hasattr(provider.connection, "commit"):
                        provider.connection.commit()
                elif db_type == "db2":
                    clean_schema = schema.replace('"', "").strip().upper()
                    clean_table = table_name.replace('"', "").strip().upper()
                    qualified_table = f"{clean_schema}.{clean_table}"
                    drop_sql = f"DROP TABLE {qualified_table}"
                    provider.query_executor.execute_statement(provider.connection, drop_sql, [])
                    if hasattr(provider.connection, "commit"):
                        provider.connection.commit()
            except Exception:
                pass  # Table might not exist

        # Create table with various data types
        create_sql = self._generate_data_types_table(db_type, schema)
        provider.query_executor.execute_statement(provider.connection, create_sql, [])
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Run round-trip test
        # For Oracle, create test schema manually before RoundTripTester (like successful tests)
        if db_type == "oracle":
            test_schema = f"{schema}_TEST"
            provider.schema_operations.create_schema_if_not_exists(provider.connection, test_schema)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()
        else:
            test_schema = f"{schema}_test"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )

        results = tester.run_round_trip_test()

        # Verify success - include all details in assertion message
        assert results["success"], (
            f"Round-trip failed. Success={results['success']}, Errors={results.get('errors', [])}, "
            f"Warnings={results.get('warnings', [])}, Differences={results['tables'].get('differences', [])}, "
            f"Original={results['tables'].get('original_count', 0)}, Regenerated={results['tables'].get('regenerated_count', 0)}"
        )

        if hasattr(provider, "close"):
            provider.close()

    def test_constraint_preservation(self, db_container):
        """Test that all constraint types are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")
        db_type = db_container["type"]
        tester = None

        # For Oracle, convert schema to uppercase (Oracle convention)
        if db_type == "oracle":
            schema = schema.upper()

        try:
            provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()

            create_sql = self._generate_constraints_table(db_type, schema)
            provider.query_executor.execute_statement(provider.connection, create_sql, [])
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()

            # For Oracle, create test schema manually before RoundTripTester (like successful tests)
            if db_type == "oracle":
                test_schema = f"{schema}_TEST"
                provider.schema_operations.create_schema_if_not_exists(
                    provider.connection, test_schema
                )
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()
            else:
                test_schema = f"{schema}_test"
            tester = RoundTripTester(
                source_provider=provider,
                test_provider=provider,
                source_schema=schema,
                test_schema=test_schema,
                test_object_types=["tables"],
            )

            results = tester.run_round_trip_test()

            # Detailed assertion message
            assert results["success"], (
                f"Round-trip failed. Success={results['success']}, Errors={results.get('errors', [])}, "
                f"Warnings={results.get('warnings', [])}, Differences={results['tables'].get('differences', [])}, "
                f"Original={results['tables'].get('original_count', 0)}, Regenerated={results['tables'].get('regenerated_count', 0)}"
            )
        finally:
            # CRITICAL: Clean up connections to prevent hanging
            # Close introspector first if it exists
            if tester and hasattr(tester, "introspector") and tester.introspector:
                try:
                    if hasattr(tester.introspector, "close"):
                        tester.introspector.close()
                except Exception:
                    pass
            # CRITICAL: MySQL and DB2 transactions are already committed (clean_schema commits, DDL auto-commits)
            # Rolling back after commits can cause hangs, so skip rollback for MySQL/DB2
            # Just close the provider connection
            if hasattr(provider, "close"):
                try:
                    provider.close()
                except Exception:
                    pass

    def test_default_value_preservation(self, db_container):
        """Test that default values are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")
        db_type = db_container["type"]

        # For Oracle, convert schema to uppercase (Oracle convention)
        if db_type == "oracle":
            schema = schema.upper()

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Clean up any existing table before creating new one
        table_name = "DEFAULTS_TEST" if db_type in ("oracle", "db2") else "defaults_test"
        try:
            if db_type == "oracle":
                clean_schema = schema.replace('"', "").strip().upper()
                clean_table = table_name.replace('"', "").strip().upper()
                qualified_table = f"{clean_schema}.{clean_table}"
                drop_sql = f"DROP TABLE {qualified_table} CASCADE CONSTRAINTS PURGE"
                provider.query_executor.execute_statement(provider.connection, drop_sql, [])
                if hasattr(provider.connection, "commit"):
                    provider.connection.commit()
            elif db_type == "db2":
                clean_schema = schema.replace('"', "").strip().upper()
                clean_table = table_name.replace('"', "").strip().upper()
                qualified_table = f"{clean_schema}.{clean_table}"
                drop_sql = f"DROP TABLE {qualified_table}"
                provider.query_executor.execute_statement(provider.connection, drop_sql, [])
                if hasattr(provider.connection, "commit"):
                    provider.connection.commit()
        except Exception:
            pass  # Table might not exist

        create_sql = self._generate_defaults_table(db_type, schema)
        provider.query_executor.execute_statement(provider.connection, create_sql, [])
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # For Oracle, create test schema manually before RoundTripTester (like successful tests)
        if db_type == "oracle":
            test_schema = f"{schema}_TEST"
            provider.schema_operations.create_schema_if_not_exists(provider.connection, test_schema)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()
        else:
            test_schema = f"{schema}_test"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )

        results = tester.run_round_trip_test()

        assert results["success"], (
            f"Round-trip failed. Success={results['success']}, Errors={results.get('errors', [])}, "
            f"Warnings={results.get('warnings', [])}, Differences={results['tables'].get('differences', [])}, "
            f"Original={results['tables'].get('original_count', 0)}, Regenerated={results['tables'].get('regenerated_count', 0)}"
        )

        if hasattr(provider, "close"):
            provider.close()

    def _generate_data_types_table(self, db_type: str, schema: str) -> str:
        """Generate table with various data types."""
        if db_type == "postgresql":
            return f"""
            CREATE TABLE "{schema}".data_types_test (
                id SERIAL PRIMARY KEY,
                varchar_col VARCHAR(100),
                char_col CHAR(10),
                text_col TEXT,
                integer_col INTEGER,
                bigint_col BIGINT,
                smallint_col SMALLINT,
                decimal_col DECIMAL(10,2),
                numeric_col NUMERIC(15,5),
                real_col REAL,
                double_col DOUBLE PRECISION,
                boolean_col BOOLEAN,
                date_col DATE,
                time_col TIME,
                timestamp_col TIMESTAMP,
                timestamptz_col TIMESTAMP WITH TIME ZONE,
                json_col JSON,
                jsonb_col JSONB,
                array_col INTEGER[]
            );
            """
        elif db_type == "oracle":
            # Oracle: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.DATA_TYPES_TEST (
                id NUMBER PRIMARY KEY,
                varchar_col VARCHAR2(100),
                char_col CHAR(10),
                text_col CLOB,
                integer_col NUMBER,
                bigint_col NUMBER(19),
                smallint_col NUMBER(5),
                decimal_col NUMBER(10,2),
                numeric_col NUMBER(15,5),
                real_col BINARY_FLOAT,
                double_col BINARY_DOUBLE,
                boolean_col NUMBER(1),
                date_col DATE,
                time_col TIMESTAMP,
                timestamp_col TIMESTAMP,
                timestamptz_col TIMESTAMP WITH TIME ZONE,
                json_col CLOB
            )
            """
        elif db_type == "sqlserver":
            return f"""
            CREATE TABLE [{schema}].data_types_test (
                id INT IDENTITY(1,1) PRIMARY KEY,
                varchar_col NVARCHAR(100),
                char_col NCHAR(10),
                text_col NVARCHAR(MAX),
                integer_col INT,
                bigint_col BIGINT,
                smallint_col SMALLINT,
                decimal_col DECIMAL(10,2),
                numeric_col NUMERIC(15,5),
                real_col REAL,
                double_col FLOAT,
                boolean_col BIT,
                date_col DATE,
                time_col TIME,
                timestamp_col DATETIME2,
                timestamptz_col DATETIMEOFFSET,
                json_col NVARCHAR(MAX)
            );
            """
        elif db_type == "mysql":
            return f"""
            CREATE TABLE `{schema}`.data_types_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                varchar_col VARCHAR(100),
                char_col CHAR(10),
                text_col TEXT,
                integer_col INT,
                bigint_col BIGINT,
                smallint_col SMALLINT,
                decimal_col DECIMAL(10,2),
                numeric_col NUMERIC(15,5),
                real_col FLOAT,
                double_col DOUBLE,
                boolean_col BOOLEAN,
                date_col DATE,
                time_col TIME,
                timestamp_col TIMESTAMP,
                timestamptz_col TIMESTAMP,
                json_col JSON
            );
            """
        elif db_type == "db2":
            # DB2: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.DATA_TYPES_TEST (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                varchar_col VARCHAR(100),
                char_col CHAR(10),
                text_col CLOB,
                integer_col INTEGER,
                bigint_col BIGINT,
                smallint_col SMALLINT,
                decimal_col DECIMAL(10,2),
                numeric_col NUMERIC(15,5),
                real_col REAL,
                double_col DOUBLE,
                boolean_col SMALLINT,
                date_col DATE,
                time_col TIME,
                timestamp_col TIMESTAMP,
                timestamptz_col TIMESTAMP,
                json_col CLOB
            )
            """
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    def _generate_constraints_table(self, db_type: str, schema: str) -> str:
        """Generate table with all constraint types."""
        if db_type == "postgresql":
            return f"""
            CREATE TABLE "{schema}".constraints_test (
                id SERIAL PRIMARY KEY,
                unique_col VARCHAR(50) UNIQUE,
                not_null_col VARCHAR(50) NOT NULL,
                check_col INTEGER CHECK (check_col > 0),
                fk_col INTEGER REFERENCES "{schema}".constraints_test(id)
            );
            """
        elif db_type == "oracle":
            # Oracle: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.CONSTRAINTS_TEST (
                composite_pk_col1 NUMBER,
                composite_pk_col2 NUMBER,
                unique_col VARCHAR2(50) UNIQUE,
                not_null_col VARCHAR2(50) NOT NULL,
                check_col NUMBER CHECK (check_col > 0),
                fk_col1 NUMBER,
                fk_col2 NUMBER,
                PRIMARY KEY (composite_pk_col1, composite_pk_col2),
                FOREIGN KEY (fk_col1, fk_col2) REFERENCES {schema_upper}.CONSTRAINTS_TEST(composite_pk_col1, composite_pk_col2)
            )
            """
        elif db_type == "sqlserver":
            return f"""
            CREATE TABLE [{schema}].constraints_test (
                id INT IDENTITY(1,1),
                unique_col NVARCHAR(50) UNIQUE,
                not_null_col NVARCHAR(50) NOT NULL,
                check_col INT CHECK (check_col > 0),
                composite_pk_col1 INT,
                composite_pk_col2 INT,
                PRIMARY KEY (composite_pk_col1, composite_pk_col2)
            );
            """
        elif db_type == "mysql":
            return f"""
            CREATE TABLE `{schema}`.constraints_test (
                id INT,
                unique_col VARCHAR(50) UNIQUE,
                not_null_col VARCHAR(50) NOT NULL,
                check_col INT CHECK (check_col > 0),
                fk_col INT,
                composite_pk_col1 INT,
                composite_pk_col2 INT,
                PRIMARY KEY (composite_pk_col1, composite_pk_col2),
                FOREIGN KEY (fk_col) REFERENCES `{schema}`.constraints_test(composite_pk_col1)
            );
            """
        elif db_type == "db2":
            # DB2: Remove PRIMARY KEY from id to allow composite PRIMARY KEY
            # A table can only have one PRIMARY KEY constraint
            # DB2 does NOT allow foreign keys to reference only part of a composite PK
            # So we reference the single-column id instead (using a self-referencing FK)
            # DB2 requires all columns in a UNIQUE constraint to be NOT NULL
            return f"""
            CREATE TABLE "{schema}".constraints_test (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                unique_col VARCHAR(50) NOT NULL UNIQUE,
                not_null_col VARCHAR(50) NOT NULL,
                check_col INTEGER CHECK (check_col > 0),
                fk_col INTEGER,
                composite_pk_col1 INTEGER NOT NULL,
                composite_pk_col2 INTEGER NOT NULL,
                UNIQUE (composite_pk_col1, composite_pk_col2),
                FOREIGN KEY (fk_col) REFERENCES "{schema}".constraints_test(id)
            );
            """
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    def _generate_defaults_table(self, db_type: str, schema: str) -> str:
        """Generate table with various default values."""
        if db_type == "postgresql":
            return f"""
            CREATE TABLE "{schema}".defaults_test (
                id SERIAL PRIMARY KEY,
                literal_default VARCHAR(50) DEFAULT 'default_value',
                function_default TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sequence_default INTEGER DEFAULT nextval('"{schema}".defaults_test_id_seq'),
                boolean_default BOOLEAN DEFAULT TRUE,
                numeric_default INTEGER DEFAULT 42
            );
            """
        elif db_type == "oracle":
            # Oracle: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.DEFAULTS_TEST (
                id NUMBER PRIMARY KEY,
                literal_default VARCHAR2(50) DEFAULT 'default_value',
                function_default TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                boolean_default NUMBER(1) DEFAULT 1,
                numeric_default NUMBER DEFAULT 42
            )
            """
        elif db_type == "sqlserver":
            return f"""
            CREATE TABLE [{schema}].defaults_test (
                id INT IDENTITY(1,1) PRIMARY KEY,
                literal_default NVARCHAR(50) DEFAULT 'default_value',
                function_default DATETIME2 DEFAULT GETDATE(),
                boolean_default BIT DEFAULT 1,
                numeric_default INT DEFAULT 42
            );
            """
        elif db_type == "mysql":
            return f"""
            CREATE TABLE `{schema}`.defaults_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                literal_default VARCHAR(50) DEFAULT 'default_value',
                function_default TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                boolean_default BOOLEAN DEFAULT TRUE,
                numeric_default INT DEFAULT 42
            );
            """
        elif db_type == "db2":
            return f"""
            CREATE TABLE "{schema}".defaults_test (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                literal_default VARCHAR(50) DEFAULT 'default_value',
                function_default TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                boolean_default SMALLINT DEFAULT 1,
                numeric_default INTEGER DEFAULT 42
            );
            """
        else:
            raise ValueError(f"Unsupported database type: {db_type}")
