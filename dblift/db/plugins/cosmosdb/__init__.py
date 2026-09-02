"""Cosmos DB database provider plugin."""

__plugin_name__ = "cosmosdb"
__plugin_version__ = "1.0.0"
__plugin_description__ = "Azure Cosmos DB provider"
__plugin_dialects__ = ["cosmosdb", "cosmos", "nosql"]
__plugin_transport__ = "native"
__plugin_class__ = "CosmosDbProvider"

from .provider import CosmosDbProvider

__all__ = ["CosmosDbProvider"]
