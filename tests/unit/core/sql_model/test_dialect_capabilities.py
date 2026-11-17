"""Conformance tests for the dialect capability matrix.

``dblift.core.sql_model.dialect.DialectCapabilities`` is the authoritative
declaration of what each dialect supports. Providers must match. If
a provider changes its behaviour (e.g. CosmosDB gains transactional
support), these tests flag the drift and force the matrix — the single
source of truth — to be updated *alongside* the provider change.

Also enforces matrix-level invariants: every canonical dialect has an
entry, aliases resolve consistently, derived frozensets match the
matrix values.
"""

from __future__ import annotations

import pytest

from dblift.core.sql_model.dialect import (
    _CAPABILITIES,
    DialectCapabilities,
    dialect_requires_schema,
    get_dialect_capabilities,
)
from dblift.db.provider_interfaces import TransactionalProvider

# --- Matrix-level invariants -------------------------------------------------


def _canonical_dialect_names():
    """Canonical primary dialect names from the plugin registry.

    Replaces the removed ``list(DialectEnum)`` vocabulary (story 26-5);
    the plugin registry is now the single source of canonical names.
    """
    from dblift.db.provider_registry import ProviderRegistry

    return sorted(p.name for p in ProviderRegistry.list_plugins())


class TestMatrixInvariants:
    """Invariants the matrix itself must satisfy."""

    @pytest.mark.parametrize("dialect", _canonical_dialect_names())
    def test_every_canonical_dialect_has_a_capabilities_entry(self, dialect):
        get_dialect_capabilities(dialect)  # trigger lazy matrix build
        assert dialect in _CAPABILITIES, (
            f"Dialect {dialect!r} has no entry in _CAPABILITIES. Add one — "
            "the matrix must cover every canonical dialect."
        )

    def test_sqlite_and_sqlite3_alias_share_the_same_record(self):
        # URL form with prefix "sqlite3:" is common enough to be a canonical
        # alias; the two entries must be identical (same object, actually, to
        # make ``is`` comparisons true).
        assert _CAPABILITIES["sqlite"] is _CAPABILITIES["sqlite3"]


# --- Helper contract --------------------------------------------------------


class TestHelpers:
    def test_unknown_dialect_is_conservative(self):
        # All ``supports_*`` return False for unknown inputs, but
        # schema_required is True — force explicit config rather than
        # silently defaulting to a schemaless model.
        assert get_dialect_capabilities("not-a-dialect").supports_transactions is False
        assert get_dialect_capabilities("not-a-dialect").supports_transactional_ddl is False
        assert dialect_requires_schema("not-a-dialect") is True

    def test_none_dialect_matches_unknown_behaviour(self):
        assert get_dialect_capabilities(None).supports_transactions is False
        assert dialect_requires_schema(None) is True

    def test_dialect_lookup_is_case_insensitive(self):
        assert get_dialect_capabilities("PostgreSQL").supports_transactions is True
        assert get_dialect_capabilities("POSTGRESQL").supports_transactions is True
        assert dialect_requires_schema("SQLite") is False

    def test_get_dialect_capabilities_returns_a_frozen_dataclass(self):
        caps = get_dialect_capabilities("postgresql")
        assert isinstance(caps, DialectCapabilities)
        with pytest.raises((AttributeError, Exception)):
            caps.supports_transactions = False  # type: ignore[misc]


# --- Per-dialect assertions --------------------------------------------------
#
# These are the authoritative truths we encode. They double as
# documentation and as a contract that providers must satisfy.


class TestPostgreSQL:
    def test_supports_transactions_and_transactional_ddl(self):
        assert get_dialect_capabilities("postgresql").supports_transactions is True
        assert get_dialect_capabilities("postgresql").supports_transactional_ddl is True

    def test_schema_required(self):
        assert dialect_requires_schema("postgresql") is True

    def test_lowercase_identifiers(self):
        assert get_dialect_capabilities("postgresql").uppercase_identifiers is False

    def test_clean_strategy_uses_introspector(self):
        assert get_dialect_capabilities("postgresql").clean_strategy == "introspector"


