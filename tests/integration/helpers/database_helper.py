"""
Database helper utilities for integration tests.

Provides functions to:
- Verify database state
- Execute queries
- Check table/schema existence
- Validate data
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from dblift.config import DbliftConfig
from dblift.core.logger import DbliftLogger, LogFormat, LogLevel
from dblift.db.provider_registry import ProviderRegistry


class DatabaseHelper:
    """Helper for database operations in integration tests."""

    def __init__(self, db_config: Dict[str, Any]):
        """
        Initialize database helper.

        Args:
            db_config: Database container configuration dict
        """
        self.db_config = db_config
        self.db_type = db_config.get("type")
        self._provider = None

    def _get_provider(self):
        """Get or create database provider."""
        if self._provider is None:
            # Build config
            config_dict = self._build_config_dict()
            config = DbliftConfig.from_dict(config_dict)

            # Create a logger for the provider
            logger = DbliftLogger(
                logfile_dir=Path("./logs"),
                format=LogFormat.TEXT,
                level=LogLevel.DEBUG,
                config=config,
            )

            self._provider = ProviderRegistry.create_provider(config, logger)
            self._provider.create_connection()
        return self._provider

    def _build_config_dict(self) -> Dict[str, Any]:
        """Build configuration dictionary from db_config."""
        db_type = self.db_config.get("type")

        # Handle CosmosDB (native, uses Azure SDK)
        if db_type == "cosmosdb":
            return {
                "database": {
                    "type": db_type,
                    "url": self.db_config.get("url", self.db_config.get("account_endpoint")),
                    "account_endpoint": self.db_config.get("account_endpoint"),
                    "account_key": self.db_config.get("account_key"),
                    "database_name": self.db_config.get("database_name"),
                },
                "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
                "logging": {"level": "DEBUG", "file": "dblift_integration.log"},
            }

        # Build database URL based on database type
        if db_type == "sqlserver":
            url = f"mssql+pymssql://{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        elif db_type == "oracle":
            service_or_database = self.db_config.get(
                "service", self.db_config.get("database", "XE")
            )
            url = f"oracle+oracledb://{self.db_config['host']}:{self.db_config['port']}?service_name={service_or_database}"
        elif db_type == "postgresql":
            url = f"postgresql+psycopg://{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        elif db_type == "mysql":
            url = f"mysql+pymysql://{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        elif db_type == "db2":
            url = f"ibm_db_sa://{self.db_config['host']}:{self.db_config['port']}/{self.db_config['database']}"
        else:
            raise ValueError(f"Unsupported database type: {db_type}")

        db_section = {
            "type": db_type,
            "url": url,
            "username": self.db_config["username"],
            "password": self.db_config["password"],
            "schema": self.db_config.get("schema", "TEST_SCHEMA"),
        }
        # Ensure Oracle provider sees service_name/sid as attributes (not only in URL)
        if db_type == "oracle":
            service_or_database = self.db_config.get(
                "service", self.db_config.get("database", "XE")
            )
            db_section["service_name"] = service_or_database

        return {
            "database": db_section,
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_integration.log"},
        }

    def execute_query(self, query: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute a SELECT query and return results.

        Args:
            query: SQL query to execute
            params: Optional query parameters

        Returns:
            List of result rows as dictionaries
        """
        provider = self._get_provider()
        schema = self.db_config.get("schema")
        if schema and hasattr(provider, "set_current_schema"):
            provider.set_current_schema(schema)
        return provider.execute_query(query, params)

    def execute_statement(self, sql: str, params: Optional[List[Any]] = None) -> int:
        """
        Execute a SQL statement (INSERT, UPDATE, DELETE, DDL).

        If SQL contains multiple statements (separated by semicolons), they will be
        executed sequentially.

        Args:
            sql: SQL statement(s) to execute (can contain multiple statements separated by semicolons)
            params: Optional statement parameters

        Returns:
            Number of affected rows (sum of all statements if multiple)
        """
        provider = self._get_provider()
        schema = self.db_config.get("schema", "TEST_SCHEMA")

        # Split SQL using dialect-aware parser to handle multiple statements
        # This is necessary because some databases (like MySQL) can't execute
        # multiple statements in a single executeUpdate() call
        # Use proper parser to handle PL/SQL blocks with internal semicolons
        from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

        db_type = self.db_config.get("type", "postgresql")
        analyzer = SqlAnalyzer(dialect=db_type)
        statements = analyzer.split_statements(sql)

        try:
            total_affected = 0
            for stmt in statements:
                if stmt:  # Skip empty statements
                    affected_rows = provider.execute_statement(stmt, schema, params)
                    total_affected += affected_rows

            if hasattr(provider, "commit_transaction"):
                provider.commit_transaction()
            return total_affected
        except Exception:
            if hasattr(provider, "rollback_transaction"):
                try:
                    provider.rollback_transaction()
                except Exception:
                    pass
            raise

    def table_exists(self, table_name: str, schema: Optional[str] = None) -> bool:
        """
        Check if a table exists in the database.

        Args:
            table_name: Name of the table
            schema: Optional schema name (uses default if not provided)

        Returns:
            True if table exists, False otherwise
        """
        provider = self._get_provider()
        schema = schema or self.db_config.get("schema", "TEST_SCHEMA")

        # Database-specific table existence queries
        if self.db_type == "postgresql":
            query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = ? AND table_name = ?
                )
            """
            result = provider.execute_query(query, [schema, table_name])
            return result[0].get("exists", False) if result else False

        elif self.db_type == "mysql":
            query = """
                SELECT COUNT(*) as cnt FROM information_schema.tables
                WHERE table_schema = ? AND table_name = ?
            """
            result = provider.execute_query(query, [schema, table_name])
            # Handle case sensitivity - some drivers return uppercase column names
            return result[0].get("cnt", result[0].get("CNT", 0)) > 0 if result else False

        elif self.db_type == "sqlserver":
            query = """
                SELECT COUNT(*) as cnt FROM information_schema.tables
                WHERE table_schema = ? AND table_name = ?
            """
            result = provider.execute_query(query, [schema, table_name])
            # Handle case sensitivity - some drivers return uppercase column names
            exists = result[0].get("cnt", result[0].get("CNT", 0)) > 0 if result else False
            if not exists and schema.lower() != "dbo":
                # Fallback: many scripts create in default 'dbo' when unqualified
                fallback = provider.execute_query(query, ["dbo", table_name])
                return fallback[0].get("cnt", fallback[0].get("CNT", 0)) > 0 if fallback else False
            return exists

        elif self.db_type == "oracle":
            # Oracle stores table names exactly as created (case-sensitive if quoted)
            # Try both uppercase (unquoted) and original case (quoted) versions
            # Use UPPER() function in SQL to handle case-insensitive matching
            query = """
                SELECT COUNT(*) as cnt FROM all_tables
                WHERE owner = UPPER(?) AND (table_name = UPPER(?) OR table_name = ?)
            """
            result = provider.execute_query(query, [schema, table_name, table_name])
            # Oracle returns column names in uppercase
            return result[0].get("CNT", result[0].get("cnt", 0)) > 0 if result else False

        elif self.db_type == "db2":
            query = """
                SELECT COUNT(*) as cnt FROM syscat.tables
                WHERE tabschema = ? AND tabname = ?
            """
            result = provider.execute_query(query, [schema.upper(), table_name.upper()])
            # DB2 returns column names in uppercase
            return result[0].get("CNT", result[0].get("cnt", 0)) > 0 if result else False

        elif self.db_type == "cosmosdb":
            # CosmosDB uses containers, not tables
            # Use provider's table_exists method or schema_operations.container_exists
            provider = self._get_provider()
            schema_name = schema or self.db_config.get("schema", "default")
            try:
                # Try provider's table_exists method first (if available)
                if hasattr(provider, "table_exists"):
                    return provider.table_exists(schema_name, table_name)
                # Fallback to schema_operations.container_exists
                elif hasattr(provider, "schema_operations") and hasattr(
                    provider.schema_operations, "container_exists"
                ):
                    return provider.schema_operations.container_exists(table_name)
                else:
                    # Last resort: try to query the container directly
                    query = f"SELECT TOP 1 c.id FROM {table_name} c"
                    provider.execute_query(query)
                    return True
            except Exception:
                return False

        return False

    def schema_exists(self, schema_name: str) -> bool:
        """
        Check if a schema exists in the database.

        Args:
            schema_name: Name of the schema

        Returns:
            True if schema exists, False otherwise
        """
        provider = self._get_provider()

        if self.db_type == "postgresql":
            query = "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = ?)"
            result = provider.execute_query(query, [schema_name])
            return result[0].get("exists", False) if result else False

        elif self.db_type == "mysql":
            query = "SELECT COUNT(*) as cnt FROM information_schema.schemata WHERE schema_name = ?"
            result = provider.execute_query(query, [schema_name])
            return result[0].get("cnt", result[0].get("CNT", 0)) > 0 if result else False

        elif self.db_type == "sqlserver":
            query = "SELECT COUNT(*) as cnt FROM sys.schemas WHERE name = ?"
            result = provider.execute_query(query, [schema_name])
            return result[0].get("cnt", result[0].get("CNT", 0)) > 0 if result else False

        elif self.db_type == "oracle":
            query = "SELECT COUNT(*) as cnt FROM all_users WHERE username = ?"
            result = provider.execute_query(query, [schema_name.upper()])
            # Oracle returns column names in uppercase
            return result[0].get("CNT", result[0].get("cnt", 0)) > 0 if result else False

        elif self.db_type == "db2":
            query = "SELECT COUNT(*) as cnt FROM syscat.schemata WHERE schemaname = ?"
            result = provider.execute_query(query, [schema_name.upper()])
            # DB2 returns column names in uppercase
            return result[0].get("CNT", result[0].get("cnt", 0)) > 0 if result else False

        return False

    def get_table_count(self, table_name: str, schema: Optional[str] = None) -> int:
        """
        Get the number of rows in a table.

        Args:
            table_name: Name of the table
            schema: Optional schema name

        Returns:
            Number of rows in the table
        """
        provider = self._get_provider()
        schema = schema or self.db_config.get("schema", "TEST_SCHEMA")

        # Build qualified table name with database-specific quoting
        if self.db_type == "postgresql":
            qualified_name = f'"{schema}"."{table_name}"'
        elif self.db_type == "mysql":
            qualified_name = f"`{schema}`.`{table_name}`"
        else:
            qualified_name = f"{schema}.{table_name}"

        query = f"SELECT COUNT(*) as cnt FROM {qualified_name}"
        result = provider.execute_query(query)
        # Handle case sensitivity - some drivers return uppercase column names
        return result[0].get("cnt", result[0].get("CNT", 0)) if result else 0

    def cleanup(self):
        """Close database connection and clean up resources."""
        if self._provider:
            try:
                self._provider.close()
            except Exception:
                pass
            self._provider = None


# Convenience functions for tests


def verify_table_exists(
    db_config: Dict[str, Any], table_name: str, schema: Optional[str] = None
) -> bool:
    """
    Verify that a table exists in the database.

    Args:
        db_config: Database configuration
        table_name: Name of the table
        schema: Optional schema name

    Returns:
        True if table exists, False otherwise
    """
    helper = DatabaseHelper(db_config)
    try:
        return helper.table_exists(table_name, schema)
    finally:
        helper.cleanup()


def verify_schema_exists(db_config: Dict[str, Any], schema_name: str) -> bool:
    """
    Verify that a schema exists in the database.

    Args:
        db_config: Database configuration
        schema_name: Name of the schema

    Returns:
        True if schema exists, False otherwise
    """
    helper = DatabaseHelper(db_config)
    try:
        return helper.schema_exists(schema_name)
    finally:
        helper.cleanup()


def get_table_count(
    db_config: Dict[str, Any], table_name: str, schema: Optional[str] = None
) -> int:
    """
    Get the number of rows in a table.

    Args:
        db_config: Database configuration
        table_name: Name of the table
        schema: Optional schema name

    Returns:
        Number of rows in the table
    """
    helper = DatabaseHelper(db_config)
    try:
        return helper.get_table_count(table_name, schema)
    finally:
        helper.cleanup()


def execute_query(
    db_config: Dict[str, Any], query: str, params: Optional[List[Any]] = None
) -> List[Dict[str, Any]]:
    """
    Execute a SELECT query and return results.

    Args:
        db_config: Database configuration
        query: SQL query to execute
        params: Optional query parameters

    Returns:
        List of result rows as dictionaries
    """
    helper = DatabaseHelper(db_config)
    try:
        return helper.execute_query(query, params)
    finally:
        helper.cleanup()


def execute_sql(db_config: Dict[str, Any], sql: str, params: Optional[List[Any]] = None) -> int:
    """
    Execute a SQL statement (INSERT, UPDATE, DELETE, DDL).

    Args:
        db_config: Database configuration
        sql: SQL statement to execute
        params: Optional statement parameters

    Returns:
        Number of affected rows
    """
    helper = DatabaseHelper(db_config)
    try:
        return helper.execute_statement(sql, params)
    finally:
        helper.cleanup()
