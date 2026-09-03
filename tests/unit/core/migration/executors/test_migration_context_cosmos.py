"""Tests for MigrationContext properties with CosmosDB provider (story 11-4, AC#2/#3/#4).

Validates that context.db and context.raw_client correctly delegate to
provider.connection_manager attributes, and that dry_run is properly propagated.
"""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.executors.python_executor import MigrationContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cosmos_provider():
    """Return a mock provider simulating CosmosDB with database + client."""
    provider = MagicMock()
    provider.connection_manager = MagicMock()
    provider.connection_manager.database = MagicMock(name="DatabaseProxy")
    provider.connection_manager.client = MagicMock(name="CosmosClient")
    return provider


# ---------------------------------------------------------------------------
# AC#2 — context.db
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMigrationContextDatabase:
    """context.db returns the DatabaseProxy from CosmosDB connection_manager."""

    def test_context_database_returns_cosmos_database_proxy(self):
        provider = _cosmos_provider()
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.db is provider.connection_manager.database

    def test_context_database_none_for_provider_without_connection_manager(self):
        provider = MagicMock(spec=[])  # No attributes at all
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.db is None

    def test_context_database_none_for_connection_manager_without_database_attr(self):
        provider = MagicMock()
        provider.connection_manager = MagicMock(spec=[])  # No database attr
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.db is None


# ---------------------------------------------------------------------------
# AC#3 — context.raw_client
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMigrationContextRawClient:
    """context.raw_client returns the CosmosClient from connection_manager."""

    def test_context_client_returns_cosmos_client(self):
        provider = _cosmos_provider()
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.raw_client is provider.connection_manager.client

    def test_context_raw_client_none_for_provider_without_connection_manager(self):
        provider = MagicMock(spec=[])
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.raw_client is None

    def test_context_raw_client_none_for_connection_manager_without_client_attr(self):
        provider = MagicMock()
        provider.connection_manager = MagicMock(spec=[])
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.raw_client is None


# ---------------------------------------------------------------------------
# AC#4 — dry_run propagation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMigrationContextDryRun:
    """dry_run is correctly propagated to the context."""

    def test_dry_run_true_propagated_to_context(self):
        ctx = MigrationContext(provider=MagicMock(), log=MagicMock(), dry_run=True)
        assert ctx.dry_run is True

    def test_dry_run_false_by_default(self):
        ctx = MigrationContext(provider=MagicMock(), log=MagicMock())
        assert ctx.dry_run is False


# ---------------------------------------------------------------------------
# Full CosmosDB mock — AC#2/#3 combined
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMigrationContextFullCosmosMock:
    """Full CosmosDB provider mock — database and client delegate correctly."""

    def test_context_with_full_cosmos_provider_mock(self):
        provider = _cosmos_provider()
        ctx = MigrationContext(provider=provider, log=MagicMock())
        assert ctx.db is provider.connection_manager.database
        assert ctx.raw_client is provider.connection_manager.client
        assert ctx.db is not None
        assert ctx.raw_client is not None
