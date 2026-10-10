"""
Cosmos DB provider components.

This package contains the modular components for Azure Cosmos DB support.
"""

from .connection_manager import CosmosDbConnectionManager
from .history_manager import CosmosDbHistoryManager
from .locking_manager import CosmosDbLockingManager
from .query_executor import CosmosDbQueryExecutor
from .schema_operations import CosmosDbSchemaOperations

__all__ = [
    "CosmosDbConnectionManager",
    "CosmosDbQueryExecutor",
    "CosmosDbLockingManager",
    "CosmosDbSchemaOperations",
    "CosmosDbHistoryManager",
]
