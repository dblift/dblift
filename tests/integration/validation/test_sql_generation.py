"""
SQL generation validation tests.

Tests that SQL generation preserves all properties correctly.
"""

from typing import Any, Dict

import pytest

from config import DbliftConfig
from config.database_config import DatabaseConfig
from core.logger import ConsoleLog
from core.sql_generator.generator_factory import SqlGeneratorFactory
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.validation.round_trip_tester import RoundTripTester
from db.provider_registry import ProviderRegistry
from tests.integration.helpers.database_helper import execute_sql


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "mysql", "sqlserver", "oracle", "db2"],
    indirect=True,
)
class TestSqlGeneration:
    """Tests for SQL generation property preservation."""

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
        log = ConsoleLog("sql_generation_test", enable_debug=False)
        return ProviderRegistry.create_provider(config, log=log)

    def test_generated_sql_preserves_all_properties(self, db_container):
        """Test that generated SQL preserves all table properties."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")
        db_type = db_container["type"]

        # Ensure schema exists
        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create original table with all properties
        create_sql = self._generate_comprehensive_table_sql(db_type, schema)
        provider.query_executor.execute_statement(provider.connection, create_sql, [])
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Introspect the table
        from core.introspection.schema_introspector import SchemaIntrospector

        introspector = SchemaIntrospector(provider)
        original_tables = introspector.get_tables(schema)

        assert len(original_tables) > 0, "Should introspect at least one table"

        # Find the comprehensive_test table specifically
        original_table = None
        for table in original_tables:
            if table.name.lower() == "comprehensive_test":
                original_table = table
                break

        assert (
            original_table is not None
        ), f"comprehensive_test table not found. Available tables: {[t.name for t in original_tables]}"

        # Generate SQL from introspected table
        generator = SqlGeneratorFactory.create(db_type)
        generated_sql = generator.generate_create_statement(original_table)

        # Get additional statements (e.g., ALTER TABLE for DB2 self-referencing FKs)
        additional_statements = generator._generate_additional_statements(original_table, db_type)
        all_sql = (
            generated_sql + "\n" + "\n".join(additional_statements)
            if additional_statements
            else generated_sql
        )

        # Verify generated SQL contains key properties
        assert generated_sql, "Generated SQL should not be empty"

        # Check for column definitions
        for col in original_table.columns:
            assert (
                col.name in generated_sql or col.name.upper() in generated_sql.upper()
            ), f"Column '{col.name}' should be in generated SQL"

        # Check for constraint definitions
        for constraint in original_table.constraints:
            if constraint.constraint_type == ConstraintType.PRIMARY_KEY:
                assert (
                    "PRIMARY KEY" in generated_sql.upper()
                ), "PRIMARY KEY constraint should be in generated SQL"
            elif constraint.constraint_type == ConstraintType.FOREIGN_KEY:
                # For DB2, self-referencing foreign keys are in additional statements
                # Check both CREATE TABLE and additional statements
                assert (
                    "FOREIGN KEY" in all_sql.upper() or "REFERENCES" in all_sql.upper()
                ), "FOREIGN KEY constraint should be in generated SQL (CREATE TABLE or ALTER TABLE)"

        # Execute generated SQL on test schema
        # For Oracle, convert schema to uppercase and create test schema manually (like successful tests)
        if db_type == "oracle":
            schema = schema.upper()
            test_schema = f"{schema}_TEST"
            provider.schema_operations.create_schema_if_not_exists(provider.connection, test_schema)
            if not provider.connection.getAutoCommit():
                provider.connection.commit()
        else:
            test_schema = f"{schema}_test"
            provider.schema_operations.create_schema_if_not_exists(provider.connection, test_schema)
            if hasattr(provider.connection, "commit") and hasattr(
                provider.connection, "getAutoCommit"
            ):
                if not provider.connection.getAutoCommit():
                    provider.connection.commit()

        # Replace schema name in generated SQL and additional statements
        if schema != test_schema:
            generated_sql = generated_sql.replace(f'"{schema}"', f'"{test_schema}"')
            generated_sql = generated_sql.replace(f"{schema}.", f"{test_schema}.")
            generated_sql = generated_sql.replace(f"[{schema}]", f"[{test_schema}]")
            generated_sql = generated_sql.replace(f"`{schema}`", f"`{test_schema}`")

            # Also replace schema in additional statements
            for i, stmt in enumerate(additional_statements):
                additional_statements[i] = stmt.replace(f'"{schema}"', f'"{test_schema}"')
                additional_statements[i] = additional_statements[i].replace(
                    f"{schema}.", f"{test_schema}."
                )
                additional_statements[i] = additional_statements[i].replace(
                    f"[{schema}]", f"[{test_schema}]"
                )
                additional_statements[i] = additional_statements[i].replace(
                    f"`{schema}`", f"`{test_schema}`"
                )

        # Drop table if it exists (from previous test runs)
        table_name = "COMPREHENSIVE_TEST"
        try:
            if db_type in ("oracle", "db2"):
                # For Oracle and DB2, use unquoted identifiers (uppercase)
                clean_schema = test_schema.replace('"', "").strip().upper()
                clean_table = table_name.replace('"', "").strip().upper()
                qualified_table = f"{clean_schema}.{clean_table}"
                if db_type == "oracle":
                    drop_sql = f"DROP TABLE {qualified_table} CASCADE CONSTRAINTS PURGE"
                else:  # db2
                    drop_sql = f"DROP TABLE {qualified_table}"
                try:
                    provider.query_executor.execute_statement(provider.connection, drop_sql, [])
                    if hasattr(provider.connection, "getAutoCommit"):
                        if not provider.connection.getAutoCommit():
                            if hasattr(provider.connection, "commit"):
                                provider.connection.commit()
                    elif hasattr(provider.connection, "commit"):
                        provider.connection.commit()
                except Exception:
                    pass  # Table might not exist - that's OK
            else:
                qualified_table = f"{test_schema}.{table_name}"
                drop_sql = f"DROP TABLE IF EXISTS {qualified_table}"
                provider.query_executor.execute_statement(provider.connection, drop_sql, [])
                if hasattr(provider.connection, "getAutoCommit"):
                    if not provider.connection.getAutoCommit():
                        if hasattr(provider.connection, "commit"):
                            provider.connection.commit()
        except Exception:
            pass  # Table might not exist or drop might fail - that's OK

        try:
            # Execute CREATE TABLE statement
            provider.query_executor.execute_statement(provider.connection, generated_sql, [])
            # Execute additional statements (e.g., ALTER TABLE for DB2)
            for stmt in additional_statements:
                if stmt and stmt.strip():
                    provider.query_executor.execute_statement(provider.connection, stmt, [])
            # CRITICAL: Only commit if autoCommit is False
            # Cannot commit when autoCommit is enabled (driver requirement)
            if hasattr(provider.connection, "commit"):
                if hasattr(provider.connection, "getAutoCommit"):
                    if not provider.connection.getAutoCommit():
                        provider.connection.commit()
                else:
                    # Fallback: try to commit (may fail, but that's OK)
                    try:
                        provider.connection.commit()
                    except Exception:
                        pass  # Ignore commit errors when autoCommit status unknown
        except Exception as e:
            pytest.fail(f"Generated SQL failed to execute: {e}\nGenerated SQL:\n{generated_sql}")

        # Re-introspect from test schema
        test_tables = introspector.get_tables(test_schema)
        assert len(test_tables) > 0, "Should introspect table from test schema"

        # Find the comprehensive_test table specifically
        test_table = None
        for table in test_tables:
            if table.name.lower() == "comprehensive_test":
                test_table = table
                break

        assert (
            test_table is not None
        ), f"comprehensive_test table not found in test schema. Available tables: {[t.name for t in test_tables]}"

        # Compare original and test tables
        from core.comparison.comparator import ObjectComparator
        from core.comparison.type_normalizer import DataTypeNormalizer

        comparator = ObjectComparator(DataTypeNormalizer())
        diff = comparator.compare_tables(original_table, test_table, db_type)

        # Report differences
        if diff.has_diffs:
            error_msg = f"Generated SQL did not preserve all properties:\n"
            if diff.missing_columns:
                error_msg += f"  Missing columns: {diff.missing_columns}\n"
            if diff.extra_columns:
                error_msg += f"  Extra columns: {diff.extra_columns}\n"
            if diff.modified_columns:
                for col_diff in diff.modified_columns:
                    error_msg += f"  Modified column '{col_diff.column_name}': {col_diff}\n"
            if diff.missing_constraints:
                error_msg += f"  Missing constraints: {diff.missing_constraints}\n"
            if diff.extra_constraints:
                error_msg += f"  Extra constraints: {diff.extra_constraints}\n"
            error_msg += f"\nGenerated SQL:\n{generated_sql}"
            pytest.fail(error_msg)

        assert not diff.has_diffs, "Generated SQL should preserve all properties"

        if hasattr(provider, "close"):
            provider.close()

    def test_generated_sql_preserves_column_properties(self, db_container):
        """Test that generated SQL preserves all column properties."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")
        db_type = db_container["type"]

        # For Oracle, convert schema to uppercase (Oracle convention)
        if db_type == "oracle":
            schema = schema.upper()

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Create table with various column properties
        create_sql = self._generate_column_properties_table(db_type, schema)
        provider.query_executor.execute_statement(provider.connection, create_sql, [])
        if hasattr(provider.connection, "commit") and hasattr(provider.connection, "getAutoCommit"):
            if not provider.connection.getAutoCommit():
                provider.connection.commit()

        # Use round-trip test to verify property preservation
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

        # Verify success - detailed error message
        assert results["success"], (
            f"Round-trip failed. Success={results['success']}, Errors={results.get('errors', [])}, "
            f"Warnings={results.get('warnings', [])}, Differences={results['tables'].get('differences', [])}, "
            f"Original={results['tables'].get('original_count', 0)}, Regenerated={results['tables'].get('regenerated_count', 0)}"
        )
        assert (
            len(results["tables"]["differences"]) == 0
        ), f"Found differences: {results['tables']['differences']}"

        if hasattr(provider, "close"):
            provider.close()

    def _generate_comprehensive_table_sql(self, db_type: str, schema: str) -> str:
        """Generate SQL for table with all properties."""
        if db_type == "postgresql":
            return f"""
            CREATE TABLE "{schema}".comprehensive_test (
                id SERIAL PRIMARY KEY,
                varchar_col VARCHAR(100),
                integer_col INTEGER NOT NULL,
                decimal_col DECIMAL(10,2),
                timestamp_col TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                boolean_col BOOLEAN DEFAULT TRUE,
                text_col TEXT,
                json_col JSONB,
                nullable_col VARCHAR(50),
                not_null_col VARCHAR(50) NOT NULL,
                unique_col VARCHAR(50) UNIQUE,
                check_col INTEGER CHECK (check_col > 0),
                default_literal_col VARCHAR(50) DEFAULT 'default_value',
                default_function_col TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                computed_col INTEGER GENERATED ALWAYS AS (integer_col * 2) STORED,
                fk_col INTEGER,
                CONSTRAINT fk_test FOREIGN KEY (fk_col) REFERENCES "{schema}".comprehensive_test(id)
            );
            """
        elif db_type == "oracle":
            # Oracle: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.COMPREHENSIVE_TEST (
                id NUMBER PRIMARY KEY,
                varchar_col VARCHAR2(100),
                integer_col NUMBER NOT NULL,
                decimal_col NUMBER(10,2),
                timestamp_col TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                boolean_col NUMBER(1) DEFAULT 1,
                text_col CLOB,
                json_col CLOB,
                nullable_col VARCHAR2(50),
                not_null_col VARCHAR2(50) NOT NULL,
                unique_col VARCHAR2(50) UNIQUE,
                check_col NUMBER CHECK (check_col > 0),
                default_literal_col VARCHAR2(50) DEFAULT 'default_value',
                default_function_col TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                computed_col NUMBER GENERATED ALWAYS AS (integer_col * 2) VIRTUAL,
                fk_col NUMBER,
                CONSTRAINT FK_TEST FOREIGN KEY (fk_col) REFERENCES {schema_upper}.COMPREHENSIVE_TEST(id)
            )
            """
        elif db_type == "sqlserver":
            return f"""
            CREATE TABLE [{schema}].comprehensive_test (
                id INT IDENTITY(1,1) PRIMARY KEY,
                varchar_col NVARCHAR(100),
                integer_col INT NOT NULL,
                decimal_col DECIMAL(10,2),
                timestamp_col DATETIME2 DEFAULT GETDATE(),
                boolean_col BIT DEFAULT 1,
                text_col NVARCHAR(MAX),
                json_col NVARCHAR(MAX),
                nullable_col NVARCHAR(50),
                not_null_col NVARCHAR(50) NOT NULL,
                unique_col NVARCHAR(50) UNIQUE,
                check_col INT CHECK (check_col > 0),
                default_literal_col NVARCHAR(50) DEFAULT 'default_value',
                default_function_col DATETIME2 DEFAULT GETDATE(),
                computed_col AS (integer_col * 2) PERSISTED,
                fk_col INT,
                FOREIGN KEY (fk_col) REFERENCES [{schema}].comprehensive_test(id)
            );
            """
        elif db_type == "mysql":
            return f"""
            CREATE TABLE `{schema}`.comprehensive_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                varchar_col VARCHAR(100),
                integer_col INT NOT NULL,
                decimal_col DECIMAL(10,2),
                timestamp_col TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                boolean_col BOOLEAN DEFAULT TRUE,
                text_col TEXT,
                json_col JSON,
                nullable_col VARCHAR(50),
                not_null_col VARCHAR(50) NOT NULL,
                unique_col VARCHAR(50) UNIQUE,
                check_col INT CHECK (check_col > 0),
                default_literal_col VARCHAR(50) DEFAULT 'default_value',
                default_function_col TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                computed_col INT AS (integer_col * 2) STORED,
                fk_col INT,
                FOREIGN KEY (fk_col) REFERENCES `{schema}`.comprehensive_test(id)
            );
            """
        elif db_type == "db2":
            # DB2: use unquoted identifiers (uppercase) to simplify tests
            # Remove UNIQUE constraint to avoid SQLCODE -542 error
            # UNIQUE constraints are tested separately in other test files
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.COMPREHENSIVE_TEST (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                varchar_col VARCHAR(100),
                integer_col INTEGER NOT NULL,
                decimal_col DECIMAL(10,2),
                timestamp_col TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                boolean_col SMALLINT DEFAULT 1,
                text_col CLOB,
                json_col CLOB,
                nullable_col VARCHAR(50),
                not_null_col VARCHAR(50) NOT NULL,
                unique_col VARCHAR(50),
                check_col INTEGER CHECK (check_col > 0),
                default_literal_col VARCHAR(50) DEFAULT 'default_value',
                default_function_col TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                computed_col INTEGER GENERATED ALWAYS AS (integer_col * 2),
                fk_col INTEGER,
                CONSTRAINT FK_TEST FOREIGN KEY (fk_col) REFERENCES {schema_upper}.COMPREHENSIVE_TEST(id)
            )
            """
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

    def _generate_column_properties_table(self, db_type: str, schema: str) -> str:
        """Generate SQL for table with various column properties."""
        if db_type == "postgresql":
            return f"""
            CREATE TABLE "{schema}".column_props_test (
                id SERIAL PRIMARY KEY,
                nullable_col VARCHAR(50),
                not_null_col VARCHAR(50) NOT NULL,
                default_literal VARCHAR(50) DEFAULT 'test',
                default_function TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                default_sequence INTEGER DEFAULT nextval('"{schema}".column_props_test_id_seq'),
                unique_col VARCHAR(50) UNIQUE,
                check_col INTEGER CHECK (check_col > 0),
                computed_stored INTEGER GENERATED ALWAYS AS (id * 2) STORED,
                collation_col VARCHAR(50) COLLATE "C"
            );
            """
        elif db_type == "oracle":
            # Oracle: use unquoted identifiers (uppercase) to simplify tests
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.COLUMN_PROPS_TEST (
                id NUMBER PRIMARY KEY,
                nullable_col VARCHAR2(50),
                not_null_col VARCHAR2(50) NOT NULL,
                default_literal VARCHAR2(50) DEFAULT 'test',
                default_function TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                unique_col VARCHAR2(50) UNIQUE,
                check_col NUMBER CHECK (check_col > 0),
                computed_virtual NUMBER GENERATED ALWAYS AS (id * 3) VIRTUAL
            )
            """
        elif db_type == "sqlserver":
            return f"""
            CREATE TABLE [{schema}].column_props_test (
                id INT IDENTITY(1,1) PRIMARY KEY,
                nullable_col NVARCHAR(50),
                not_null_col NVARCHAR(50) NOT NULL,
                default_literal NVARCHAR(50) DEFAULT 'test',
                default_function DATETIME2 DEFAULT GETDATE(),
                unique_col NVARCHAR(50) UNIQUE,
                check_col INT CHECK (check_col > 0),
                computed_persisted AS (id * 2) PERSISTED
            );
            """
        elif db_type == "mysql":
            return f"""
            CREATE TABLE `{schema}`.column_props_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                nullable_col VARCHAR(50),
                not_null_col VARCHAR(50) NOT NULL,
                default_literal VARCHAR(50) DEFAULT 'test',
                default_function TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                unique_col VARCHAR(50) UNIQUE,
                check_col INT CHECK (check_col > 0),
                base_col INT DEFAULT 10,
                computed_stored INT AS (base_col * 2) STORED
            );
            """
        elif db_type == "db2":
            # DB2: use unquoted identifiers (uppercase) to simplify tests
            # Remove UNIQUE constraint to avoid SQLCODE -542 error with computed columns
            schema_upper = schema.upper()
            return f"""
            CREATE TABLE {schema_upper}.COLUMN_PROPS_TEST (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                nullable_col VARCHAR(50),
                not_null_col VARCHAR(50) NOT NULL,
                default_literal VARCHAR(50) DEFAULT 'test',
                default_function TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                unique_col VARCHAR(50),
                check_col INTEGER CHECK (check_col > 0),
                computed_col INTEGER GENERATED ALWAYS AS (id * 2)
            )
            """
        else:
            raise ValueError(f"Unsupported database type: {db_type}")
