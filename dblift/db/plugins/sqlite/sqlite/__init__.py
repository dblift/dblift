"""
SQLite provider module.

This module contains SQLite-specific database operations split into focused components:
- connection_manager.py: SQLite connection management using Python sqlite3
- locking_manager.py: Migration locking functionality using file locks
- query_executor.py: SQL execution and result processing
- schema_operations.py: Schema operations and metadata queries
- history_manager.py: Migration history table management
"""

from .connection_manager import SQLiteConnectionManager
from .history_manager import SQLiteHistoryManager
from .locking_manager import SQLiteLockingManager
from .query_executor import SQLiteQueryExecutor
from .schema_operations import SQLiteSchemaOperations

__all__ = [
    "SQLiteConnectionManager",
    "SQLiteLockingManager",
    "SQLiteQueryExecutor",
    "SQLiteSchemaOperations",
    "SQLiteHistoryManager",
]
