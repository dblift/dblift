"""Entry-point declaration for the Cosmos DB plugin (Epic 26 story 26-12)."""

from __future__ import annotations

from db.plugins.cosmosdb.config import CosmosDbConfig
from db.plugins.cosmosdb.provider import CosmosDbProvider
from db.plugins.cosmosdb.quirks import CosmosdbQuirks
from db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="cosmosdb",
    version="1.0.0",
    description="Azure Cosmos DB provider",
    dialects=["cosmosdb", "cosmos", "nosql"],
    provider_class=CosmosDbProvider,
    transport="native",
    quirks_class=CosmosdbQuirks,
    config_class=CosmosDbConfig,
)
