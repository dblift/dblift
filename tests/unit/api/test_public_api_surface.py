"""Tests pinning the documented public API surface.

``docs/semver-policy.md`` § 1 enumerates the names downstream users may
import. Changes to that surface trigger a MINOR (additions) or MAJOR
(removals / renames) version bump. These tests freeze the surface in
CI so a change cannot land without being noticed.

They are intentionally minimalist — one assertion per named public
symbol that the import works and the type is what the doc claims.
Adding a new public symbol means:

    1. Export it in the module's __all__.
    2. Add it to docs/semver-policy.md § 1.
    3. Add it here.

Dropping one of the three steps fails CI, not human review.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_api_package_has_py_typed_marker():
    """PEP 561: downstream type checkers look for ``api/py.typed``.

    If this file vanishes (or the packaging config stops shipping it),
    downstream IDEs and mypy runs on consumer projects silently lose
    dblift's type information. Pin the marker's existence.
    """
    marker = Path(__file__).resolve().parents[3] / "api" / "py.typed"
    assert marker.is_file(), "api/py.typed marker missing. See PEP 561 + docs/semver-policy.md."


class TestApiPackageSurface:
    """``from api import ...`` — the top-level entry point."""

    def test_dbliftclient_is_a_class(self):
        from api import DBLiftClient

        assert isinstance(DBLiftClient, type)

    def test_event_emitter_is_importable(self):
        from api import EventEmitter

        assert EventEmitter is not None

    def test_event_type_is_importable(self):
        from api import EventType

        assert EventType is not None

    def test_all_lists_exactly_three_symbols(self):
        """``api.__all__`` is the contract. Additions are MINOR bumps
        (document in semver-policy.md + CHANGELOG); removals are MAJOR."""
        import api

        assert set(api.__all__) == {
            "DBLiftClient",
            "EventEmitter",
            "EventType",
        }


class TestConfigPackageSurface:
    """``from config import ...`` — configuration loading."""

    def test_dblift_config_is_a_class(self):
        from config import DbliftConfig

        assert isinstance(DbliftConfig, type)

    def test_database_config_is_a_class(self):
        from config import DatabaseConfig

        assert isinstance(DatabaseConfig, type)

    def test_load_config_is_callable(self):
        from config import load_config

        assert callable(load_config)

    def test_all_lists_exactly_three_symbols(self):
        import config

        assert set(config.__all__) == {"DatabaseConfig", "DbliftConfig", "load_config"}


class TestMigrationTypeSurface:
    """The documented ``from core.migration import ...`` public path.

    These tests use the documented public path (`core.migration`), NOT
    the internal implementation module (`core.migration.migration`).
    Bugbot on PR-14 flagged that the prior version imported from the
    internal path and therefore would have passed even if
    ``core/migration/__init__.py`` stopped re-exporting the symbols —
    defeating the purpose of surface pinning.
    """

    def test_migration_type_is_importable_via_public_path(self):
        from core.migration import MigrationType

        assert isinstance(MigrationType, type)

    def test_versioned_script_types_is_frozenset_via_public_path(self):
        from core.migration import VERSIONED_SCRIPT_TYPES

        assert isinstance(VERSIONED_SCRIPT_TYPES, frozenset)

    def test_type_match_helpers_are_importable_via_public_path(self):
        from core.migration import is_migration_type, is_versioned, migration_type_name

        assert callable(is_migration_type)
        assert callable(is_versioned)
        assert callable(migration_type_name)

    def test_migration_class_is_importable_via_public_path(self):
        from core.migration import Migration

        assert isinstance(Migration, type)

    def test_all_lists_the_documented_symbols(self):
        """``core.migration.__all__`` is the contract enumeration."""
        import core.migration

        assert set(core.migration.__all__) == {
            "AppliedMigration",
            "Migration",
            "MigrationResource",
            "MigrationType",
            "ResolvedMigration",
            "VERSIONED_SCRIPT_TYPES",
            "is_migration_type",
            "is_versioned",
            "migration_type_name",
        }

    def test_migration_type_members_are_stable(self):
        """Enum members are part of the public contract. Adding is MINOR;
        removing or renaming is MAJOR."""
        from core.migration import MigrationType

        expected = {
            "SQL",
            "PYTHON",
            "REPEATABLE",
            "UNDO_SQL",
            "BASELINE",
            "CALLBACK",
            "DELETE",
            "UNKNOWN",
        }
        assert {m.name for m in MigrationType} == expected

    @pytest.mark.parametrize(
        "symbol_name,impl_module",
        [
            # Re-exported from core.migration.migration
            ("AppliedMigration", "core.migration.migration"),
            ("Migration", "core.migration.migration"),
            ("MigrationResource", "core.migration.migration"),
            ("MigrationType", "core.migration.migration"),
            ("ResolvedMigration", "core.migration.migration"),
            ("VERSIONED_SCRIPT_TYPES", "core.migration.migration"),
            # Re-exported from core.migration._type_match
            ("is_migration_type", "core.migration._type_match"),
            ("is_versioned", "core.migration._type_match"),
            ("migration_type_name", "core.migration._type_match"),
        ],
    )
    def test_public_path_and_implementation_path_return_same_objects(
        self, symbol_name, impl_module
    ):
        """Re-export must forward the same object, not a copy / re-binding.

        Parameterised over every symbol in ``core.migration.__all__`` so a
        future re-export added to the package's ``__init__`` forces the
        contributor to add a row here — silently re-binding a symbol
        (e.g. ``from core.migration.migration import MigrationType; MigrationType = ...``
        elsewhere) would break ``isinstance`` checks on user code that
        crossed import boundaries and fail this test.
        """
        import importlib

        public_module = importlib.import_module("core.migration")
        implementation_module = importlib.import_module(impl_module)

        public_obj = getattr(public_module, symbol_name)
        impl_obj = getattr(implementation_module, symbol_name)

        assert public_obj is impl_obj, (
            f"core.migration.{symbol_name} is not the same object as "
            f"{impl_module}.{symbol_name}. Re-exports must be direct "
            f"``from X import Y`` aliases, not re-bindings."
        )


class TestLoggerPackageSurface:
    """The documented ``from core.logger import ...`` public path."""

    EXPECTED_EXPORTS = {
        "AbstractLog",
        "BaselineResult",
        "CleanResult",
        "ConsoleLog",
        "DbliftLogger",
        "DiffResult",
        "FileLog",
        "HtmlFormatter",
        "InfoResult",
        "JsonFormatter",
        "Log",
        "LogFactory",
        "LogFormat",
        "LogLevel",
        "MigrateResult",
        "MigrationInfo",
        "MultiLog",
        "NullLog",
        "OperationResult",
        "OutputFormatter",
        "OutputFormatterFactory",
        "RepairResult",
        "ValidateResult",
    }

    def test_all_lists_the_documented_logger_symbols(self):
        import core.logger

        assert set(core.logger.__all__) == self.EXPECTED_EXPORTS

    @pytest.mark.parametrize("symbol_name", sorted(EXPECTED_EXPORTS))
    def test_logger_public_symbol_is_importable(self, symbol_name):
        import core.logger

        assert getattr(core.logger, symbol_name) is not None


class TestDBLiftClientPublicMethods:
    """The public methods on DBLiftClient."""

    EXPECTED_PUBLIC_METHODS = frozenset(
        {
            "migrate",
            "info",
            "validate",
            "undo",
            "generate_undo_script",
            "generate_undo_scripts",
            "clean",
            "baseline",
            "repair",
            "import_flyway",
            # Construction helpers
            "from_config",
            "from_config_file",
            "from_sqlalchemy",
            # Teardown
            "close",
        }
    )

    def test_every_expected_method_exists(self):
        from api import DBLiftClient

        for name in self.EXPECTED_PUBLIC_METHODS:
            assert hasattr(DBLiftClient, name), (
                f"DBLiftClient.{name} is part of the documented public API "
                f"but is missing. Check api/client.py and docs/semver-policy.md."
            )

    def test_no_unexpected_public_method_creeps_in(self):
        """Any new public (non-underscore) method on DBLiftClient must be
        added to EXPECTED_PUBLIC_METHODS here AND to docs/semver-policy.md.
        This test red-lines silent surface growth."""
        from api import DBLiftClient

        actual = {
            name
            for name in dir(DBLiftClient)
            if not name.startswith("_") and callable(getattr(DBLiftClient, name))
        }
        extra = actual - self.EXPECTED_PUBLIC_METHODS
        assert not extra, (
            f"Unexpected public method(s) on DBLiftClient: {sorted(extra)}. "
            f"If intentional, add to EXPECTED_PUBLIC_METHODS and "
            f"docs/semver-policy.md (MINOR bump). If internal, prefix with "
            f"underscore."
        )

    # Operations whose body issues SQL or migration-script work — every one
    # must be decorated with ``_with_client_emitter`` so that core-layer
    # ``emit_event`` calls land on the *client's* emitter rather than the
    # process-wide default. ``from_config*``/``from_sqlalchemy``/``close``
    # are excluded because they don't run a SQL operation, only construction
    # or teardown.
    EXPECTED_DECORATED_OPERATIONS = frozenset(
        {
            "migrate",
            "info",
            "validate",
            "undo",
            "generate_undo_script",
            "generate_undo_scripts",
            "clean",
            "baseline",
            "repair",
            "import_flyway",
        }
    )

    def test_every_operation_binds_client_emitter(self):
        """Cursor-bot finding (api/client.py:141): the docstring claims every
        public operation binds the client's emitter, but only ``migrate`` and
        ``undo`` did. The fix decorates each operation with
        ``@_with_client_emitter``. This test makes that the structural rule —
        adding a public operation without the decorator fails CI here.
        """
        from unittest.mock import patch

        from api import DBLiftClient
        from api import client as client_module

        for name in self.EXPECTED_DECORATED_OPERATIONS:
            method = getattr(DBLiftClient, name)

            calls: list[object] = []

            def _spy(emitter, *, _calls=calls):
                _calls.append(emitter)
                from contextlib import nullcontext

                return nullcontext()

            sentinel = object()
            stub = DBLiftClient.__new__(DBLiftClient)
            stub.events = sentinel  # type: ignore[attr-defined]

            with patch.object(client_module, "use_client_emitter", side_effect=_spy):
                try:
                    method(stub)  # type: ignore[arg-type]
                except Exception:
                    # The method bodies will fail (no executor wired up); we
                    # only care that the decorator fired *before* the body.
                    pass

            assert calls, (
                f"DBLiftClient.{name} did not call use_client_emitter — "
                f"it is missing @_with_client_emitter. Per-client event "
                f"isolation is broken for this operation."
            )
            assert calls[0] is sentinel, (
                f"DBLiftClient.{name} called use_client_emitter but with "
                f"{calls[0]!r}, not the client's own ``self.events``."
            )


class TestClientInfoDisplayHuman:
    """OBS-04: ``client.info()`` must not print to stdout by default.

    Programmatic API consumers want a clean ``InfoResult`` and rely on
    capturing real stdout for their own output. The CLI handler explicitly
    opts back into the human-readable Rich table via ``display_human=True``.
    """

    def _stub_client(self, mock_executor):
        from unittest.mock import MagicMock

        from api.client import DBLiftClient

        client = DBLiftClient.__new__(DBLiftClient)
        client.events = MagicMock()
        client.events.emit = MagicMock()
        client._migrations_dir = None
        client.executor = mock_executor
        return client

    def test_default_passes_display_human_false_to_executor(self):
        """Default API call sends display_human=False — no stdout side effect."""
        from unittest.mock import MagicMock, patch

        from core.logger.results import InfoResult

        mock_executor = MagicMock()
        mock_executor.info.return_value = InfoResult()
        client = self._stub_client(mock_executor)

        with patch.object(client, "_get_scripts_dir", return_value=None):
            client.info()

        kwargs = mock_executor.info.call_args.kwargs
        assert kwargs.get("display_human") is False, (
            "client.info() must default to display_human=False so the API path "
            "does not print to stdout (OBS-04 regression)."
        )

    def test_explicit_display_human_true_is_forwarded(self):
        """CLI handler sets display_human=True; the value must reach executor."""
        from unittest.mock import MagicMock, patch

        from core.logger.results import InfoResult

        mock_executor = MagicMock()
        mock_executor.info.return_value = InfoResult()
        client = self._stub_client(mock_executor)

        with patch.object(client, "_get_scripts_dir", return_value=None):
            client.info(display_human=True)

        kwargs = mock_executor.info.call_args.kwargs
        assert kwargs.get("display_human") is True


class TestClientConfigDirectoryShape:
    def test_from_config_does_not_mutate_shared_config_migrations_dir(self):
        from api.client import DBLiftClient
        from config.dblift_config import DbliftConfig

        config = DbliftConfig.from_dict(
            {
                "database": {
                    "url": "sqlite:////tmp/test.db",
                    "schema": "main",
                },
                "migrations": {
                    "directory": "/tmp/base",
                },
            }
        )

        with patch(
            "api._client_factory.ProviderRegistry.create_provider",
            return_value=MagicMock(),
        ):
            client_a = DBLiftClient.from_config(config, migrations_dir="/tmp/client_a")
            client_b = DBLiftClient.from_config(config, migrations_dir="/tmp/client_b")

        assert config.migrations.directory == "/tmp/base"
        assert str(client_a._get_scripts_dir()) == "/tmp/client_a"
        assert str(client_b._get_scripts_dir()) == "/tmp/client_b"

    def test_from_config_normalizes_dict_migration_directories_for_client_ctor(self):
        from api._client_factory import client_from_config
        from config.dblift_config import DbliftConfig

        config = DbliftConfig.from_dict(
            {
                "database": {
                    "url": "sqlite:////tmp/test.db",
                    "schema": "main",
                },
                "migrations": {
                    "directory": "/tmp/base",
                    "directories": [{"path": "/tmp/extra", "recursive": True}],
                },
            }
        )

        class CapturingClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        with patch(
            "api._client_factory.ProviderRegistry.create_provider",
            return_value=MagicMock(),
        ):
            client = client_from_config(config, client_cls=CapturingClient)

        assert client.kwargs["migrations_dir"] == ["/tmp/extra"]

    def test_normalize_migrations_dirs_clears_stale_dict_entries(self):
        from api._client_factory import normalize_migrations_dirs
        from config.dblift_config import DbliftConfig

        config = DbliftConfig.from_dict(
            {
                "database": {
                    "url": "sqlite:////tmp/test.db",
                    "schema": "main",
                },
                "migrations": {
                    "directories": [{"path": "/tmp/extra", "recursive": True}],
                },
            }
        )

        normalize_migrations_dirs(config, ["/tmp/extra"])

        assert config.migrations.directory == "/tmp/extra"
        assert config.migrations.directories == []


class TestInfoResultCompatibilityAliases:
    def test_exposes_applied_and_pending_migration_lists(self):
        from core.logger.results import InfoResult, MigrationInfo

        result = InfoResult()
        applied = MigrationInfo(script="V1__init.sql", version="1", status="SUCCESS")
        pending = MigrationInfo(script="V2__next.sql", version="2", status="PENDING")
        result.add_migration(applied)
        result.add_migration(pending)

        assert result.applied_migrations == [applied]
        assert result.pending_migrations == [pending]
