"""Factory for PostgreSQL-wire-compatible distribution plugins.

Several engines (Neon, Supabase, Aurora PostgreSQL, AlloyDB, YugabyteDB,
TimescaleDB, Citus) speak the PostgreSQL wire protocol and reuse PostgreSQL's
provider, config, SQLAlchemy URL builder, and ``psycopg`` driver wholesale.
Their only per-engine content is *identity*, not *behavior*:

* a ``canonical_dialect_key`` on the provider, and
* a quirks subclass that resets the two "reference dialect" flags to ``False``
  (exactly one registered plugin — PostgreSQL — may own each, see
  :meth:`ProviderRegistry.reference_dialect_name`).

Historically each such engine shipped three near-identical files
(``provider.py`` / ``quirks.py`` / ``plugin.py``) that differed only by a name
string. This module collapses that boilerplate: :func:`make_pg_compatible_plugin`
builds the provider class, the quirks class, and the :class:`PluginInfo` from a
single dialect name, so a new PG-wire engine is one declaration in its
``plugin.py``.

Engines with genuine behavioral differences (CockroachDB's table locking,
Redshift's catalog/history SQL) are **not** built here — they keep hand-written
provider/quirks classes.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Type

from db.base_provider import BaseProvider
from db.plugins.postgresql.provider import PostgreSqlProvider
from db.plugins.postgresql.quirks import PostgresqlQuirks
from db.plugins.postgresql.sqlalchemy_url import build_sqlalchemy_url
from db.provider_registry import PluginInfo


def _class_stem(dialect: str) -> str:
    """Derive the CamelCase class-name stem from a dialect key.

    ``"neon"`` -> ``"Neon"``; ``"aurora-postgresql"`` -> ``"AuroraPostgresql"``.
    Kept deliberately simple (``str.capitalize`` per hyphen segment) so the
    generated names match the ``<Stem>Provider`` / ``<Stem>Quirks`` strings the
    plugin-contract tests assert.
    """
    return "".join(part.capitalize() for part in dialect.split("-"))


def make_pg_compatible_provider(dialect: str) -> Type[PostgreSqlProvider]:
    """Build a PostgreSQL provider subclass carrying only a distinct identity."""
    stem = _class_stem(dialect)
    return type(
        f"{stem}Provider",
        (PostgreSqlProvider,),
        {
            "__module__": __name__,
            "__doc__": (
                f"{stem} provider — wire-compatible with PostgreSQL; reuses the "
                "PostgreSQL provider with a distinct dialect identity."
            ),
            "canonical_dialect_key": dialect,
        },
    )


def make_pg_compatible_quirks(dialect: str) -> Type[PostgresqlQuirks]:
    """Build a PostgreSQL quirks subclass that drops the reference-dialect flags.

    The two flags are set in the class body (not per instance) because
    :meth:`ProviderRegistry.canonical_dialect_name_for_capability` reads
    ``vars(quirks_class)`` — only a class-level override makes this engine a
    non-owner of the ANSI-reference and sqlglot-read-fallback capabilities,
    preserving PostgreSQL as the single owner of each.
    """
    stem = _class_stem(dialect)

    def __init__(self: PostgresqlQuirks, dialect_name: str = dialect) -> None:
        # type()-built classes have no __class__ cell, so ``super()`` is
        # unavailable — call the base initializer explicitly.
        PostgresqlQuirks.__init__(self, dialect_name=dialect_name)

    return type(
        f"{stem}Quirks",
        (PostgresqlQuirks,),
        {
            "__module__": __name__,
            "__doc__": (
                f"{stem} quirks, inheriting every PostgreSQL quirk. Only the "
                "reference-dialect flags are reset so PostgreSQL stays the sole "
                "owner of each."
            ),
            "is_ansi_reference_dialect": False,
            "is_default_sqlglot_read_fallback": False,
            "__init__": __init__,
        },
    )


def make_pg_compatible_plugin(
    dialect: str,
    description: str,
    *,
    dialects: Optional[List[str]] = None,
    version: str = "1.0.0",
    sqlalchemy_url_builder: Callable[..., str] = build_sqlalchemy_url,
    native_driver_module: str = "psycopg",
) -> PluginInfo:
    """Assemble the :class:`PluginInfo` for a PostgreSQL-wire-compatible engine.

    Reuses PostgreSQL's config (``config_dialect="postgresql"``), URL builder,
    and driver; only the identity (provider/quirks classes + dialect key) is
    engine-specific. ``dialects`` defaults to ``[dialect]``.
    """
    provider_class: Type[BaseProvider] = make_pg_compatible_provider(dialect)
    quirks_class = make_pg_compatible_quirks(dialect)
    return PluginInfo(
        name=dialect,
        version=version,
        description=description,
        dialects=dialects if dialects is not None else [dialect],
        provider_class=provider_class,
        transport="native",
        quirks_class=quirks_class,
        config_dialect="postgresql",  # lint: allow-dialect-string: reuse PG config class
        sqlalchemy_url_builder=sqlalchemy_url_builder,
        native_driver_module=native_driver_module,
    )


__all__ = [
    "make_pg_compatible_provider",
    "make_pg_compatible_quirks",
    "make_pg_compatible_plugin",
]
