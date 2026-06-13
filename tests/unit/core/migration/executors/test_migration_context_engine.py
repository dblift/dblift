"""Tests for enriched MigrationContext (engine, connection, schema, placeholders, config)."""

from unittest.mock import MagicMock

import pytest

from core.migration.executors.python_executor import MigrationContext


def _make_sqlite_provider_with_engine():
    provider = MagicMock()
    provider.engine = MagicMock(name="fake-engine")
    provider.connection = MagicMock(name="fake-conn")
    return provider


def test_migration_context_exposes_engine_and_connection():
    provider = _make_sqlite_provider_with_engine()
    cfg = MagicMock()
    cfg.database = MagicMock()
    cfg.database.schema = "app"
    ctx = MigrationContext(
        provider=provider,
        log=MagicMock(),
        config=cfg,
        placeholders={"schema": "app"},
    )
    assert ctx.engine is provider.engine
    assert ctx.connection is provider.connection
    assert ctx.schema == "app"
    assert ctx.placeholders["schema"] == "app"
    assert ctx.config is cfg


def test_migration_context_engine_none_for_non_sqlalchemy_provider():
    provider = MagicMock()
    # Explicitly set to None to simulate a provider without real engine/connection
    # (plain MagicMock auto-vivifies attribute access to another mock).
    provider.engine = None
    provider.connection = None
    ctx = MigrationContext(provider=provider, log=MagicMock())
    assert ctx.engine is None
    assert ctx.connection is None
    assert ctx.schema is None
