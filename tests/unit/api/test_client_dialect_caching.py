"""Tests for dialect caching and normalization (story 18-13).

Validates that dialect is normalized to lowercase and cached at initialization
in DBLiftClient, JdbcProvider, and SqlGeneratorFactory.
"""

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── AC#1 — DBLiftClient.dialect cached at __init__ ──────────────────────


@pytest.mark.unit
class TestClientDialectCaching:
    """Tests for DBLiftClient dialect caching (AC#1)."""

    def _make_client(self, provider_dialect="postgresql"):
        """Create a DBLiftClient with a mocked provider."""
        from api.client import DBLiftClient

        provider = MagicMock()
        provider.dialect = provider_dialect
        provider.config = None

        config = MagicMock()
        config.migrations.directory = "/tmp/migrations"
        config.migrations.directories = []

        logger = MagicMock()
        client = DBLiftClient(
            provider=provider,
            migrations_dir="/tmp/migrations",
            config=config,
            logger=logger,
        )
        return client

    def test_dialect_cached_at_init(self):
        """client.dialect is defined after __init__."""
        client = self._make_client()
        assert hasattr(client, "dialect")
        assert isinstance(client.dialect, str)

    def test_dialect_normalized_to_lowercase(self):
        """provider.dialect = 'PostgreSQL' → client.dialect == 'postgresql'."""
        client = self._make_client(provider_dialect="PostgreSQL")
        assert client.dialect == "postgresql"

    def test_get_dialect_called_once_not_on_method_call(self):
        """_get_dialect_for_sql_generation called 1x at init, not when accessing self.dialect."""
        from api.client import DBLiftClient

        provider = MagicMock()
        provider.dialect = "postgresql"
        provider.config = None

        config = MagicMock()
        config.migrations.directory = "/tmp/migrations"
        config.migrations.directories = []

        logger = MagicMock()

        with patch.object(
            DBLiftClient, "_get_dialect_for_sql_generation", return_value="postgresql"
        ) as mock_get:
            client = DBLiftClient(
                provider=provider,
                migrations_dir="/tmp/migrations",
                config=config,
                logger=logger,
            )
            assert mock_get.call_count == 1

            # Accessing self.dialect should NOT trigger another call
            assert client.dialect == "postgresql"
            assert mock_get.call_count == 1

    def test_generate_undo_scripts_dialect_regression(self):
        """generate_undo_script and generate_undo_scripts_batch use client.dialect."""
        from api._client_operations import (
            _generate_undo_script_for_migration,
            generate_undo_scripts_operation,
        )

        undo_generation_source = inspect.getsource(_generate_undo_script_for_migration)
        assert "client.dialect" in undo_generation_source
        assert "_get_dialect_for_sql_generation()" not in undo_generation_source

        batch_source = inspect.getsource(generate_undo_scripts_operation)
        assert "_get_dialect_for_sql_generation()" not in batch_source
        assert "client.generate_undo_script(" not in batch_source
        assert "_generate_undo_script_for_migration(" in batch_source

    def test_generate_undo_scripts_parses_each_migration_once(self, tmp_path, monkeypatch):
        from api._client_operations import generate_undo_scripts_operation
        from api.events import EventEmitter
        from core.migration import migration as migration_module

        migration_file = tmp_path / "V1__create_users.sql"
        migration_file.write_text("CREATE TABLE users (id int);\n", encoding="utf-8")

        original_migration = migration_module.Migration
        migration_calls = []

        def counting_migration(*args, **kwargs):
            migration_calls.append(args[0] if args else kwargs.get("script_path"))
            return original_migration(*args, **kwargs)

        monkeypatch.setattr(migration_module, "Migration", counting_migration)

        client = MagicMock()
        client.logger = MagicMock()
        client.dialect = "postgresql"
        client.events = EventEmitter()

        results = generate_undo_scripts_operation(
            client,
            migration_paths=[migration_file],
            overwrite=True,
        )

        assert len(results) == 1
        assert results[0].success is True
        assert migration_calls == [migration_file]

    def test_generate_undo_scripts_generic_exception_emits_failed_event(self, tmp_path):
        from api import _client_operations as operations
        from api.events import EventType

        migration_file = tmp_path / "V1__create_users.sql"
        migration_file.write_text("CREATE TABLE users (id int);\n", encoding="utf-8")

        client = MagicMock()
        client.logger = MagicMock()
        client.dialect = "postgresql"
        client.events = MagicMock()

        with patch.object(
            operations,
            "_prepare_undo_generation_migration",
            side_effect=RuntimeError("generator unavailable"),
        ):
            results = operations.generate_undo_scripts_operation(
                client,
                migration_paths=[migration_file],
            )

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error_message == ("Failed to generate undo script: generator unavailable")

        failed_calls = [
            call
            for call in client.events.emit.call_args_list
            if call.args[0] == EventType.MIGRATION_FAILED
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0].args[1] == {
            "error": "Failed to generate undo script: generator unavailable",
            "operation": "generate_undo_script",
        }

    def test_generate_undo_scripts_file_exists_error_keeps_clean_message(self, tmp_path):
        from api import _client_operations as operations
        from api.events import EventType

        migration_file = tmp_path / "V1__create_users.sql"
        migration_file.write_text("CREATE TABLE users (id int);\n", encoding="utf-8")

        client = MagicMock()
        client.logger = MagicMock()
        client.dialect = "postgresql"
        client.events = MagicMock()

        error_message = "Undo script already exists: U1__create_users.sql"
        with (
            patch.object(
                operations,
                "_prepare_undo_generation_migration",
                return_value=MagicMock(),
            ),
            patch.object(
                operations,
                "_generate_undo_script_for_migration",
                side_effect=FileExistsError(error_message),
            ),
        ):
            results = operations.generate_undo_scripts_operation(
                client,
                migration_paths=[migration_file],
            )

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error_message == error_message

        failed_calls = [
            call
            for call in client.events.emit.call_args_list
            if call.args[0] == EventType.MIGRATION_FAILED
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0].args[1] == {
            "error": error_message,
            "operation": "generate_undo_script",
        }

    def test_generate_undo_script_overwritten_uses_generator_path(self, tmp_path):
        from api._client_operations import generate_undo_script_operation
        from api.events import EventEmitter

        migration_file = tmp_path / "V1_2__create_users.sql"
        migration_file.write_text("CREATE TABLE users (id int);\n", encoding="utf-8")
        undo_file = tmp_path / "U1_2__create_users.sql"
        undo_file.write_text("-- old undo\n", encoding="utf-8")

        client = MagicMock()
        client.logger = MagicMock()
        client.dialect = "postgresql"
        client.events = EventEmitter()

        result = generate_undo_script_operation(
            client,
            migration_path=migration_file,
            overwrite=True,
        )

        assert result.success is True
        assert result.undo_script_path == str(undo_file)
        assert result.overwritten is True

    def test_generate_undo_script_value_error_result_keeps_migration_path(self, tmp_path):
        from api import _client_operations as operations
        from api.events import EventEmitter

        migration_file = tmp_path / "not_versioned.sql"
        migration_file.write_text("CREATE TABLE users (id int);\n", encoding="utf-8")

        client = MagicMock()
        client.logger = MagicMock()
        client.dialect = "postgresql"
        client.events = EventEmitter()

        result = operations.generate_undo_script_operation(
            client,
            migration_path=migration_file,
        )

        assert result.success is False
        assert result.migration_path == str(migration_file)
        assert result.error_message.startswith("File is not a versioned migration")