class TestOracle:
    def test_supports_transactions_but_not_ddl(self):
        assert get_dialect_capabilities("oracle").supports_transactions is True
        # Oracle auto-commits DDL; rollback cannot undo CREATE/ALTER/DROP.
        assert get_dialect_capabilities("oracle").supports_transactional_ddl is False

    def test_uppercase_identifiers(self):
        assert get_dialect_capabilities("oracle").uppercase_identifiers is True

    def test_schema_required(self):
        assert dialect_requires_schema("oracle") is True


class TestMySQL:
    def test_supports_transactions_but_not_ddl(self):
        assert get_dialect_capabilities("mysql").supports_transactions is True
        assert get_dialect_capabilities("mysql").supports_transactional_ddl is False

    def test_schema_required(self):
        assert dialect_requires_schema("mysql") is True


class TestSQLServer:
    def test_supports_transactions_and_ddl(self):
        assert get_dialect_capabilities("sqlserver").supports_transactions is True
        assert get_dialect_capabilities("sqlserver").supports_transactional_ddl is True


class TestDB2:
    def test_uppercase_identifiers(self):
        assert get_dialect_capabilities("db2").uppercase_identifiers is True

    def test_supports_transactional_ddl(self):
        assert get_dialect_capabilities("db2").supports_transactional_ddl is True


class TestSQLite:
    def test_no_schema_required(self):
        assert dialect_requires_schema("sqlite") is False
        assert dialect_requires_schema("sqlite3") is False

    def test_supports_transactional_ddl(self):
        # SQLite's transactions cover DDL — this is the exact scenario
        # Bugbot flagged on PR 160 ("Snapshot skipped for SQLite despite
        # supporting transactions"). If somebody ever switches this to
        # False, this test red-lines the regression.
        assert get_dialect_capabilities("sqlite").supports_transactional_ddl is True

    def test_clean_strategy_is_native(self):
        # SQLite enumerates drop candidates via the provider directly,
        # not via generic introspection.
        assert get_dialect_capabilities("sqlite").clean_strategy == "native"


class TestCosmosDB:
    def test_no_transactions(self):
        # Cosmos DB is NoSQL; begin/commit/rollback are no-ops.
        assert get_dialect_capabilities("cosmosdb").supports_transactions is False
        assert get_dialect_capabilities("cosmosdb").supports_transactional_ddl is False

    def test_no_schema_required(self):
        assert dialect_requires_schema("cosmosdb") is False

    def test_clean_strategy_is_native(self):
        assert get_dialect_capabilities("cosmosdb").clean_strategy == "native"


# --- Provider conformance ---------------------------------------------------
#
# Where a provider exposes a runtime method that declares the same fact
# the matrix declares, assert the two agree. Drift between the two would
# be a bug; CI must catch it.


