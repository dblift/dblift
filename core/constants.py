"""
Constants used throughout the dblift application.
This file consolidates magic numbers and commonly used values.
"""

# Database default ports
ORACLE_DEFAULT_PORT = 1521

# Time conversions
SECONDS_TO_MILLISECONDS = 1000

# Dblift-managed table names. Shared between the snapshot writer
# (``core.migration.snapshots``) and consumers that need to exclude
# them from user-facing introspection (``db.introspection``) or
# normalise them at the storage layer (CosmosDB provider). Living
# here keeps the constant on the cross-cutting boundary so neither
# package has to import the other.
DBLIFT_SCHEMA_SNAPSHOTS_TABLE = "dblift_schema_snapshots"

# Data sets / Lane B (audited corrections) managed tables.
# The change-set table stores before/after row images using the snapshot codec.
# Per-dataset history tables are named via config (e.g. dblift_data_history_corrections).
DBLIFT_DATA_CHANGE_SET_TABLE = "dblift_data_change_set"

# The audit table is an append-only, hash-chained log of apply/undo events,
# shared across datasets (chained per-dataset). Tamper-evidence for the ledger.
DBLIFT_DATA_AUDIT_TABLE = "dblift_data_audit"

# Default timeout values
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