# ── AC#2 — BaseProvider canonical dialect key fallback ───────────────────


@pytest.mark.unit
class TestBaseProviderDialect:
    """Tests for native provider dialect metadata (AC#2)."""

    def test_default_canonical_dialect_key_is_empty(self):
        from db.base_provider import BaseProvider

        assert BaseProvider.canonical_dialect_key == ""

    def test_postgresql_provider_declares_canonical_dialect_key(self):
        from db.plugins.postgresql.provider import PostgreSqlProvider

        assert PostgreSqlProvider.canonical_dialect_key == "postgresql"


# ── AC#3 — SqlGeneratorFactory case-insensitive ──────────────────────────


@pytest.mark.unit
class TestGeneratorFactoryCaseInsensitive:
    """Tests for SqlGeneratorFactory case-insensitive dialect (AC#3)."""

    def test_generator_factory_create_case_insensitive(self):
        """create('PostgreSQL') returns same type as create('postgresql')."""
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        gen_upper = SqlGeneratorFactory.create("PostgreSQL")
        gen_lower = SqlGeneratorFactory.create("postgresql")
        assert type(gen_upper) is type(gen_lower)

    def test_generator_factory_is_supported_case_insensitive(self):
        """is_supported('POSTGRESQL') == is_supported('postgresql')."""
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        # Ensure defaults are registered
        SqlGeneratorFactory.create("postgresql")
        assert SqlGeneratorFactory.is_supported("POSTGRESQL") is True
        assert SqlGeneratorFactory.is_supported("postgresql") is True
