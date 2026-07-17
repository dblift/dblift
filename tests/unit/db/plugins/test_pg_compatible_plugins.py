"""PostgreSQL-compatible distribution plugins.

Includes Neon, Supabase, Aurora PostgreSQL, AlloyDB, YugabyteDB, TimescaleDB,
Citus, CockroachDB, and Redshift.

Each is a thin plugin that reuses the PostgreSQL provider/config/URL-builder/
driver and only carries a distinct identity + a quirks subclass. The tests pin
the reuse contract and — critically — that every PG-derived quirks resets
``is_ansi_reference_dialect`` to ``False`` so the single-owner invariant in
``ProviderRegistry.reference_dialect_name`` still holds.
"""

import importlib

import pytest

from db.plugins.postgresql.provider import PostgreSqlProvider
from db.plugins.postgresql.quirks import PostgresqlQuirks
from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url as build_postgresql_url
from db.plugins.redshift.sqlalchemy_url import build_sqlalchemy_url as build_redshift_url
from db.provider_registry import ProviderRegistry

# (plugin dir/module, canonical dialect name, provider cls, quirks cls)
PG_COMPATIBLE = [
    ("neon", "neon", "NeonProvider", "NeonQuirks"),
    ("supabase", "supabase", "SupabaseProvider", "SupabaseQuirks"),
    (
        "aurora_postgresql",
        "aurora-postgresql",
        "AuroraPostgresqlProvider",
        "AuroraPostgresqlQuirks",
    ),
    ("alloydb", "alloydb", "AlloydbProvider", "AlloydbQuirks"),
    ("yugabytedb", "yugabytedb", "YugabytedbProvider", "YugabytedbQuirks"),
    ("timescaledb", "timescaledb", "TimescaledbProvider", "TimescaledbQuirks"),
    ("citus", "citus", "CitusProvider", "CitusQuirks"),
    ("cockroachdb", "cockroachdb", "CockroachdbProvider", "CockroachdbQuirks"),
    ("redshift", "redshift", "RedshiftProvider", "RedshiftQuirks"),
]


def _plugin(module_dir):
    return importlib.import_module(f"db.plugins.{module_dir}.plugin").PLUGIN


@pytest.mark.unit
@pytest.mark.parametrize("module_dir,dialect,provider_name,quirks_name", PG_COMPATIBLE)
class TestPgCompatiblePlugin:
    def test_plugin_info_reuses_postgresql(self, module_dir, dialect, provider_name, quirks_name):
        plugin = _plugin(module_dir)
        assert plugin.name == dialect
        assert plugin.dialects == [dialect]
        assert plugin.transport == "native"
        # Reuse contract: PG-wire engines share PostgreSQL config. Redshift
        # uses a dedicated SQLAlchemy dialect/driver because Redshift does not
        # implement every PostgreSQL connection bootstrap query.
        assert plugin.config_dialect == "postgresql"
        if dialect == "redshift":
            assert plugin.sqlalchemy_url_builder is build_redshift_url
            assert plugin.native_driver_module == "redshift_connector"
        else:
            assert plugin.sqlalchemy_url_builder is build_postgresql_url
            assert plugin.native_driver_module == "psycopg"

    def test_provider_subclasses_postgresql(self, module_dir, dialect, provider_name, quirks_name):
        plugin = _plugin(module_dir)
        assert issubclass(plugin.provider_class, PostgreSqlProvider)
        assert plugin.provider_class.__name__ == provider_name
        assert plugin.provider_class.canonical_dialect_key == dialect

    def test_quirks_inherit_pg_but_drop_reference_flag(
        self, module_dir, dialect, provider_name, quirks_name
    ):
        plugin = _plugin(module_dir)
        assert issubclass(plugin.quirks_class, PostgresqlQuirks)
        assert plugin.quirks_class.__name__ == quirks_name
        quirks = plugin.quirks_class(dialect_name=dialect)
        # Wire-compatible → parse/render through the postgres sqlglot dialect.
        assert quirks.sqlglot_dialect == "postgres"
        assert quirks.dialect_name == dialect
        # Only PostgreSQL may own the ANSI reference dialect.
        assert quirks.is_ansi_reference_dialect is False


@pytest.mark.unit
def test_reference_dialect_invariant_survives_pg_derived_plugins():
    """Registering every PG-derived plugin must not create a second ANSI-reference
    owner — ``reference_dialect_name`` requires exactly one (PostgreSQL)."""
    ProviderRegistry.discover_plugins()
    for module_dir, *_ in PG_COMPATIBLE:
        ProviderRegistry.register_plugin(_plugin(module_dir))

    assert ProviderRegistry.reference_dialect_name() == "postgresql"


@pytest.mark.unit
@pytest.mark.parametrize("module_dir,dialect,provider_name,quirks_name", PG_COMPATIBLE)
def test_registry_routes_dialect_to_provider(module_dir, dialect, provider_name, quirks_name):
    ProviderRegistry.discover_plugins()
    ProviderRegistry.register_plugin(_plugin(module_dir))

    assert ProviderRegistry.canonical_dialect_name(dialect) == dialect
    provider_cls = ProviderRegistry.get_provider_class(dialect)
    assert provider_cls is not None
    assert provider_cls.__name__ == provider_name
    assert issubclass(provider_cls, PostgreSqlProvider)


@pytest.mark.unit
@pytest.mark.parametrize("module_dir,dialect,provider_name,quirks_name", PG_COMPATIBLE)
def test_config_create_preserves_identity(module_dir, dialect, provider_name, quirks_name):
    """``type: <engine>`` reuses ``PostgreSqlConfig`` but must KEEP its own type,
    so ``create_provider`` returns the engine's provider — not PostgreSQL's.

    Regression guard: ``PostgreSqlConfig.__post_init__`` used to force
    ``type = "postgresql"`` unconditionally, collapsing every PG-derived engine
    back to PostgreSQL (identity lost). ``_POSTGRESQL_FAMILY`` preserves it.
    """
    from config.database_config import BaseDatabaseConfig
    from config.dblift_config import DbliftConfig
    from db.plugins.postgresql.config import PostgreSqlConfig

    ProviderRegistry.discover_plugins()
    ProviderRegistry.register_plugin(_plugin(module_dir))

    cfg = BaseDatabaseConfig.create(
        {"type": dialect, "url": "postgresql://u:p@h:5432/db", "schema": "public"}
    )
    assert isinstance(cfg, PostgreSqlConfig)  # reuses the PG config class
    assert cfg.type == dialect  # ...but keeps its own identity

    provider = ProviderRegistry.create_provider(DbliftConfig(database=cfg))
    assert type(provider).__name__ == provider_name


@pytest.mark.unit
def test_postgres_alias_still_normalises_to_postgresql():
    """The ``postgres`` alias (not a distinct engine) must still fold to
    ``postgresql`` — only the named family members keep their own type."""
    from config.database_config import BaseDatabaseConfig

    cfg = BaseDatabaseConfig.create({"type": "postgres", "url": "postgresql://u:p@h/db"})
    assert cfg.type == "postgresql"
