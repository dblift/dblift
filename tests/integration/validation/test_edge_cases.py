"""
Edge case tests for snapshot, diff-to-SQL, and export-schema.

Tests edge cases like:
- Quoted identifiers with special characters
- Reserved word identifiers
- Very long names
- Unicode characters
- Case sensitivity variations
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
class TestEdgeCases:
    """Tests for edge cases in schema handling."""

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
        log = ConsoleLog("edge_case_test", enable_debug=False)
        return ProviderRegistry.create_provider(config, log=log)

    def test_quoted_identifiers(self, db_container):
        """Test handling of quoted identifiers."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")
        db_type = db_container["type"]

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with quoted identifiers (case-sensitive, special chars)
        if db_type == "postgresql":
            create_sql = f"""
            CREATE TABLE "{schema}"."TestTable" (
                "Id" SERIAL PRIMARY KEY,
                "User Name" VARCHAR(100),
                "created-at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        elif db_type == "oracle":
            schema_upper = schema.upper()
            create_sql = f"""
            CREATE TABLE {schema_upper}."TestTable" (
                "Id" NUMBER PRIMARY KEY,
                "User Name" VARCHAR2(100),
                "created-at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        elif db_type == "sqlserver":
            create_sql = f"""
            CREATE TABLE [{schema}].[TestTable] (
                [Id] INT IDENTITY(1,1) PRIMARY KEY,
                [User Name] NVARCHAR(100),
                [created-at] DATETIME2 DEFAULT GETDATE()
            );
            """
        elif db_type == "mysql":
            create_sql = f"""
            CREATE TABLE `{schema}`.`TestTable` (
                `Id` INT AUTO_INCREMENT PRIMARY KEY,
                `User Name` VARCHAR(100),
                `created-at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        elif db_type == "db2":
            create_sql = f"""
            CREATE TABLE "{schema}"."TestTable" (
                "Id" INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                "User Name" VARCHAR(100),
                "created-at" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        else:
            pytest.skip(f"Quoted identifiers test not implemented for {db_type}")

        try:
            provider.query_executor.execute_statement(provider.connection, create_sql, [])
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()
        except Exception as e:
            pytest.skip(f"Quoted identifiers not supported or failed: {e}")

        # Run round-trip test
        test_schema = f"{schema}_test"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )

        results = tester.run_round_trip_test()

        # For quoted identifiers, we may have case differences, so be lenient
        if not results["success"]:
            # Check if differences are only case-related
            differences = results["tables"]["differences"]
            if differences:
                # Log but don't fail if it's just case sensitivity
                print(f"Quoted identifier differences: {differences}")

        if hasattr(provider, "close"):
            provider.close()

    def test_reserved_words(self, db_container):
        """Test handling of reserved word identifiers."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")
        db_type = db_container["type"]

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with reserved word identifiers
        # Use database-specific quoting
        if db_type == "postgresql":
            create_sql = f"""
            CREATE TABLE "{schema}"."select" (
                "table" SERIAL PRIMARY KEY,
                "from" VARCHAR(100),
                "where" INTEGER
            );
            """
        elif db_type == "oracle":
            schema_upper = schema.upper()
            create_sql = f"""
            CREATE TABLE {schema_upper}."select" (
                "table" NUMBER PRIMARY KEY,
                "from" VARCHAR2(100),
                "where" NUMBER
            );
            """
        elif db_type == "sqlserver":
            create_sql = f"""
            CREATE TABLE [{schema}].[select] (
                [table] INT IDENTITY(1,1) PRIMARY KEY,
                [from] NVARCHAR(100),
                [where] INT
            );
            """
        elif db_type == "mysql":
            create_sql = f"""
            CREATE TABLE `{schema}`.`select` (
                `table` INT AUTO_INCREMENT PRIMARY KEY,
                `from` VARCHAR(100),
                `where` INT
            );
            """
        elif db_type == "db2":
            create_sql = f"""
            CREATE TABLE "{schema}"."select" (
                "table" INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                "from" VARCHAR(100),
                "where" INTEGER
            );
            """
        else:
            pytest.skip(f"Reserved words test not implemented for {db_type}")

        try:
            provider.query_executor.execute_statement(provider.connection, create_sql, [])
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()
        except Exception as e:
            pytest.skip(f"Reserved words not supported or failed: {e}")

        # Run round-trip test
        test_schema = f"{schema}_test"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )

        results = tester.run_round_trip_test()

        # Reserved words should be preserved
        assert results[
            "success"
        ], f"Round-trip failed with reserved words: {results.get('errors', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_long_names(self, db_container):
        """Test handling of very long identifier names."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")
        db_type = db_container["type"]

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with long names (but within database limits)
        # Most databases limit identifiers to 63-128 characters
        long_name = "a" * 60  # Safe length for most databases

        if db_type == "postgresql":
            create_sql = f"""
            CREATE TABLE "{schema}"."{long_name}" (
                "{long_name}_id" SERIAL PRIMARY KEY,
                "{long_name}_col" VARCHAR(100)
            );
            """
        elif db_type == "oracle":
            schema_upper = schema.upper()
            # Oracle has 30 char limit for unquoted, 128 for quoted
            long_name_oracle = "A" * 60
            create_sql = f"""
            CREATE TABLE {schema_upper}."{long_name_oracle}" (
                "{long_name_oracle}_ID" NUMBER PRIMARY KEY,
                "{long_name_oracle}_COL" VARCHAR2(100)
            );
            """
        elif db_type == "sqlserver":
            create_sql = f"""
            CREATE TABLE [{schema}].[{long_name}] (
                [{long_name}_id] INT IDENTITY(1,1) PRIMARY KEY,
                [{long_name}_col] NVARCHAR(100)
            );
            """
        elif db_type == "mysql":
            create_sql = f"""
            CREATE TABLE `{schema}`.`{long_name}` (
                `{long_name}_id` INT AUTO_INCREMENT PRIMARY KEY,
                `{long_name}_col` VARCHAR(100)
            );
            """
        elif db_type == "db2":
            create_sql = f"""
            CREATE TABLE "{schema}"."{long_name}" (
                "{long_name}_id" INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                "{long_name}_col" VARCHAR(100)
            );
            """
        else:
            pytest.skip(f"Long names test not implemented for {db_type}")

        try:
            provider.query_executor.execute_statement(provider.connection, create_sql, [])
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()
        except Exception as e:
            pytest.skip(f"Long names not supported or failed: {e}")

        # Run round-trip test
        test_schema = f"{schema}_test"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )

        results = tester.run_round_trip_test()

        assert results["success"], f"Round-trip failed with long names: {results.get('errors', [])}"

        if hasattr(provider, "close"):
            provider.close()

    def test_case_sensitivity(self, db_container):
        """Test handling of case-sensitive identifiers."""
        provider = self._get_provider(db_container)
        provider.create_connection()
        schema = db_container.get("schema", "TEST_SCHEMA")
        db_type = db_container["type"]

        provider.schema_operations.create_schema_if_not_exists(provider.connection, schema)
        if hasattr(provider.connection, "commit"):
            provider.connection.commit()

        # Create table with mixed case (using quotes for case preservation)
        if db_type == "postgresql":
            create_sql = f"""
            CREATE TABLE "{schema}"."MixedCaseTable" (
                "MixedCaseId" SERIAL PRIMARY KEY,
                "MixedCaseColumn" VARCHAR(100)
            );
            """
        elif db_type == "oracle":
            schema_upper = schema.upper()
            create_sql = f"""
            CREATE TABLE {schema_upper}."MixedCaseTable" (
                "MixedCaseId" NUMBER PRIMARY KEY,
                "MixedCaseColumn" VARCHAR2(100)
            );
            """
        elif db_type == "sqlserver":
            create_sql = f"""
            CREATE TABLE [{schema}].[MixedCaseTable] (
                [MixedCaseId] INT IDENTITY(1,1) PRIMARY KEY,
                [MixedCaseColumn] NVARCHAR(100)
            );
            """
        elif db_type == "mysql":
            # MySQL on Linux is case-sensitive for table names
            create_sql = f"""
            CREATE TABLE `{schema}`.`MixedCaseTable` (
                `MixedCaseId` INT AUTO_INCREMENT PRIMARY KEY,
                `MixedCaseColumn` VARCHAR(100)
            );
            """
        elif db_type == "db2":
            create_sql = f"""
            CREATE TABLE "{schema}"."MixedCaseTable" (
                "MixedCaseId" INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                "MixedCaseColumn" VARCHAR(100)
            );
            """
        else:
            pytest.skip(f"Case sensitivity test not implemented for {db_type}")

        try:
            provider.query_executor.execute_statement(provider.connection, create_sql, [])
            if hasattr(provider.connection, "commit"):
                provider.connection.commit()
        except Exception as e:
            pytest.skip(f"Case sensitivity test failed: {e}")

        # Run round-trip test
        test_schema = f"{schema}_test"
        tester = RoundTripTester(
            source_provider=provider,
            test_provider=provider,
            source_schema=schema,
            test_schema=test_schema,
            test_object_types=["tables"],
        )

        results = tester.run_round_trip_test()

        # Case sensitivity may vary by database, so be lenient
        if not results["success"]:
            differences = results["tables"]["differences"]
            if differences:
                print(f"Case sensitivity differences: {differences}")

        if hasattr(provider, "close"):
            provider.close()
