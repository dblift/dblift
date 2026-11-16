"""Dialect quoting and capability helpers for database dialect identifiers.

Identifier-quoting dispatch is centralized here: the module-level
``quote_identifier`` / ``quote_qualified`` functions hold the canonical
quoting rules, so callers use them instead of branching on dialect name.

This module also holds ``SQLGLOT_DIALECT_MAP``, so callers can import it
instead of repeating inline string comparisons.

Canonical-name resolution lives in ``ProviderRegistry.canonical_dialect_name``;
per-dialect behaviour is dispatched through each plugin's Quirks class rather
than hardcoded here.
"""

from dataclasses import dataclass
from typing import Dict, Optional

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
    #: (Oracle, DB2). Relevant for introspection comparison and display.
    uppercase_identifiers: bool
    #: How ``clean`` enumerates and drops schema objects:
    #:   - ``"native"``: provider exposes ``enumerate_clean_candidates`` /
    #:     ``get_clean_preview`` (SQLite, Cosmos DB, Oracle)
    #:   - ``"introspector"``: introspector walks plugin-owned vendor metadata queries
    clean_strategy: str


# Capabilities now live on plugin Quirks. The lazy ``_CAPABILITIES`` dict
# below is built once on first ``get_dialect_capabilities`` call by reading
# each registered plugin's quirks. This module no longer hardcodes any
# dialect name.
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
    from dblift.db.provider_registry import ProviderRegistry

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
    clean_strategy="introspector",
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


def dialect_requires_schema(dialect: Optional[str]) -> bool:
    """``True`` iff the dialect's config must carry a non-empty ``database.schema``."""
    return get_dialect_capabilities(dialect).schema_required


# SQLGLOT_DIALECT_MAP starts empty; consumers either call ``_ensure_*``
# directly (internal) or trigger population implicitly through helpers
# that wrap access. Importers that read the dict before any plugin-aware
# code path runs would see an empty dict — wrap external read paths to
# call the ensure-helper.
def get_sqlglot_dialect(dialect: Optional[str]) -> Optional[str]:
    """Public API for sqlglot-dialect lookup. Builds the map lazily."""
    _ensure_sqlglot_dialect_map()
    if not dialect:
        return None
    return SQLGLOT_DIALECT_MAP.get(dialect.lower().strip())


# ---------------------------------------------------------------------------
# Centralized sqlglot dialect mapping (single source of truth).
#
# Kept as a plain Dict (not a property) so it can be constructed at import
# time with zero overhead.
# ---------------------------------------------------------------------------

#: Maps dblift dialect names (and common aliases) to sqlglot dialect
#: names. Lazily populated from each plugin's ``Quirks.sqlglot_dialect``
#: on first access. A value of ``None`` means
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
    from dblift.db.provider_registry import ProviderRegistry

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
# Canonical quoting rules per dialect. Driven directly by
# ``Quirks.quote_open`` / ``Quirks.quote_close`` — ``quote_identifier``
# reads them from ``ProviderRegistry.get_quirks`` per call, so adding a
# new dialect = override the attributes in its plugin Quirks, no edit to
# this file.
# ---------------------------------------------------------------------------


def quote_identifier(dialect: Optional[str], identifier: str) -> str:
    """Quote a SQL identifier using the canonical rules for *dialect*.

    This is the single source of truth for identifier quoting.
    Callers that previously maintained their own ``_quote_identifier``
    if/elif chains now delegate here.

    Rules:
      - mysql    → ``identifier``
      - sqlserver → [identifier]
      - all others (postgresql, oracle, db2, sqlite, cosmosdb, unknown,
        None) → "identifier"  (ANSI SQL double-quote)

    Args:
        dialect: SQL dialect string (any case; None treated as default).
        identifier: Raw identifier to quote. An embedded occurrence of the
            dialect's own close-quote character is escaped by doubling it
            before wrapping.

    Returns:
        Quoted identifier string.
    """
    from dblift.db.provider_registry import ProviderRegistry

    q = ProviderRegistry.get_quirks((dialect or "").lower().strip())
    escaped = identifier.replace(q.quote_close, q.quote_close * 2)
    return f"{q.quote_open}{escaped}{q.quote_close}"


def quote_qualified(
    dialect: Optional[str],
    schema: Optional[str],
    identifier: str,
) -> str:
    """Quote a schema-qualified SQL identifier using dialect rules.

    Bans the ``f'"{schema}"."{table}"'`` anti-pattern that ignored
    dialect quoting. On Oracle, unquoted identifiers fold
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
    # Oracle folds unquoted identifiers to uppercase at CREATE TABLE
    # time, so explicitly-quoted lower-case idents target a
    # non-existent object — upper-case them to match the folding done
    # at definition. The decision is dialect-owned via the
    # ``quote_qualified_folds_to_uppercase`` quirk (Oracle ONLY).
    # DB2 shares Oracle's identifier-folding quirks but deliberately
    # leaves this flag False to preserve historical behaviour.
    from dblift.db.provider_registry import ProviderRegistry

    key = (dialect or "").lower().strip()
    if ProviderRegistry.get_quirks(key).quote_qualified_folds_to_uppercase:
        identifier = identifier.upper()
        if schema:
            schema = schema.upper()
    ident_q = quote_identifier(dialect, identifier)
    if not schema:
        return ident_q
    schema_q = quote_identifier(dialect, schema)
    return f"{schema_q}.{ident_q}"
