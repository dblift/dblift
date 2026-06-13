"""
Comprehensive property preservation tests for all dialects.

These tests verify that SQL generation and introspection correctly handle
all database properties including data types, constraints, defaults, etc.
"""

import pytest

from config import DbliftConfig
from config.database_config import DatabaseConfig
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester
from db.provider_registry import ProviderRegistry


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "mysql", "sqlserver", "oracle", "db2"],
    indirect=True,
)
class TestComprehensiveProperties:
    """Comprehensive property preservation tests."""

    def _get_provider(self, db_container):
        """Create database provider."""
        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Build database URL if not provided
        if db_container.get("url"):
            database_url = db_container.get("url")
        else:
            host = db_container.get("host", "localhost")
            port = db_container.get("port")
            database = db_container.get("database")

            if db_type == "postgresql":
                database_url = f"postgresql+psycopg://{host}:{port}/{database}"
            elif db_type == "mysql":
                database_url = f"mysql+pymysql://{host}:{port}/{database}"
            elif db_type == "sqlserver":
                database_url = f"mssql+pymssql://{host}:{port}/{database}?encrypt=false"
            elif db_type == "oracle":
                database_url = f"oracle+oracledb://{host}:{port}?service_name={database}"
            elif db_type == "db2":
                database_url = f"ibm_db_sa://{host}:{port}/{database}"
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

    def _drop_table_if_exists(self, provider, db_type: str, schema: str, table_name: str):
        """Drop a table if it exists, handling database-specific syntax.

        For Oracle and DB2, uses unquoted identifiers (uppercase) to simplify tests.
        """
        try:
            if db_type in ("oracle", "db2"):
                # For Oracle and DB2, use unquoted identifiers (uppercase)
                clean_schema = schema.replace('"', "").strip().upper()
                clean_table = table_name.replace('"', "").strip().upper()
                qualified_table = f"{clean_schema}.{clean_table}"

                if db_type == "oracle":
                    drop_sql = f"DROP TABLE {qualified_table} CASCADE CONSTRAINTS PURGE"
                else:  # db2
                    drop_sql = f"DROP TABLE {qualified_table}"

                try:
                    provider.query_executor.execute_statement(provider.connection, drop_sql, [])
                    # Commit if autocommit is disabled
                    if hasattr(provider.connection, "getAutoCommit"):
                        if not provider.connection.getAutoCommit():
                            if hasattr(provider.connection, "commit"):
                                provider.connection.commit()
                    elif hasattr(provider.connection, "commit"):
                        provider.connection.commit()
                except Exception:
                    # Table might not exist - that's OK
                    pass
            else:
                qualified_table = f"{schema}.{table_name}"
                drop_sql = f"DROP TABLE IF EXISTS {qualified_table}"
                provider.query_executor.execute_statement(provider.connection, drop_sql, [])
                # Commit if autocommit is disabled
                if hasattr(provider.connection, "getAutoCommit"):
                    if not provider.connection.getAutoCommit():
                        if hasattr(provider.connection, "commit"):
                            provider.connection.commit()
        except Exception as e:
            # Table might not exist or drop might fail for other reasons
            # Log but don't fail - we'll try to create anyway
            import logging

            logging.getLogger(__name__).debug(f"Could not drop table {schema}.{table_name}: {e}")
            pass

    def test_all_numeric_types(self, db_container):
        """Test all numeric data types are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        # For Oracle, convert schema to uppercase (Oracle convention)
        db_type = db_container["type"]
        if db_type == "oracle":
            schema = schema.upper()

        # Ensure schema exists
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Clean up any existing table before creating new one
        table_name = "NUMERIC_TYPES_TEST" if db_type in ("oracle", "db2") else "numeric_types_test"
        self._drop_table_if_exists(provider, db_type, schema, table_name)

        # Create table with all numeric types
        create_sql = self._generate_numeric_types_table(db_type, schema)
        provider.query_executor.execute_statement(provider.connection, create_sql, [])
        # CRITICAL: DB2 requires explicit commit after DDL operations
        if db_type == "db2":
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()
        elif (
            hasattr(provider.connection, "getAutoCommit")
            and not provider.connection.getAutoCommit()
        ):
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

        # Verify success
        assert (
            results["success"] or len(results["errors"]) == 0
        ), f"Round-trip failed: {results.get('errors', [])}. Warnings: {results.get('warnings', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_all_string_types(self, db_container):
        """Test all string data types are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        # For Oracle, convert schema to uppercase (Oracle convention)
        db_type = db_container["type"]
        if db_type == "oracle":
            schema = schema.upper()

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Clean up any existing table before creating new one
        table_name = "STRING_TYPES_TEST" if db_type in ("oracle", "db2") else "string_types_test"
        self._drop_table_if_exists(provider, db_type, schema, table_name)

        create_sql = self._generate_string_types_table(db_type, schema)
        provider.query_executor.execute_statement(provider.connection, create_sql, [])
        # CRITICAL: DB2 requires explicit commit after DDL operations
        if db_type == "db2":
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()
        elif (
            hasattr(provider.connection, "getAutoCommit")
            and not provider.connection.getAutoCommit()
        ):
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

        assert (
            results["success"] or len(results["errors"]) == 0
        ), f"Round-trip failed: {results.get('errors', [])}. Warnings: {results.get('warnings', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_all_datetime_types(self, db_container):
        """Test all date/time data types are preserved."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        # For Oracle, convert schema to uppercase (Oracle convention)
        db_type = db_container["type"]
        if db_type == "oracle":
            schema = schema.upper()

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Clean up any existing table before creating new one
        table_name = (
            "DATETIME_TYPES_TEST" if db_type in ("oracle", "db2") else "datetime_types_test"
        )
        self._drop_table_if_exists(provider, db_type, schema, table_name)

        create_sql = self._generate_datetime_types_table(db_type, schema)
        provider.query_executor.execute_statement(provider.connection, create_sql, [])
        # CRITICAL: DB2 requires explicit commit after DDL operations
        if db_type == "db2":
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()
        elif (
            hasattr(provider.connection, "getAutoCommit")
            and not provider.connection.getAutoCommit()
        ):
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

        assert (
            results["success"] or len(results["errors"]) == 0
        ), f"Round-trip failed: {results.get('errors', [])}. Warnings: {results.get('warnings', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_complex_constraints(self, db_container):
        """Test complex constraint combinations."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")

        # For Oracle, convert schema to uppercase (Oracle convention)
        db_type = db_container["type"]
        if db_type == "oracle":
            schema = schema.upper()

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Clean up any existing table before creating new one
        table_name = (
            "COMPLEX_CONSTRAINTS_TEST"
            if db_type in ("oracle", "db2")
            else "complex_constraints_test"
        )
        self._drop_table_if_exists(provider, db_type, schema, table_name)

        create_sql = self._generate_complex_constraints_table(db_type, schema)
        provider.query_executor.execute_statement(provider.connection, create_sql, [])
        # CRITICAL: DB2 requires explicit commit after DDL operations
        if db_type == "db2":
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()
        elif (
            hasattr(provider.connection, "getAutoCommit")
            and not provider.connection.getAutoCommit()
        ):
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

        assert (
            results["success"] or len(results["errors"]) == 0
        ), f"Round-trip failed: {results.get('errors', [])}. Warnings: {results.get('warnings', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def _generate_numeric_types_table(self, db_type: str, schema: str) -> str:
        """Generate table with all numeric types."""
        if db_type == "postgresql":
            return f"""
            CREATE TABLE "{schema}".numeric_types_test (
                id SERIAL PRIMARY KEY,
                smallint_col SMALLINT,
                integer_col INTEGER,
                bigint_col BIGINT,
                decimal_col DECIMAL(10,2),
                numeric_col NUMERIC(15,5),
                real_col REAL,
                double_col DOUBLE PRECISION
            )
            """
        elif db_type == "mysql":
            return f"""
            CREATE TABLE `{schema}`.numeric_types_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                tinyint_col TINYINT,
                smallint_col SMALLINT,
                mediumint_col MEDIUMINT,
                integer_col INT,
                bigint_col BIGINT,
                decimal_col DECIMAL(10,2),
                float_col FLOAT,
                double_col DOUBLE
            )
            """
        elif db_type == "sqlserver":
            return f"""
            CREATE TABLE [{schema}].numeric_types_test (
                id INT IDENTITY(1,1) PRIMARY KEY,
                tinyint_col TINYINT,
                smallint_col SMALLINT,
                integer_col INT,
                bigint_col BIGINT,
                decimal_col DECIMAL(10,2),
                numeric_col NUMERIC(15,5),
                float_col FLOAT,
                real_col REAL
            )
            """
        elif db_type == "oracle":
            # Oracle: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.NUMERIC_TYPES_TEST (
                id NUMBER PRIMARY KEY,
                number_col NUMBER,
                number_10_2 NUMBER(10,2),
                number_15_5 NUMBER(15,5),
                float_col FLOAT,
                binary_float_col BINARY_FLOAT,
                binary_double_col BINARY_DOUBLE
            )
            """
        elif db_type == "db2":
            # DB2: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.NUMERIC_TYPES_TEST (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                smallint_col SMALLINT,
                integer_col INTEGER,
                bigint_col BIGINT,
                decimal_col DECIMAL(10,2),
                numeric_col NUMERIC(15,5),
                real_col REAL,
                double_col DOUBLE
            )
            """
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    def _generate_string_types_table(self, db_type: str, schema: str) -> str:
        """Generate table with all string types."""
        if db_type == "postgresql":
            return f"""
            CREATE TABLE "{schema}".string_types_test (
                id SERIAL PRIMARY KEY,
                char_col CHAR(10),
                varchar_col VARCHAR(100),
                text_col TEXT
            )
            """
        elif db_type == "mysql":
            return f"""
            CREATE TABLE `{schema}`.string_types_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                char_col CHAR(10),
                varchar_col VARCHAR(100),
                text_col TEXT,
                mediumtext_col MEDIUMTEXT,
                longtext_col LONGTEXT
            )
            """
        elif db_type == "sqlserver":
            return f"""
            CREATE TABLE [{schema}].string_types_test (
                id INT IDENTITY(1,1) PRIMARY KEY,
                char_col CHAR(10),
                varchar_col VARCHAR(100),
                nchar_col NCHAR(10),
                nvarchar_col NVARCHAR(100),
                text_col TEXT,
                ntext_col NTEXT
            )
            """
        elif db_type == "oracle":
            # Oracle: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.STRING_TYPES_TEST (
                id NUMBER PRIMARY KEY,
                char_col CHAR(10),
                varchar2_col VARCHAR2(100),
                nchar_col NCHAR(10),
                nvarchar2_col NVARCHAR2(100),
                clob_col CLOB,
                nclob_col NCLOB
            )
            """
        elif db_type == "db2":
            # DB2: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.STRING_TYPES_TEST (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                char_col CHAR(10),
                varchar_col VARCHAR(100),
                clob_col CLOB
            )
            """
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    def _generate_datetime_types_table(self, db_type: str, schema: str) -> str:
        """Generate table with all date/time types."""
        if db_type == "postgresql":
            return f"""
            CREATE TABLE "{schema}".datetime_types_test (
                id SERIAL PRIMARY KEY,
                date_col DATE,
                time_col TIME,
                timestamp_col TIMESTAMP,
                timestamptz_col TIMESTAMPTZ
            )
            """
        elif db_type == "mysql":
            return f"""
            CREATE TABLE `{schema}`.datetime_types_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                date_col DATE,
                time_col TIME,
                datetime_col DATETIME,
                timestamp_col TIMESTAMP,
                year_col YEAR
            )
            """
        elif db_type == "sqlserver":
            return f"""
            CREATE TABLE [{schema}].datetime_types_test (
                id INT IDENTITY(1,1) PRIMARY KEY,
                date_col DATE,
                time_col TIME,
                datetime_col DATETIME,
                datetime2_col DATETIME2,
                datetimeoffset_col DATETIMEOFFSET,
                smalldatetime_col SMALLDATETIME
            )
            """
        elif db_type == "oracle":
            # Oracle: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.DATETIME_TYPES_TEST (
                id NUMBER PRIMARY KEY,
                date_col DATE,
                timestamp_col TIMESTAMP,
                timestamp_tz_col TIMESTAMP WITH TIME ZONE,
                timestamp_ltz_col TIMESTAMP WITH LOCAL TIME ZONE
            )
            """
        elif db_type == "db2":
            # DB2: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.DATETIME_TYPES_TEST (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                date_col DATE,
                time_col TIME,
                timestamp_col TIMESTAMP
            )
            """
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    def _generate_complex_constraints_table(self, db_type: str, schema: str) -> str:
        """Generate table with complex constraint combinations."""
        if db_type == "postgresql":
            return f"""
            CREATE TABLE "{schema}".complex_constraints_test (
                id SERIAL PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                value INTEGER CHECK (value > 0 AND value < 1000),
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        elif db_type == "mysql":
            return f"""
            CREATE TABLE `{schema}`.complex_constraints_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                value INT CHECK (value > 0 AND value < 1000),
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        elif db_type == "sqlserver":
            return f"""
            CREATE TABLE [{schema}].complex_constraints_test (
                id INT IDENTITY(1,1) PRIMARY KEY,
                code NVARCHAR(50) UNIQUE NOT NULL,
                value INT CHECK (value > 0 AND value < 1000),
                status NVARCHAR(20) DEFAULT 'active',
                created_at DATETIME2 DEFAULT GETDATE()
            )
            """
        elif db_type == "oracle":
            # Oracle: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.COMPLEX_CONSTRAINTS_TEST (
                id NUMBER PRIMARY KEY,
                code VARCHAR2(50) UNIQUE NOT NULL,
                value NUMBER CHECK (value > 0 AND value < 1000),
                status VARCHAR2(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        elif db_type == "db2":
            # DB2: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.COMPLEX_CONSTRAINTS_TEST (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                value INTEGER CHECK (value > 0 AND value < 1000),
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        else:
            raise ValueError(f"Unsupported database type: {db_type}")
