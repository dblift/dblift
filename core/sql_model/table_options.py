"""Dialect-specific options for ``Table``, regrouped into immutable dataclasses.

SIMP-48
-------
``core.sql_model.table.Table.__init__`` now exposes only base/structural
parameters. All dialect-specific properties (MySQL ``storage_engine``,
SQL Server ``memory_optimized``, PostgreSQL ``row_security``,
Oracle/DB2 ``pctfree``, ...) are grouped into four small frozen
dataclasses plus this ``TableOptions`` aggregate, and applied via
``Table.from_options(name, columns, options=TableOptions(...))``.
The reverse extraction is ``Table.to_options()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True, slots=True)
class MySqlTableOptions:
    """MySQL/MariaDB specific table options."""

    storage_engine: Optional[str] = None
    row_format: Optional[str] = None
    table_collation: Optional[str] = None
    next_auto_increment: Optional[int] = None
    create_options: Optional[str] = None


@dataclass(frozen=True, slots=True)
class SqlServerTableOptions:
    """SQL Server (T-SQL grammar-based) table options."""

    filegroup: Optional[str] = None
    memory_optimized: bool = False
    system_versioned: bool = False
    history_table: Optional[str] = None
    history_schema: Optional[str] = None
    period_start_column: Optional[str] = None
    period_end_column: Optional[str] = None


@dataclass(frozen=True, slots=True)
class PostgresTableOptions:
    """PostgreSQL specific table options."""

    row_security: bool = False
    force_row_security: bool = False
    policies: List[Dict[str, Any]] = field(default_factory=list)
    inherits: List[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OracleStorageOptions:
    """Oracle / DB2 storage parameters — SQL-generation-only, not diff-relevant."""

    pctfree: Optional[int] = None
    pctused: Optional[int] = None
    initial: Optional[int] = None
    next: Optional[int] = None


@dataclass(frozen=True, slots=True)
class TableOptions:
    """Aggregated dialect-specific options for ``core.sql_model.table.Table``."""

    mysql: MySqlTableOptions = field(default_factory=MySqlTableOptions)
    sqlserver: SqlServerTableOptions = field(default_factory=SqlServerTableOptions)
    postgres: PostgresTableOptions = field(default_factory=PostgresTableOptions)
    oracle_storage: OracleStorageOptions = field(default_factory=OracleStorageOptions)
    derived_from: Optional[str] = None
    raw_ddl: Optional[str] = None


# ---------------------------------------------------------------------------
# Built-in ``dialect_options`` namespace map (ADR-26 E story 26-5).
#
# ``Table`` stores its built-in per-dialect options inside ``dialect_options``
# under the owning plugin's *canonical* namespace (``mysql`` / ``sqlserver`` /
# ``postgresql`` / ``oracle``). To keep ``table.py`` free of dialect-name
# string literals, the namespace strings are resolved from the plugin registry
# via a capability flag rather than hardcoded here. The mapping below names
# only the option keys (which are not dialect names) and the capability that
# identifies each namespace owner.
# ---------------------------------------------------------------------------

# (capability flag identifying the namespace owner, ((default, option_key), ...))
_BUILTIN_OPTION_GROUPS: Tuple[Tuple[str, Tuple[Tuple[Any, str], ...]], ...] = (
    (
        "table_uses_storage_engine_clause",
        (
            (None, "storage_engine"),
            (None, "row_format"),
            (None, "table_collation"),
            (None, "next_auto_increment"),
            (None, "create_options"),
        ),
    ),
    (
        "table_uses_filegroup_syntax",
        (
            (None, "filegroup"),
            (False, "memory_optimized"),
            (False, "system_versioned"),
            (None, "history_table"),
            (None, "history_schema"),
            (None, "period_start_column"),
            (None, "period_end_column"),
        ),
    ),
    (
        "table_supports_inherits",
        (
            (False, "row_security"),
            (False, "force_row_security"),
            ([], "policies"),
            ([], "inherits"),
        ),
    ),
    (
        "table_supports_storage_params",
        (
            (None, "pctfree"),
            (None, "pctused"),
            (None, "initial"),
            (None, "next"),
        ),
    ),
)

_namespace_cache: Dict[str, Optional[str]] = {}


def builtin_namespace_for(capability: str) -> Optional[str]:
    """Return the canonical ``dialect_options`` namespace owning *capability*.

    Resolved (and cached) via the plugin registry so ``table.py`` never names
    a dialect. Returns ``None`` if no single plugin owns the capability.
    """
    if capability not in _namespace_cache:
        from db.provider_registry import ProviderRegistry

        _namespace_cache[capability] = ProviderRegistry.canonical_dialect_name_for_capability(
            capability
        )
    return _namespace_cache[capability]


def builtin_option_namespaces() -> Dict[str, Tuple[Tuple[Any, str], ...]]:
    """Map each built-in ``dialect_options`` namespace → its ``(default, key)`` options.

    Namespaces with no resolvable owner plugin are skipped, so the result only
    contains live canonical names (``mysql`` / ``sqlserver`` / ``postgresql`` /
    ``oracle`` for the first-party plugin set).
    """
    out: Dict[str, Tuple[Tuple[Any, str], ...]] = {}
    for capability, options in _BUILTIN_OPTION_GROUPS:
        namespace = builtin_namespace_for(capability)
        if namespace is not None:
            out[namespace] = options
    return out
