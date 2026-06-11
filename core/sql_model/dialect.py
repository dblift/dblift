"""Dialect enum for canonical database dialect identifiers.

Story 21-14 — Phase 1 pilot: identifier-quoting dispatch centralised here.

Before (2 files, 9 if/elif branches):
  base_converter.py      _quote_identifier()  — 5 branches
  undo_script_generator.py _quote_identifier() — 4 branches

After (0 branches in those files, 1 dispatch dict below):
  Each `_quote_identifier` becomes a one-liner:
    return DialectEnum.quote_identifier(self.dialect, identifier)

SIMP-37 — Phase 0: DialectGroup constants + SQLGLOT_DIALECT_MAP centralized here
  so that all clusters (Phase 1–5) can import frozensets instead of repeating
  inline string comparisons.

Story 25-19 — Phase 5: dispatch_by_dialect utility for replacing scattered if/elif chains.
"""

from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, FrozenSet, Optional, TypeVar

T = TypeVar("T")

if TYPE_CHECKING:
    # Lazy module-level constants resolved via ``__getattr__`` (PEP 562).
    # Declare them here so mypy infers ``FrozenSet[str]`` instead of ``Any?``
    # at import sites. Without these stubs, mypy's cache occasionally widens
    # the inferred type to ``Any | None``, breaking ``x in CATALOG_DIALECTS``.
    CATALOG_DIALECTS: FrozenSet[str]
    CATALOG_SCHEMA_DIALECTS: FrozenSet[str]
    NULL_CATALOG_DIALECTS: FrozenSet[str]
    CONCURRENT_INDEX_DIALECTS: FrozenSet[str]
    ONLINE_INDEX_DIALECTS: FrozenSet[str]
    NOSQL_DIALECTS: FrozenSet[str]
    SCHEMA_OPTIONAL_DIALECTS: FrozenSet[str]
    CASCADE_DROP_DIALECTS: FrozenSet[str]
    BACKTICK_DIALECTS: FrozenSet[str]

# ---------------------------------------------------------------------------
# SIMP-37 Phase 0 — DialectGroup frozensets
#
# These constants replace scattered `dialect == "x"` comparisons with
# membership tests (`dialect in SOME_DIALECTS`).  Import them in any module
# that needs to branch on dialect groups rather than individual values.
# ---------------------------------------------------------------------------

# Dialect-group sets are now derived lazily from plugin Quirks. Module
# load no longer hardcodes a single name. ``__getattr__`` (PEP 562) at
# the bottom of this module resolves each well-known set on first
# access. Listed here for ``grep``-ability:
#
#   CATALOG_DIALECTS              -> quirks.metadata_catalog_mode == "catalog"
#   CATALOG_SCHEMA_DIALECTS       -> ... == "catalog+schema"
#   NULL_CATALOG_DIALECTS         -> ... == "schema_only"
#   CONCURRENT_INDEX_DIALECTS     -> quirks.supports_concurrent_index
#   ONLINE_INDEX_DIALECTS         -> quirks.supports_online_index
#   NOSQL_DIALECTS                -> quirks.is_nosql
#   SCHEMA_OPTIONAL_DIALECTS      -> not quirks.schema_required
#   CASCADE_DROP_DIALECTS         -> quirks.drop_table_default_cascade
#   BACKTICK_DIALECTS             -> quirks.quote_open == "`"


# ---------------------------------------------------------------------------
# PR-07 — DialectCapabilities (canonical capability matrix per dialect)
#
# Purpose: a single authoritative record of what each dialect supports, so
# call sites stop answering the same question with different heuristics
# (``isinstance(p, TransactionalProvider) and p.supports_transactions()``,
# ``if dialect in ("sqlite", "cosmosdb")``, ``if dialect.lower() == "oracle"
# or dialect.lower() == "db2"``). Providers are expected to match this
# matrix; a conformance test asserts it in tests/unit/core/sql_model/.
# See docs/adr/0007-dialect-capabilities-matrix.md.
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass(frozen=True)
class DialectCapabilities:
    """What a given dialect supports. Authoritative; providers must match."""

    #: The provider can begin/commit/rollback transactions (DML, at least).
    supports_transactions: bool
    #: DDL (CREATE/ALTER/DROP) participates in transactions and can be
    #: rolled back. Oracle and MySQL auto-commit DDL; PostgreSQL, SQL Server,
    #: DB2, and SQLite do not.
    supports_transactional_ddl: bool
    #: A ``database.schema`` value is required in config. False for
    #: file-based or schema-less backends (SQLite, Cosmos DB).
    schema_required: bool
    #: Unquoted identifiers fold to uppercase in the persisted catalogue
    #: (Oracle, DB2). Relevant for SQL generation and display.
    uppercase_identifiers: bool
    #: How ``clean`` enumerates and drops schema objects.
    clean_strategy: str


