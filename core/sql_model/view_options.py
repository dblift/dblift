"""Dialect-specific options for ``View``, regrouped into immutable dataclasses.

Mirrors the design of ``core.sql_model.table_options`` (SIMP-48):
the legacy ``View.__init__`` exposes 20 keyword arguments. Most are
optional dialect-specific properties (PostgreSQL ``unlogged`` /
``security_definer``, MySQL ``algorithm`` / ``definer``, Oracle
``force``, materialized-view refresh policy, ...). The sprawl makes
the constructor hard to read and impossible to type-check ergonomically.

This module groups those options into four small frozen dataclasses
plus a ``ViewOptions`` aggregate. ``View`` exposes
``View.from_options(...)`` and ``View.to_options()`` so callers can
opt into the typed surface incrementally — the original
``View.__init__`` signature is preserved verbatim, so the existing
249+ call sites keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True, slots=True)
class MaterializedViewOptions:
    """Refresh policy and population state for materialized views.

    Used by Oracle / DB2 / PostgreSQL when ``materialized=True``.
    """

    is_populated: Optional[bool] = None
    refresh_method: Optional[str] = None  # FAST, COMPLETE, FORCE, MANUAL (Oracle, DB2)
    refresh_mode: Optional[str] = None  # ON DEMAND, ON COMMIT (Oracle)
    fast_refreshable: Optional[bool] = None  # Oracle
    last_refresh: Optional[str] = None  # Oracle, DB2 — runtime metadata


@dataclass(frozen=True, slots=True)
class PostgresViewOptions:
    """PostgreSQL-specific view options."""

    unlogged: Optional[bool] = None  # PostgreSQL grammar-based
    security_definer: Optional[bool] = None
    security_invoker: Optional[bool] = None


@dataclass(frozen=True, slots=True)
class MySqlViewOptions:
    """MySQL-specific view options."""

    algorithm: Optional[str] = None  # MERGE, TEMPTABLE, UNDEFINED
    sql_security: Optional[str] = None  # DEFINER, INVOKER
    definer: Optional[str] = None  # user@host


@dataclass(frozen=True, slots=True)
class OracleViewOptions:
    """Oracle-specific view options."""

    force: Optional[bool] = None  # FORCE / NOFORCE


@dataclass(frozen=True, slots=True)
class ViewOptions:
    """Aggregated dialect-specific options for ``core.sql_model.view.View``."""

    materialized_view: MaterializedViewOptions = field(default_factory=MaterializedViewOptions)
    postgres: PostgresViewOptions = field(default_factory=PostgresViewOptions)
    mysql: MySqlViewOptions = field(default_factory=MySqlViewOptions)
    oracle: OracleViewOptions = field(default_factory=OracleViewOptions)
    # SQL-generation only, dialect-agnostic
    dependencies: List[str] = field(default_factory=list)

    def to_kwargs(self) -> Dict[str, Any]:
        """Flatten options into the keyword form accepted by ``View.__init__``."""
        return {
            # Materialized view
            "is_populated": self.materialized_view.is_populated,
            "refresh_method": self.materialized_view.refresh_method,
            "refresh_mode": self.materialized_view.refresh_mode,
            "fast_refreshable": self.materialized_view.fast_refreshable,
            "last_refresh": self.materialized_view.last_refresh,
            # PostgreSQL
            "unlogged": self.postgres.unlogged,
            "security_definer": self.postgres.security_definer,
            "security_invoker": self.postgres.security_invoker,
            # MySQL
            "algorithm": self.mysql.algorithm,
            "sql_security": self.mysql.sql_security,
            "definer": self.mysql.definer,
            # Oracle
            "force": self.oracle.force,
            # Misc
            "dependencies": list(self.dependencies),
        }
