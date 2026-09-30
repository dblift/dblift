"""Dialect boundary contract.

This module is the **single declaration** of every behaviour a database
plugin can override. Adding a hook = ADR + edit this file. Calling a
hook = ``provider.quirks.<hook>()`` from framework code.

Why a boundary
--------------

Dialect-specific behaviour must not appear in ``api/``, ``cli/``,
``config/`` or ``core/`` as string-literal branches
(``if dialect.lower() == "oracle": ...``): every such branch is one more
file to edit when a backend is added and one more place for a compound
predicate to go wrong. Instead, one behaviour-overlay protocol —
:class:`DialectQuirks` — is implemented per dialect in
``db/plugins/<X>/quirks.py``. The framework asks ``provider.quirks`` for
the answer; it never names a dialect. ADR 0007 covers the data side
(capabilities matrix); this module covers the behaviour side.

Layout
------

``DialectQuirks``
    Top-level Protocol. Composes the per-concern sub-protocols below.

Sub-protocols:

* ``DdlQuirks`` — DDL/SQL rendering hooks.
* ``ParserQuirks`` — parser/tokenizer factory hooks.
* ``ModelQuirks`` — domain-model rendering hooks.
* ``ComparatorQuirks`` — schema-diff comparator hooks.
* ``ValidatorQuirks`` — lint/perf rule hooks.
* ``TypeMapQuirks`` — type normalisation hooks.
* ``ErrorQuirks`` — error-classification hooks.
* ``ConnectionQuirks`` — connection / engine-pool hooks.

Resolution
----------

A provider exposes its quirks via :attr:`dblift.db.base_provider.BaseProvider.quirks`.
The accessor delegates to :class:`dblift.db.provider_registry.ProviderRegistry`,
which resolves ``dialect -> PluginInfo.quirks_class`` and instantiates
on first access.

A plugin that has nothing to override may omit ``quirks_class`` from
its ``PluginInfo``; the registry returns a :class:`dblift.db.base_quirks.BaseQuirks`
instance, whose hooks carry safe defaults. Per-plugin classes override
only the deltas.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional, Protocol, Type, runtime_checkable

if TYPE_CHECKING:
    from dblift.db.generator_protocol import AlterGeneratorProtocol, SqlGeneratorProtocol


@runtime_checkable
class DdlQuirks(Protocol):
    """DDL / SQL-rendering hooks.

    First hooks: the DDL generator class and the ALTER generator class
    for this dialect, consumed by a ``SqlGeneratorProtocol`` implementation.
    Returning ``None`` means no dialect-specific generator is provided.
    """

    def ddl_generator_class(self) -> Optional[Type["SqlGeneratorProtocol"]]:
        """Return the dialect-specific DDL generator class, or ``None``."""

    def alter_generator_class(self) -> Optional[Type["AlterGeneratorProtocol"]]:
        """Return the dialect-specific ALTER generator class, or ``None``."""

    def skip_index_ddl(self) -> bool:
        """True when the dialect manages indexes outside SQL DDL.

        CosmosDB sets this; the framework emits a comment instead of
        a DDL statement for INDEX objects. Other dialects return False.
        """

    def skip_index_ddl_comment(self) -> str:
        """Comment emitted when ``skip_index_ddl()`` returns True.

        Plugins that set ``skip_index_ddl=True`` provide their own
        explanation here. The default is dialect-agnostic so the
        framework can stay branch-free.
        """

    def preserves_object_definition(self, object_type_name: str) -> bool:
        """True when the verbatim object definition must be preserved.

        MySQL views / procedures / functions / triggers / events carry
        ``DEFINER`` clauses and quirky identifier quoting that the
        generator should not strip.
        """

    def introspector_class(self) -> "Optional[type]":
        """Return the dialect-specific BaseIntrospector class, or None.

        None causes IntrospectorFactory to fall back to SchemaIntrospector.
        Plugins use a lazy import to avoid circular imports.
        """

    non_transactional_sql_patterns: "tuple[tuple[str, str], ...]"
    native_driver_display: str
    requires_credentials: bool
    url_optional_when_file_path_given: bool


@runtime_checkable
class ParserQuirks(Protocol):
    """Parser / tokenizer factory hooks."""


@runtime_checkable
class ModelQuirks(Protocol):
    """Domain-model rendering hooks.

    First hook: how a dialect wraps a trigger body when rendering to
    SQL. Oracle requires ``BEGIN`` / ``END`` blocks; other dialects
    pass the body through unchanged. The framework calls
    ``provider.quirks.wrap_trigger_body(body)`` from
    :meth:`dblift.core.sql_model.trigger.Trigger._format_body`.
    """

    def wrap_trigger_body(self, body: str) -> str:
        """Wrap a trigger body in dialect-specific delimiters.

        Default: return ``body`` unchanged. Oracle prepends ``BEGIN\\n``
        when the body doesn't already start with ``DECLARE`` or
        ``BEGIN``.
        """


@runtime_checkable
class ComparatorQuirks(Protocol):
    """Schema-diff comparator hooks."""

    view_supports_algorithm: bool
    view_supports_force_noforce: bool
    view_supports_unlogged_and_security: bool
    event_supports_mysql_schedule: bool
    supports_constraint_triggers: bool
    default_index_type: str
    serial_types_alias_integer: bool
    proc_uses_definition_field: bool
    proc_skip_empty_comparison: bool
    table_supports_compress: bool
    table_supports_memory_optimized: bool
    table_supports_system_versioned: bool
    table_column_default_has_on_update: bool
    seq_uses_nextval_syntax: bool
    computed_column_introspection_incomplete: bool


@runtime_checkable
class ValidatorQuirks(Protocol):
    """Lint / perf rule hooks."""

    def existence_check_sql(self, table_name: str) -> str:
        """Return SQL that checks whether *table_name* has any rows."""

    def fk_reference_query(
        self, schema: str, table: str, col: str
    ) -> "tuple[Optional[str], list[Any]]":
        """Return ``(sql, params)`` for FK reference lookup, or ``(None, [])``."""

    def index_reference_query(
        self, schema: str, table: str, col: str
    ) -> "tuple[Optional[str], list[Any]]":
        """Return ``(sql, params)`` for index reference lookup, or ``(None, [])``."""


@runtime_checkable
class TypeMapQuirks(Protocol):
    """Type-normalisation hooks."""

    def type_equivalents(self) -> "dict[str, str]":
        """Return dialect alias→canonical type mapping."""

    def type_preferences(self) -> "dict[str, str]":
        """Return dialect canonical→preferred type mapping."""


@runtime_checkable
class ErrorQuirks(Protocol):
    """Error-classification hooks. Populated by ADR-26 T0."""

    def error_patterns(self) -> "list[tuple[re.Pattern[str], Any]]":
        """Return this dialect's ordered (compiled-regex, ErrorCategory) pairs
        for connection/SQL error classification, or [] for none.

        Typed loosely (second element is the db-layer ``ErrorCategory`` enum)
        because this module is in ``core/`` and MUST NOT import from ``db/``
        at module load — the core→db layering rule. Plugins return the
        precise type."""


@runtime_checkable
class ConnectionQuirks(Protocol):
    """Connection / engine-pool hooks. Populated by ADR-26 T0."""

    def engine_pool_options(self) -> "dict[str, Any]":
        """Return dialect-specific SQLAlchemy engine/pool kwargs merged into
        ``create_engine(...)``. Default: {} (no overrides)."""


@runtime_checkable
class DialectQuirks(
    DdlQuirks,
    ParserQuirks,
    ModelQuirks,
    ComparatorQuirks,
    ValidatorQuirks,
    TypeMapQuirks,
    ErrorQuirks,
    ConnectionQuirks,
    Protocol,
):
    """Single contract for dialect-specific behaviour.

    Composes the per-concern sub-protocols. Framework code depends on
    this aggregate; concrete plugins implement only the hooks they need
    by extending :class:`dblift.db.base_quirks.BaseQuirks`.

    Required attribute
    ------------------
    ``dialect_name``
        The lowercase identifier of the dialect this instance speaks
        for (``"postgresql"``, ``"oracle"``, …). Used by conformance
        tests and by error messages — never as a branching key.
    """

    dialect_name: str


__all__ = [
    "DialectQuirks",
    "DdlQuirks",
    "ParserQuirks",
    "ModelQuirks",
    "ComparatorQuirks",
    "ValidatorQuirks",
    "TypeMapQuirks",
    "ErrorQuirks",
    "ConnectionQuirks",
]