# Capabilities now live on plugin Quirks (Epic 26 story 26-13
# followup). The lazy ``_CAPABILITIES`` dict below is built once on
# first ``get_dialect_capabilities`` call by reading each registered
# plugin's quirks. This module no longer hardcodes any dialect name.
_CAPABILITIES: Dict[str, DialectCapabilities] = {}


_capabilities_seen: int = 0


def _ensure_capabilities() -> None:
    """Populate ``_CAPABILITIES`` from registered plugin quirks.

    Re-builds when the registry's expected (plugin, alias) pair count
    changes. Uses an integer counter — not ``len(_CAPABILITIES)`` —
    because two plugins can legitimately share an alias (e.g. mysql
    and mariadb both publish ``"mariadb"`` while loading), causing
    dict deduplication that would otherwise pin the length below
    ``expected`` and trigger an infinite rebuild loop. (PR #241
    Bugbot.)
    """
    global _capabilities_seen
    from db.provider_registry import ProviderRegistry

    ProviderRegistry.discover_plugins()
    expected = sum(len(p.dialects) for p in ProviderRegistry.list_plugins())
    if expected and _capabilities_seen == expected:
        return
    _CAPABILITIES.clear()
    _capabilities_seen = 0
    for plugin_info in ProviderRegistry.list_plugins():
        quirks = ProviderRegistry.get_quirks(plugin_info.name)
        caps = DialectCapabilities(
            supports_transactions=quirks.supports_transactions,
            supports_transactional_ddl=quirks.supports_transactional_ddl,
            schema_required=quirks.schema_required,
            uppercase_identifiers=quirks.uppercase_identifiers,
            clean_strategy=quirks.clean_strategy,
        )
        for alias in plugin_info.dialects:
            _capabilities_seen += 1
            _CAPABILITIES[alias.lower()] = caps


# Defined BEFORE get_dialect_capabilities so that any future module-level
# expression inserted between the function and its fallback would not
# hit a NameError at import time (Bugbot PR 162 "forward reference").
_CAPABILITIES_UNKNOWN: DialectCapabilities = DialectCapabilities(
    supports_transactions=False,
    supports_transactional_ddl=False,
    schema_required=True,  # safest default — force explicit config
    uppercase_identifiers=False,
    clean_strategy="native",
)


def get_dialect_capabilities(dialect: Optional[str]) -> DialectCapabilities:
    """Return the capabilities record for *dialect*.

    Unknown / ``None`` dialects fall back to ``UNKNOWN`` behaviour — the
    most conservative defaults so that caller-side ``if supports_X(d)``
    guards degrade safely rather than raise.
    """
    if not dialect:
        return _CAPABILITIES_UNKNOWN
    _ensure_capabilities()
    return _CAPABILITIES.get(dialect.lower().strip(), _CAPABILITIES_UNKNOWN)


def dialect_supports_transactions(dialect: Optional[str]) -> bool:
    """``True`` iff the named dialect supports begin/commit/rollback."""
    return get_dialect_capabilities(dialect).supports_transactions


def dialect_supports_transactional_ddl(dialect: Optional[str]) -> bool:
    """``True`` iff DDL participates in transactions and can be rolled back."""
    return get_dialect_capabilities(dialect).supports_transactional_ddl


def dialect_requires_schema(dialect: Optional[str]) -> bool:
    """``True`` iff the dialect's config must carry a non-empty ``database.schema``."""
    return get_dialect_capabilities(dialect).schema_required


def dialect_uses_uppercase_identifiers(dialect: Optional[str]) -> bool:
    """``True`` iff unquoted identifiers fold to uppercase in the catalogue."""
    return get_dialect_capabilities(dialect).uppercase_identifiers


def dialect_clean_strategy(dialect: Optional[str]) -> str:
    """Return the provider clean enumeration strategy."""
    return get_dialect_capabilities(dialect).clean_strategy