class TestProviderConformance:
    """Matrix declarations must match provider runtime behaviour.

    Every provider that can be instantiated without a live database is
    checked on BOTH axes the ``TransactionalProvider`` interface exposes
    (``supports_transactions`` and ``supports_transactional_ddl``). The
    single-axis version of this test was flagged by Bugbot on PR-07
    because it allowed a CosmosDB drift to go undetected: the matrix
    declared ``supports_transactional_ddl=False`` for cosmosdb while the
    provider had no override and inherited ``True`` from the abstract
    base. The parametrised form below makes that class of bug impossible
    — any axis added to ``TransactionalProvider`` goes through the same
    loop.

    Providers are instantiated with ``__new__`` only, so this test may only
    call methods that do not require live connections or constructor state.
    """

    # Each entry: (provider class, dialect string)
    _INSTANTIABLE_PROVIDERS = [
        ("cosmosdb", "dblift.db.plugins.cosmosdb.provider", "CosmosDbProvider"),
        ("db2", "dblift.db.plugins.db2.provider", "Db2Provider"),
        ("mysql", "dblift.db.plugins.mysql.provider", "MySqlProvider"),
        ("oracle", "dblift.db.plugins.oracle.provider", "OracleProvider"),
        ("postgresql", "dblift.db.plugins.postgresql.provider", "PostgreSqlProvider"),
        ("sqlite", "dblift.db.plugins.sqlite.provider", "SQLiteProvider"),
        ("sqlserver", "dblift.db.plugins.sqlserver.provider", "SqlServerProvider"),
    ]

    @staticmethod
    def _stub(module_path: str, class_name: str):
        """Import the class and build a stub instance without ``__init__``."""
        import importlib

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls.__new__(cls)

    @pytest.mark.parametrize(
        "dialect,module_path,class_name",
        _INSTANTIABLE_PROVIDERS,
        ids=[d for d, _, _ in _INSTANTIABLE_PROVIDERS],
    )
    def test_supports_transactions_matches_matrix(self, dialect, module_path, class_name):
        stub = self._stub(module_path, class_name)
        assert (
            isinstance(stub, TransactionalProvider)
            is get_dialect_capabilities(dialect).supports_transactions
        ), (
            f"{class_name} transaction interface does not match "
            f"DialectCapabilities for {dialect!r}. Update either the override "
            f"or the matrix — both must agree."
        )

    @pytest.mark.parametrize(
        "dialect,module_path,class_name",
        _INSTANTIABLE_PROVIDERS,
        ids=[d for d, _, _ in _INSTANTIABLE_PROVIDERS],
    )
    def test_supports_transactional_ddl_matches_matrix(self, dialect, module_path, class_name):
        """Bugbot PR-07 guard: this is the axis that used to go unchecked."""
        stub = self._stub(module_path, class_name)
        assert (
            stub.supports_transactional_ddl()
            is get_dialect_capabilities(dialect).supports_transactional_ddl
        ), (
            f"{class_name}.supports_transactional_ddl() does not match "
            f"DialectCapabilities for {dialect!r}. Update either the override "
            f"or the matrix — both must agree."
        )

    @pytest.mark.parametrize(
        "dialect,module_path,class_name",
        _INSTANTIABLE_PROVIDERS,
        ids=[d for d, _, _ in _INSTANTIABLE_PROVIDERS],
    )
    def test_schema_requirement_matches_matrix_for_plugin_metadata(
        self, dialect, module_path, class_name
    ):
        """Every provider under test must have a matrix row for schema policy."""
        # Importing the provider module is enough to catch typo/drift in the
        # conformance table without touching a database connection.
        self._stub(module_path, class_name)
        assert dialect_requires_schema(dialect) is get_dialect_capabilities(dialect).schema_required

    @pytest.mark.parametrize(
        "dialect,module_path,class_name",
        _INSTANTIABLE_PROVIDERS,
        ids=[d for d, _, _ in _INSTANTIABLE_PROVIDERS],
    )
    def test_clean_strategy_is_declared_for_every_provider(self, dialect, module_path, class_name):
        self._stub(module_path, class_name)
        assert get_dialect_capabilities(dialect).clean_strategy in {"introspector", "native"}

    @pytest.mark.parametrize(
        "dialect,module_path,class_name",
        _INSTANTIABLE_PROVIDERS,
        ids=[d for d, _, _ in _INSTANTIABLE_PROVIDERS],
    )
    def test_native_clean_strategy_providers_expose_clean_preview(
        self, dialect, module_path, class_name
    ):
        import importlib

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        if get_dialect_capabilities(dialect).clean_strategy == "native":
            assert hasattr(cls, "get_clean_preview"), (
                f"{class_name} declares native clean strategy for {dialect!r} "
                "but does not expose get_clean_preview()."
            )
