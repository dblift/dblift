"""
Integration test helpers for DBLift.

This package provides helper utilities for integration testing:
- CLI command execution (using production cli/main.py)
- Database operations and validation
- Migration file creation and management
- Concurrency testing utilities
"""

from .cli_runner_direct import (
    CommandResult,
)
from .cli_runner_direct import DBLiftCLIDirect as DBLiftCLI
from .cli_runner_direct import get_cli_version
from .concurrency_helper import (
    ConcurrentExecutionResult,
    ConcurrentExecutor,
    simulate_user_sessions,
)
from .database_helper import (
    DatabaseHelper,
    execute_query,
    get_table_count,
    verify_schema_exists,
    verify_table_exists,
)
from .migration_helper import (
    MigrationHelper,
    create_config,
    create_migration,
    create_repeatable_migration,
    create_undo_migration,
    create_versioned_migration,
)

__all__ = [
    # CLI helpers
    "DBLiftCLI",
    "CommandResult",
    "get_cli_version",
    # Database helpers
    "DatabaseHelper",
    "verify_table_exists",
    "verify_schema_exists",
    "get_table_count",
    "execute_query",
    # Migration helpers
    "MigrationHelper",
    "create_migration",
    "create_config",
    "create_versioned_migration",
    "create_repeatable_migration",
    "create_undo_migration",
    # Concurrency helpers
    "ConcurrentExecutor",
    "ConcurrentExecutionResult",
    "simulate_user_sessions",
]