# Derived frozenset of schema-optional dialects. Computed lazily from
# the plugin-driven matrix so module load doesn't pay the registry
# import cost. Callers that compare membership go through
# :func:`schema_optional_dialects_from_matrix`.
def schema_optional_dialects_from_matrix() -> FrozenSet[str]:
    """Return dialect names whose ``schema_required`` is False."""
    _ensure_capabilities()
    return frozenset(d for d, caps in _CAPABILITIES.items() if not caps.schema_required)


# Backwards-compat module attribute. Resolved on first access so old
# ``from core.sql_model.dialect import SCHEMA_OPTIONAL_DIALECTS_FROM_MATRIX``
# imports keep working without an upfront registry import. ``__getattr__``
# at module scope (PEP 562) gives us deferred attribute resolution.
def _dialects_where(predicate: Callable[[Any], bool]) -> FrozenSet[str]:
    """Return the frozen set of dialect aliases whose quirks satisfy
    ``predicate(quirks)``. Used by the lazy module-level constants."""
    from db.provider_registry import ProviderRegistry

    ProviderRegistry.discover_plugins()
    out: "set[str]" = set()
    for plugin_info in ProviderRegistry.list_plugins():
        quirks = ProviderRegistry.get_quirks(plugin_info.name)
        if predicate(quirks):
            out.update(d.lower() for d in plugin_info.dialects)
    return frozenset(out)


_LAZY_DIALECT_SETS = {
    "CATALOG_DIALECTS": lambda q: q.metadata_catalog_mode == "catalog",
    "CATALOG_SCHEMA_DIALECTS": lambda q: q.metadata_catalog_mode == "catalog+schema",
    "NULL_CATALOG_DIALECTS": lambda q: q.metadata_catalog_mode == "schema_only",
    "CONCURRENT_INDEX_DIALECTS": lambda q: q.supports_concurrent_index,
    "ONLINE_INDEX_DIALECTS": lambda q: q.supports_online_index,
    "NOSQL_DIALECTS": lambda q: q.is_nosql,
    "SCHEMA_OPTIONAL_DIALECTS": lambda q: not q.schema_required,
    "CASCADE_DROP_DIALECTS": lambda q: q.drop_table_default_cascade,
    "BACKTICK_DIALECTS": lambda q: q.quote_open == "`",
}

# Cache of resolved sets. Filled on first access; auto-invalidated when
# the registry's plugin count changes (tests resetting ``_plugins``).
# Using a count-based invalidator beats a static cache because callers
# reading these constants in hot loops would otherwise rebuild every
# call. (PR #241 Bugbot.)
_LAZY_DIALECT_SET_CACHE: Dict[str, FrozenSet[str]] = {}
_lazy_dialect_set_seen: int = 0


def __getattr__(name: str) -> Any:  # noqa: D401 - module-level dunder
    global _lazy_dialect_set_seen
    if name == "SCHEMA_OPTIONAL_DIALECTS_FROM_MATRIX":
        return schema_optional_dialects_from_matrix()
    if name in _LAZY_DIALECT_SETS:
        from db.provider_registry import ProviderRegistry

        ProviderRegistry.discover_plugins()
        expected = sum(len(p.dialects) for p in ProviderRegistry.list_plugins())
        if expected != _lazy_dialect_set_seen:
            _LAZY_DIALECT_SET_CACHE.clear()
            _lazy_dialect_set_seen = expected
        cached = _LAZY_DIALECT_SET_CACHE.get(name)
        if cached is None:
            cached = _dialects_where(_LAZY_DIALECT_SETS[name])
            _LAZY_DIALECT_SET_CACHE[name] = cached
        return cached
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# SQLGLOT_DIALECT_MAP and _QUOTE_OPEN/_CLOSE start empty; consumers
# either call ``_ensure_*`` directly (internal) or trigger population
# implicitly through helpers that wrap access. Importers that read
# the dict before any plugin-aware code path runs would see an empty
# dict — wrap external read paths to call the ensure-helper.
def get_sqlglot_dialect(dialect: Optional[str]) -> Optional[str]:
    """Public API for sqlglot-dialect lookup. Builds the map lazily."""
    _ensure_sqlglot_dialect_map()
    if not dialect:
        return None
    return SQLGLOT_DIALECT_MAP.get(dialect.lower().strip())


# ---------------------------------------------------------------------------
# SIMP-37 Phase 0 — Centralized sqlglot dialect mapping (single source of truth)
#
# The map is deliberately kept as a plain Dict (not a property) so it can be
# constructed at import time with zero overhead.
# ---------------------------------------------------------------------------

