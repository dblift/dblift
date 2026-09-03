"""Entry-point declaration for the Cosmos DB plugin (Epic 26 story 26-12)."""

from __future__ import annotations

from dblift.db.plugins.cosmosdb.config import CosmosDbConfig
from dblift.db.plugins.cosmosdb.provider import CosmosDbProvider
from dblift.db.plugins.cosmosdb.quirks import CosmosdbQuirks
from dblift.db.provider_registry import PluginInfo

PLUGIN: PluginInfo = PluginInfo(
    name="cosmosdb",
    version="1.0.0",
    description="Azure Cosmos DB provider",
    dialects=["cosmosdb", "cosmos", "nosql"],
    provider_class=CosmosDbProvider,
    transport="native",
    quirks_class=CosmosdbQuirks,
    config_class=CosmosDbConfig,
    # ``azure.cosmos`` is what ``cosmosdb/_sdk.py`` and ``connection_manager.py``
    # import, so its absence is what makes the plugin unusable; ``cosmosdb`` is the
    # pyproject extra that installs both ``azure-cosmos`` and ``azure-identity``.
    # The field names one module, and ``azure-identity`` is a second distribution
    # used only on the managed-identity auth path, so ``azure.cosmos`` is the check
    # that is right for every user: no Cosmos DB connection works without it.
    native_driver_module="azure.cosmos",
    install_extra="cosmosdb",
)
