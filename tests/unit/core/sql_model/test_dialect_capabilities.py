"""Conformance tests for the dialect capability matrix.

``core.sql_model.dialect.DialectCapabilities`` is the authoritative
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

from core.sql_model.dialect import (
    _CAPABILITIES,
    SCHEMA_OPTIONAL_DIALECTS,
    SCHEMA_OPTIONAL_DIALECTS_FROM_MATRIX,
    DialectCapabilities,
    DialectEnum,
    dialect_clean_strategy,
    dialect_requires_schema,
    dialect_supports_transactional_ddl,
    dialect_supports_transactions,
    dialect_uses_uppercase_identifiers,
    get_dialect_capabilities,
)

# --- Matrix-level invariants -------------------------------------------------


class TestMatrixInvariants:
    """Invariants the matrix itself must satisfy."""

    @pytest.mark.parametrize("member", list(DialectEnum))
    def test_every_canonical_dialect_has_a_capabilities_entry(self, member):
        if member is DialectEnum.UNKNOWN:
            pytest.skip("UNKNOWN is handled via the fallback, not the matrix.")
        assert member.value in _CAPABILITIES, (
            f"DialectEnum.{member.name} has no entry in _CAPABILITIES. Add one — "
            "the matrix must cover every canonical dialect."
        )

    def test_sqlite_and_sqlite3_alias_share_the_same_record(self):
        # URL form with prefix "sqlite3:" is common enough to be a canonical
        # alias; the two entries must be identical (same object, actually, to
        # make ``is`` comparisons true).
        assert _CAPABILITIES["sqlite"] is _CAPABILITIES["sqlite3"]

    def test_schema_optional_derived_matches_legacy_frozenset(self):
        # The legacy SIMP-37 frozenset must match what the matrix produces.
        assert SCHEMA_OPTIONAL_DIALECTS == SCHEMA_OPTIONAL_DIALECTS_FROM_MATRIX


# --- Helper contract --------------------------------------------------------


class TestHelpers:
    def test_unknown_dialect_is_conservative(self):
        # All ``supports_*`` return False for unknown inputs, but
        # schema_required is True — force explicit config rather than
        # silently defaulting to a schemaless model.
        assert dialect_supports_transactions("not-a-dialect") is False
        assert dialect_supports_transactional_ddl("not-a-dialect") is False
        assert dialect_requires_schema("not-a-dialect") is True

    def test_none_dialect_matches_unknown_behaviour(self):
        assert dialect_supports_transactions(None) is False
        assert dialect_requires_schema(None) is True

    def test_dialect_lookup_is_case_insensitive(self):
        assert dialect_supports_transactions("PostgreSQL") is True
        assert dialect_supports_transactions("POSTGRESQL") is True
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
        assert dialect_supports_transactions("postgresql") is True
        assert dialect_supports_transactional_ddl("postgresql") is True

    def test_schema_required(self):
        assert dialect_requires_schema("postgresql") is True

    def test_lowercase_identifiers(self):
        assert dialect_uses_uppercase_identifiers("postgresql") is False

    def test_clean_strategy_uses_introspector(self):
        assert dialect_clean_strategy("postgresql") == "introspector"


class TestOracle:
    def test_supports_transactions_but_not_ddl(self):
        assert dialect_supports_transactions("oracle") is True
        # Oracle auto-commits DDL; rollback cannot undo CREATE/ALTER/DROP.
        assert dialect_supports_transactional_ddl("oracle") is False

    def test_uppercase_identifiers(self):
        assert dialect_uses_uppercase_identifiers("oracle") is True

    def test_schema_required(self):
        assert dialect_requires_schema("oracle") is True


class TestMySQL:
    def test_supports_transactions_but_not_ddl(self):
        assert dialect_supports_transactions("mysql") is True
        assert dialect_supports_transactional_ddl("mysql") is False

    def test_schema_required(self):
        assert dialect_requires_schema("mysql") is True


class TestSQLServer:
    def test_supports_transactions_and_ddl(self):
        assert dialect_supports_transactions("sqlserver") is True
        assert dialect_supports_transactional_ddl("sqlserver") is True


class TestDB2:
    def test_uppercase_identifiers(self):
        assert dialect_uses_uppercase_identifiers("db2") is True

    def test_supports_transactional_ddl(self):
        assert dialect_supports_transactional_ddl("db2") is True


class TestSQLite:
    def test_no_schema_required(self):
        assert dialect_requires_schema("sqlite") is False
        assert dialect_requires_schema("sqlite3") is False

    def test_supports_transactional_ddl(self):
        # SQLite's transactions cover DDL — this is the exact scenario
        # Bugbot flagged on PR 160 ("Snapshot skipped for SQLite despite
        # supporting transactions"). If somebody ever switches this to
        # False, this test red-lines the regression.
        assert dialect_supports_transactional_ddl("sqlite") is True

    def test_clean_strategy_is_native(self):
        # SQLite enumerates drop candidates via the provider directly,
        # not via generic introspection.
        assert dialect_clean_strategy("sqlite") == "native"


class TestCosmosDB:
    def test_no_transactions(self):
        # Cosmos DB is NoSQL; begin/commit/rollback are no-ops.
        assert dialect_supports_transactions("cosmosdb") is False
        assert dialect_supports_transactional_ddl("cosmosdb") is False

    def test_no_schema_required(self):
        assert dialect_requires_schema("cosmosdb") is False

    def test_clean_strategy_is_native(self):
        assert dialect_clean_strategy("cosmosdb") == "native"


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
        ("cosmosdb", "db.plugins.cosmosdb.provider", "CosmosDbProvider"),
        ("db2", "db.plugins.db2.provider", "Db2Provider"),
        ("mysql", "db.plugins.mysql.provider", "MySqlProvider"),
        ("oracle", "db.plugins.oracle.provider", "OracleProvider"),
        ("postgresql", "db.plugins.postgresql.provider", "PostgreSqlProvider"),
        ("sqlite", "db.plugins.sqlite.provider", "SQLiteProvider"),
        ("sqlserver", "db.plugins.sqlserver.provider", "SqlServerProvider"),
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
        assert stub.supports_transactions() is dialect_supports_transactions(dialect), (
            f"{class_name}.supports_transactions() does not match "
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
        assert stub.supports_transactional_ddl() is dialect_supports_transactional_ddl(dialect), (
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
        assert dialect_clean_strategy(dialect) in {"introspector", "native"}

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
        if dialect_clean_strategy(dialect) == "native":
            assert hasattr(cls, "get_clean_preview"), (
                f"{class_name} declares native clean strategy for {dialect!r} "
                "but does not expose get_clean_preview()."
            )