#: Maps dblift dialect names (and common aliases) to sqlglot dialect
#: names. Lazily populated from each plugin's ``Quirks.sqlglot_dialect``
#: on first access (Epic 26 followup). A value of ``None`` means
#: sqlglot has no matching dialect; callers should fall back to
#: unformatted output or a generic dialect.
SQLGLOT_DIALECT_MAP: Dict[str, Optional[str]] = {}
_sqlglot_map_seen: int = 0


def _ensure_sqlglot_dialect_map() -> None:
    """Populate ``SQLGLOT_DIALECT_MAP`` from registered plugin quirks.

    Re-runs when the registry's expected (plugin, alias) pair count
    changes. Uses an integer counter rather than ``len(map)`` so that
    plugins sharing an alias (dict deduplication) don't pin the
    length below the expected count and trigger an infinite rebuild
    loop. (PR #241 Bugbot.)
    """
    global _sqlglot_map_seen
    from db.provider_registry import ProviderRegistry

    ProviderRegistry.discover_plugins()
    expected = sum(len(p.dialects) for p in ProviderRegistry.list_plugins())
    if expected and _sqlglot_map_seen == expected:
        return
    SQLGLOT_DIALECT_MAP.clear()
    _sqlglot_map_seen = 0
    for plugin_info in ProviderRegistry.list_plugins():
        quirks = ProviderRegistry.get_quirks(plugin_info.name)
        for alias in plugin_info.dialects:
            _sqlglot_map_seen += 1
            SQLGLOT_DIALECT_MAP[alias.lower()] = quirks.sqlglot_dialect


# ---------------------------------------------------------------------------
# Canonical quoting rules per dialect (story 21-14). Now driven by
# ``Quirks.quote_open`` / ``Quirks.quote_close`` rather than a static
# table — adding a new dialect = override the attributes in its
# plugin Quirks, no edit to this file.
# ---------------------------------------------------------------------------
_QUOTE_OPEN: "dict[str, str]" = {}
_QUOTE_CLOSE: "dict[str, str]" = {}
_DEFAULT_QUOTE = '"'
# Tracks how many plugin dialects we've ingested. Re-build when stale
# (registry got cleared by tests). Counter beats a bool flag here
# because some plugins keep both maps empty (default ANSI quote
# everywhere) and a bool would always force re-discovery.
_quote_maps_seen: int = 0


def _ensure_quote_maps() -> None:
    global _quote_maps_seen
    from db.provider_registry import ProviderRegistry

    ProviderRegistry.discover_plugins()
    expected = sum(len(p.dialects) for p in ProviderRegistry.list_plugins())
    # ``==`` not ``>=`` — see _ensure_capabilities for rationale.
    if expected and _quote_maps_seen == expected:
        return
    _QUOTE_OPEN.clear()
    _QUOTE_CLOSE.clear()
    _quote_maps_seen = 0
    for plugin_info in ProviderRegistry.list_plugins():
        quirks = ProviderRegistry.get_quirks(plugin_info.name)
        for alias in plugin_info.dialects:
            _quote_maps_seen += 1
            if quirks.quote_open != _DEFAULT_QUOTE:
                _QUOTE_OPEN[alias.lower()] = quirks.quote_open
            if quirks.quote_close != _DEFAULT_QUOTE:
                _QUOTE_CLOSE[alias.lower()] = quirks.quote_close


