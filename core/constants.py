"""
Constants used throughout the dblift application.
This file consolidates magic numbers and commonly used values.
"""

# Database default ports
ORACLE_DEFAULT_PORT = 1521
POSTGRESQL_DEFAULT_PORT = 5432
SQLSERVER_DEFAULT_PORT = 1433
MYSQL_DEFAULT_PORT = 3306

# Time conversions
SECONDS_TO_MILLISECONDS = 1000

# Database field sizes
DB_SCRIPT_NAME_MAX_LENGTH = 1000
DB_TEAM_MAX_LENGTH = 100
DB_DEPLOYMENT_ID_MAX_LENGTH = 100

# Dblift-managed table names. Shared between the snapshot writer
# (``core.migration.snapshots``) and consumers that need to exclude
# them from user-facing introspection (``db.introspection``) or
# normalise them at the storage layer (CosmosDB provider). Living
# here keeps the constant on the cross-cutting boundary so neither
# package has to import the other.
DBLIFT_SCHEMA_SNAPSHOTS_TABLE = "dblift_schema_snapshots"

# Default timeout values
DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30
DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS = 60

# String truncation limits
LOG_STATEMENT_PREVIEW_LENGTH = 50
LOG_CONTENT_PREVIEW_LENGTH = 100


def truncate_sql_for_logging(sql: str, max_length: int = LOG_STATEMENT_PREVIEW_LENGTH) -> str:
    """Truncate SQL statement for logging purposes.

    Args:
        sql: SQL statement to truncate
        max_length: Maximum length before truncation (defaults to LOG_STATEMENT_PREVIEW_LENGTH)

    Returns:
        Full SQL if len <= max_length, otherwise first max_length chars + "..."
    """
    if len(sql) <= max_length:
        return sql
    return f"{sql[:max_length]}..."


# Test values
TEST_PLACEHOLDER_TIME_MS = 100

# Formatting constants
SEPARATOR_LINE_LENGTH = 50
EXTENDED_SEPARATOR_LINE_LENGTH = 60

# Database URL parameter names
URL_PARAM_DATABASE = "database"
URL_PARAM_DATABASE_NAME = "databaseName"
URL_PARAM_USER = "user"
URL_PARAM_USERNAME = "username"
URL_PARAM_PASSWORD = "password"
URL_PARAM_PWD = "pwd"

# Story 26-5: legacy URL pattern constants and container port constants removed
# (no callers). If reintroduced, route through plugin Quirks.

# Default retry values
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 1