class DialectEnum(str, Enum):
    """Canonical dialect identifiers for dblift.

    Uses str mixin for backward compatibility with existing string-based
    dialect comparisons (e.g., `self.dialect == DialectEnum.POSTGRESQL`
    works even if `self.dialect` is the plain string "postgresql").
    """

    POSTGRESQL = "postgresql"  # lint: allow-dialect-string: dialect dispatch
    ORACLE = "oracle"  # lint: allow-dialect-string: dialect dispatch
    MYSQL = "mysql"  # lint: allow-dialect-string: dialect dispatch
    SQLSERVER = "sqlserver"  # lint: allow-dialect-string: dialect dispatch
    DB2 = "db2"  # lint: allow-dialect-string: dialect dispatch
    SQLITE = "sqlite"  # lint: allow-dialect-string: dialect dispatch
    COSMOSDB = "cosmosdb"  # lint: allow-dialect-string: dialect dispatch
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, dialect: Optional[str]) -> "DialectEnum":
        """Normalize a dialect string to DialectEnum.

        Args:
            dialect: Dialect string (any case, e.g., "Oracle", "POSTGRESQL")

        Returns:
            DialectEnum member, or DialectEnum.UNKNOWN if not recognized
        """
        if not dialect:
            return cls.UNKNOWN
        try:
            return cls(dialect.lower().strip())
        except ValueError:
            return cls.UNKNOWN

    @staticmethod
    def quote_identifier(dialect: Optional[str], identifier: str) -> str:
        """Quote a SQL identifier using the canonical rules for *dialect*.

        This is the single source of truth for identifier quoting (story 21-14).
        Callers that previously maintained their own ``_quote_identifier``
        if/elif chains now delegate here.

        Rules:
          - mysql    → ``identifier``
          - sqlserver → [identifier]
          - all others (postgresql, oracle, db2, sqlite, cosmosdb, unknown,
            None) → "identifier"  (ANSI SQL double-quote)

        Args:
            dialect: SQL dialect string (any case; None treated as default).
            identifier: Raw identifier to quote (no escaping of internal
                special characters — callers that need escaping keep their
                own implementation, e.g. SafetyChecker).

        Returns:
            Quoted identifier string.
        """
        _ensure_quote_maps()
        key = (dialect or "").lower().strip()
        open_q = _QUOTE_OPEN.get(key, _DEFAULT_QUOTE)
        close_q = _QUOTE_CLOSE.get(key, _DEFAULT_QUOTE)
        return f"{open_q}{identifier}{close_q}"

    @staticmethod
    def quote_qualified(
        dialect: Optional[str],
        schema: Optional[str],
        identifier: str,
    ) -> str:
        """Quote a schema-qualified SQL identifier using dialect rules.

        Bans the ``f'"{schema}"."{table}"'`` anti-pattern that ignored
        dialect quoting (B10-BUG-01). On Oracle, unquoted identifiers fold
        to upper-case at CREATE TABLE time, so explicitly quoted lower-case
        idents target a non-existent object — Oracle inputs are upper-cased
        here to match the folding done at definition.

        Args:
            dialect: SQL dialect string (any case).
            schema: Optional schema name. Omitted when None or empty.
            identifier: Object name (table, view, sequence, ...).

        Returns:
            ``"<schema>"."<identifier>"`` with dialect-correct quotes, or
            ``"<identifier>"`` alone when *schema* is empty.
        """
        # Preserve historical Oracle-only behaviour here. The wider
        # ``uppercase_identifiers`` quirks flag (which DB2 also sets)
        # is consulted elsewhere; this specific helper only
        # uppercased identifiers for Oracle, and changing that would
        # alter DB2 output formatting unexpectedly. (PR #241 Bugbot.)
        # lint: allow-dialect-string: preserve narrow historical Oracle path
        key = (dialect or "").lower().strip()
        if key == "oracle":  # lint: allow-dialect-string: narrow historical scope
            identifier = identifier.upper()
            if schema:
                schema = schema.upper()
        ident_q = DialectEnum.quote_identifier(dialect, identifier)
        if not schema:
            return ident_q
        schema_q = DialectEnum.quote_identifier(dialect, schema)
        return f"{schema_q}.{ident_q}"


def dispatch_by_dialect(
    dialect: Optional[str],
    handlers: Dict[str, Callable[[], T]],
    default: Optional[Callable[[], T]] = None,
) -> Optional[T]:
    """Execute the handler for the given dialect, falling back to default.

    Replaces scattered ``if dialect == "x": ... elif dialect == "y": ...``
    chains with a single registry lookup.  Each handler is a zero-argument
    callable (typically a lambda) so that expensive computations are only
    evaluated for the matched dialect.

    Args:
        dialect: SQL dialect string (any case; None treated as empty string).
        handlers: Mapping of normalised dialect key → zero-arg callable.
        default: Fallback callable when dialect is not in *handlers*.
                 If None and dialect has no handler, returns None.

    Returns:
        The return value of the matched handler, or None if no match and no
        default is provided.

    Example::

        query = dispatch_by_dialect(
            self.dialect,
            {
                "oracle": lambda: "SELECT 1 FROM DUAL",
                "db2":    lambda: "SELECT 1 FROM SYSIBM.SYSDUMMY1",
            },
            default=lambda: "SELECT 1",
        )
    """
    key = (dialect or "").lower().strip()
    handler = handlers.get(key) or default
    if handler is None:
        return None
    return handler()
