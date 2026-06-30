"""Default :class:`DialectQuirks` implementation — Epic 26 story 26-2.

Concrete plugins extend :class:`BaseQuirks` and override only the
hooks whose behaviour differs from the default. Hooks live in the
sub-protocols declared in ``core/dialect_boundary.py``; this class
provides their default bodies.

In story 26-2 the protocol surface is empty (see ``core/dialect_boundary.py``);
``BaseQuirks`` therefore has no hook bodies yet. As stories 26-3..26-8
move dialect logic into quirks, this class gains safe defaults and
per-plugin classes override the deltas.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Dict, Optional, Sequence, Tuple, Type

from core.dialect_boundary import DialectQuirks
from db.dml_analysis import (
    DEFAULT_QUOTE_PAIRS,
    DEFAULT_UPSERT_MARKER_PAIRS,
    DEFAULT_UPSERT_SET_MARKERS,
    DmlMutation,
    analyze_dml,
    is_full_table_dml,
    updates_restore_key,
)


class BaseQuirks:
    """Default implementation of :class:`DialectQuirks`.

    Subclasses (one per ``db/plugins/<X>/quirks.py``) inherit and
    override the hooks they need. The dialect identifier is mandatory;
    everything else is optional and gains a default as Epic 26 stories
    land.
    """

    dialect_name: str = ""

    #: Per-version vendor→canonical type aliases for
    #: :class:`core.normalization.type_mapper.CanonicalTypeMapper` (built
    #: from plugins at import time). Keys are ``(dialect, version_spec)``
    #: such as ``("postgresql", "9.4+")``. Plugins override with non-empty
    #: dicts; base default is empty.
    version_specific_type_mappings: ClassVar[dict[tuple[str, str], dict[str, str]]] = {}

    # ------------------------------------------------------------------
    # Capability matrix (Epic 26 followup — capabilities-onto-quirks).
    # Defaults are conservative: an unknown / placeholder dialect must
    # NOT claim to support transactions or transactional DDL, so
    # callers that fall through to ``BaseQuirks()`` degrade to the
    # safest behaviour. Each plugin's quirks subclass overrides these
    # class attributes with its real values.
    #
    # Replaces the static ``_CAPABILITIES`` dict in
    # ``core/sql_model/dialect.py``: ``get_dialect_capabilities`` now
    # builds the record from these attributes via the registry.
    # ------------------------------------------------------------------

    #: Begin/commit/rollback supported (DML, at least).
    supports_transactions: bool = False
    #: DDL participates in transactions and is rollback-able.
    supports_transactional_ddl: bool = False
    #: ``database.schema`` must be present in config after dialect defaults
    #: have had a chance to derive it from the connection settings.
    schema_required: bool = True
    #: Unquoted identifiers fold to uppercase in the catalogue.
    uppercase_identifiers: bool = False
    #: How ``clean`` enumerates schema objects: ``"native"`` or ``"introspector"``.
    clean_strategy: str = "introspector"
    #: ``sqlglot`` dialect name (or ``None`` if sqlglot has no match).
    #: Used by formatters/parsers that delegate to sqlglot.
    sqlglot_dialect: Optional[str] = None
    #: Upper-cased SQL patterns that signal sqlglot can't parse the
    #: statement faithfully. When *any* pattern appears in the
    #: uppercased SQL text, ``HybridParser`` falls back to regex-only.
    #: Plugins override to declare dialect-specific incompatibilities.
    sqlglot_unsupported_sql_patterns: "tuple[str, ...]" = ()

    # ------------------------------------------------------------------
    # DML undo-safety scanning (data corrections). The scanning mechanics
    # live dialect-free in ``db.dml_analysis``; these attributes carry the
    # only per-dialect knowledge it needs, so plugins can narrow them
    # without the data layer hard-coding any vendor SQL.
    # ------------------------------------------------------------------

    #: Quote delimiters (opening char -> closing char) the scanner skips
    #: over. Default is the union of every dialect's string/identifier
    #: quoting; plugins may narrow it.
    sql_scan_quote_pairs: ClassVar[Dict[str, str]] = dict(DEFAULT_QUOTE_PAIRS)
    #: Phrases that make an ``INSERT`` also take the UPDATE path without a
    #: following ``SET`` keyword (e.g. MySQL ``ON DUPLICATE KEY UPDATE``).
    upsert_update_set_markers: "tuple[str, ...]" = DEFAULT_UPSERT_SET_MARKERS
    #: Two-token upsert markers (both must appear) introducing a standard
    #: ``... DO UPDATE SET`` clause (e.g. PostgreSQL ``ON CONFLICT``).
    upsert_update_marker_pairs: "tuple[tuple[str, str], ...]" = DEFAULT_UPSERT_MARKER_PAIRS

    def analyze_dml(self, statement: str) -> DmlMutation:
        """Classify a DML statement for undo-safety (table, events, updated columns)."""
        return analyze_dml(
            statement,
            sqlglot_dialect=self.sqlglot_dialect,
            quote_pairs=self.sql_scan_quote_pairs,
            upsert_set_markers=self.upsert_update_set_markers,
            upsert_marker_pairs=self.upsert_update_marker_pairs,
        )

    def statement_updates_restore_key(
        self, statement: str, restore_key_columns: Sequence[str]
    ) -> bool:
        """Whether the statement assigns any of ``restore_key_columns``."""
        return updates_restore_key(
            statement,
            restore_key_columns,
            sqlglot_dialect=self.sqlglot_dialect,
            quote_pairs=self.sql_scan_quote_pairs,
            upsert_set_markers=self.upsert_update_set_markers,
        )

    def is_full_table_dml(self, statement: str) -> bool:
        """Whether the statement is an UPDATE/DELETE with no top-level WHERE."""
        return is_full_table_dml(
            statement,
            sqlglot_dialect=self.sqlglot_dialect,
            quote_pairs=self.sql_scan_quote_pairs,
        )

    def is_sqlglot_opaque_valid_ddl(self, sql_content: str) -> bool:
        """Return True if *sql_content* is valid DDL that sqlglot would
        incorrectly reject. Plugins override for dialect-specific patterns
        (e.g. PostgreSQL ``DROP TRIGGER … ON table``)."""
        return False

    def preprocess_sql_for_sqlglot(self, sql_content: str) -> str:
        """Transform SQL before passing it to sqlglot. Default: pass-through.
        Plugins override to normalize dialect-specific syntax that sqlglot
        can't handle natively."""
        return sql_content

    def normalize_column_data_type(self, col: object, data_type: str) -> str:
        """Normalize a column's data type string for DDL generation.

        Called by ``BasicTableDdlGenerator._normalize_column_data_type`` after
        the base string is extracted from ``col.data_type``. Plugins override
        to handle dialect-specific type representations:
        - SQL Server: strip ``IDENTITY`` suffix, collapse ``DATETIME(n)``
        - DB2: collapse ``TIMESTAMP(n)`` → ``TIMESTAMP``
        - PostgreSQL: strip precision from fixed-width float types, reorder
          ``TIMESTAMP {WITH|WITHOUT} TIME ZONE(n)``

        Default: passthrough (return ``data_type`` unchanged).
        """
        return data_type

    def render_identity_clause(self, col: object) -> "Optional[str]":
        """Return the identity/auto-increment clause for an identity column, or None.

        Called by ``BasicTableDdlGenerator._build_identity_clause``.  When the
        column is not an identity column the method should return ``None`` so the
        caller can fall through to the non-identity path.

        Default: None (dialect has no identity syntax, or column is not identity).
        """
        return None

    def fk_reference_bind_params(self, schema: str, table: str, column: str) -> "list[str]":
        """Return the bind-parameter list for the FK reference safety-check query.

        Most dialects use ``[schema, table, column]``.  Oracle's query references
        the schema twice and needs ``[schema, schema, table, column]``.

        Default: ``[schema, table, column]``.
        """
        return [schema, table, column]

    def derive_schema_name(self, database_config: Any) -> "Optional[str]":
        """Return a schema name derived from dialect defaults, or ``None``.

        Plugins override this when their effective schema comes from a
        non-``schema`` config field, such as MySQL's database/catalog or
        Oracle's current user. The base implementation covers dialects with
        a plain default schema name, such as PostgreSQL and SQLite.
        """
        return self.default_schema_name

    def requires_sdk_for_drop(self) -> bool:
        """Return True if DROP statements require SDK execution rather than SQL.

        CosmosDB containers cannot be dropped through SQL execution; the Azure
        SDK must be used instead. All other dialects return False.
        """
        return False

    def sdk_operation_hint_prefix(self) -> "Optional[str]":
        """Return the comment prefix to inject before SDK-executed statements, or None.

        Used by ``script_formatter`` to annotate CosmosDB SDK operations in
        generated SQL scripts. Default: None (no annotation).
        """
        return None

    def build_sdk_drop_operation(self, statement: object) -> "Optional[dict[str, Any]]":
        """Build the SDK operation dict for a DROP statement, or None.

        Called by ``generate_sql_script`` for each DROP statement when
        ``requires_sdk_for_drop()`` is True. The returned dict is stored as
        ``statement.sdk_operation`` and later passed to ``generate_sdk_script``.

        ``statement`` is a ``SqlStatement``; access attributes via ``getattr``.
        Return ``None`` to leave ``sdk_operation`` unset (no-op for this
        statement).

        Default: None (no SDK operation).
        """
        return None

    def generate_sdk_script(self, sdk_statements: "list[Any]") -> "Optional[str]":
        """Generate a dialect-specific SDK script block for ``sdk_statements``.

        Called by ``generate_sql_script`` after SQL formatting when there are
        statements with ``requires_sdk=True``. Return the full text to append
        to the generated script (including headers/comments), or ``None`` to
        skip appending.

        Default: None (no SDK script appended).
        """
        return None

    def unwrap_default_value(self, default_str: str, column: object) -> str:
        """Strip dialect-specific wrapping from a DEFAULT value string.

        SQL Server stores default values in parentheses, e.g. ``(0)`` → ``0``.
        MySQL backtick/double-quote string literals are normalised to single quotes.
        Default: return ``default_str`` unchanged.
        """
        return default_str

    # ------------------------------------------------------------------
    # Column ALTER generation hooks (Epic 27).
    # Drive ``ColumnConverter._generate_*_change`` in
    # ``core/sql_generator/diff_converters/column_converter.py``.
    # Each hook receives the pre-formatted identifiers so the plugin
    # only needs to compose the SQL string.  Return ``None`` to emit
    # a warning and skip the change; return a ``SqlStatement`` comment
    # to document a no-op (e.g. schema-less dialects).
    # ------------------------------------------------------------------

    def render_column_nullable_change(
        self,
        col_diff: object,
        formatted_table: str,
        formatted_column: str,
        dialect: str,
    ) -> "Optional[object]":
        """Return ALTER statement to add/drop NOT NULL, or None if unsupported.

        Default: None (dialect not implemented — caller logs a warning).
        """
        return None

    def render_column_default_change(
        self,
        col_diff: object,
        formatted_table: str,
        formatted_column: str,
        dialect: str,
    ) -> "Optional[object]":
        """Return ALTER statement to set/drop a column DEFAULT, or None if unsupported.

        Default: None (dialect not implemented — caller logs a warning).
        """
        return None

    def render_column_type_change(
        self,
        col_diff: object,
        formatted_table: str,
        formatted_column: str,
        dialect: str,
    ) -> "Optional[object]":
        """Return ALTER statement to change a column's data type, or None if unsupported.

        Default: None (dialect not implemented — caller logs a warning).
        """
        return None

    def render_column_collation_change(
        self,
        col_diff: object,
        formatted_table: str,
        formatted_column: str,
        dialect: str,
    ) -> "Optional[object]":
        """Return ALTER statement to change a column's collation, or None if unsupported.

        Default: None (dialect not implemented — caller logs a warning).
        """
        return None

    def round_trip_extra_object_types(self) -> "list[str]":
        """Return dialect-specific object type names to include in round-trip tests.

        ``RoundTripTester._get_supported_object_types`` extends the base list
        with this result. Plugins return names from the set:
        ``user_defined_types``, ``materialized_views``, ``extensions``,
        ``synonyms``, ``packages``, ``events``.

        Default: empty list (no dialect-specific types beyond the base set).
        """
        return []

    #: Identifier-quoting characters. Default is ANSI double-quote on
    #: both sides; MySQL uses backticks, SQL Server uses square
    #: brackets. Plugins override the two attributes.
    quote_open: str = '"'
    quote_close: str = '"'
    #: ``quote_qualified`` upper-cases the schema + identifier before
    #: quoting. Oracle folds unquoted identifiers to uppercase at CREATE
    #: TABLE time, so explicitly-quoted lower-case idents would target a
    #: non-existent object; upper-casing here matches the catalogue.
    #: Oracle ONLY — DB2 shares Oracle's identifier-folding quirks but is
    #: deliberately left untouched here to preserve historical behaviour
    #: (story 26-5).
    quote_qualified_folds_to_uppercase: bool = False
    #: Single-row SELECT statement used as a transaction-liveness
    #: probe (e.g. connection pre-flight). DB2 rejects bare ``SELECT 1``;
    #: Oracle requires ``FROM DUAL``.
    connection_probe_sql: str = "SELECT 1"
    #: ``SELECT … LIMIT N`` syntax is supported. PostgreSQL, MySQL and
    #: SQLite accept ``LIMIT``; Oracle (``FETCH FIRST N ROWS ONLY``)
    #: and DB2 (``FETCH FIRST N ROWS ONLY``) do not; SQL Server uses
    #: ``TOP N`` instead. When False, post-commit verification queries
    #: and similar probes omit the ``LIMIT`` clause.
    select_supports_limit: bool = True
    #: Default schema name when the user supplies none. ``None`` means
    #: the dialect has no default — the framework returns ``""``.
    #: PostgreSQL=``"public"``, CosmosDB=``"default"``, SQLite=``"main"``.
    #: SQL Server's "dbo" is NOT set here — it's a parser hint only
    #: (``parser_default_schema``), not an export-schema fallback.
    default_schema_name: Optional[str] = None
    #: Schema name the parser assigns to objects with no explicit schema.
    #: Falls back to ``default_schema_name`` when ``None``.
    #: SQL Server sets ``"dbo"`` here without setting ``default_schema_name``
    #: so export-schema doesn't normalize empty schemas to ``"dbo"``.
    parser_default_schema: Optional[str] = None
    #: ``DROP TABLE / VIEW / INDEX / ... IF EXISTS`` is supported.
    #: Oracle has no native ``IF EXISTS``; everyone else does.
    drop_supports_if_exists: bool = False
    #: ``DROP TABLE`` defaults to ``CASCADE`` (drop dependents).
    #: PostgreSQL is the historical only-True here. Most other
    #: dialects either don't support CASCADE in DROP TABLE or default
    #: to RESTRICT.
    drop_table_default_cascade: bool = False
    #: ``TINYINT(1)`` is an alias for BOOLEAN (MySQL convention).
    tinyint1_is_boolean: bool = False
    #: SQL literal for ``False`` in DML predicates. Oracle (NUMBER(1)),
    #: SQL Server (BIT), and SQLite (INTEGER) reject the ``FALSE``
    #: keyword and need ``"0"``; CosmosDB SQL takes lowercase
    #: ``"false"``; ANSI default is uppercase ``"FALSE"``.
    boolean_false_literal: str = "FALSE"
    #: How unquoted identifiers fold in the catalogue. One of:
    #: ``"lowercase"`` (PostgreSQL, MySQL — default),
    #: ``"uppercase"`` (Oracle, DB2),
    #: ``"case_insensitive"`` (SQL Server — stores as written, compares
    #: case-insensitively).
    #: Distinct from :attr:`uppercase_identifiers` which is a coarser
    #: ``True/False`` used by capability checks; this attribute carries
    #: the third "case-insensitive" option needed by SQL Server.
    unquoted_identifier_case: str = "lowercase"
    #: ``CREATE INDEX ... CONCURRENTLY`` is valid (PostgreSQL only).
    supports_concurrent_index: bool = False
    #: ``CREATE INDEX ... ONLINE`` is valid (SQL Server only).
    supports_online_index: bool = False
    #: The dialect uses ``GO`` as a batch separator (SQL Server / MSSQL).
    supports_go_batch_separator: bool = False
    #: This dialect belongs to the SQL Server / T-SQL family. SQL-Server-only
    #: framework branches (e.g. the alias-canonicalisation step in
    #: ``ExecutionEngine._parse_sql_statements``) gate on this instead of
    #: comparing against the literal ``"sqlserver"``. Exactly the SQL Server
    #: plugin (and its aliases ``mssql``/``tsql``/``sql_server``) sets it True.
    is_sqlserver_family: bool = False
    #: This dialect is the permissive default sqlglot *read* grammar used as
    #: the last-resort fallback when a dialect declares no ``sqlglot_dialect``
    #: of its own (e.g. DB2, CosmosDB). Exactly one native plugin (PostgreSQL,
    #: whose ``sqlglot_dialect`` is ``"postgres"``) advertises this so the
    #: undo-script generators resolve the fallback from the registry rather
    #: than hardcoding ``"postgres"``.
    is_default_sqlglot_read_fallback: bool = False
    #: This dialect is the ANSI/generic reference dialect dblift renders with
    #: when a model carries no dialect of its own (``dialect is None``). The
    #: ``SqlGeneratorFactory`` resolves a falsy dialect to the single plugin
    #: that sets this True (PostgreSQL) via
    #: :meth:`db.provider_registry.ProviderRegistry.reference_dialect_name`,
    #: so the no-dialect render default is a registry/plugin decision with no
    #: hardcoded literal in ``core/``.
    is_ansi_reference_dialect: bool = False
    #: The dialect authenticates against a cloud account (endpoint + key or
    #: managed identity) rather than the usual host/user/password. Gates the
    #: Azure-account auth validation in
    #: ``DbliftConfig.validate_complete_data``. Exactly the CosmosDB plugin
    #: sets it True; ``is_nosql`` is deliberately *not* reused because it is
    #: too generic (a future relational cloud dialect could need this, and a
    #: future non-Azure NoSQL dialect must not inherit the rule).
    requires_cloud_account_auth: bool = False
    #: NoSQL / document-store dialect (no relational DDL).
    is_nosql: bool = False
    #: How metadata queries treat the catalog argument:
    #:   ``"catalog"``   — schema arg becomes catalog (MySQL).
    #:   ``"catalog+schema"`` — separate catalog (database) and schema
    #:                          parameters (SQL Server).
    #:   ``"schema_only"`` — catalog is None, only schema (default).
    metadata_catalog_mode: str = "schema_only"
    #: Pygments lexer name for syntax-highlighting console output.
    #: Plugins override with their preferred lexer
    #: (PostgreSQL=``"postgresql"``, MySQL=``"mysql"``,
    #: SQL Server=``"tsql"``). Default ``"sql"`` works generically.
    pygments_lexer: str = "sql"
    #: Native SQLAlchemy URL query parameter names that populate
    #: ``database.schema`` during config hydration. Plugins can add aliases
    #: without teaching ``config/`` about dialect-specific spellings.
    native_url_schema_params: Tuple[str, ...] = ("currentSchema",)

    # ------------------------------------------------------------------
    # Procedure / function DDL hooks (story 26-5).
    # Drive ``Procedure._generate_basic_create_statement`` /
    # ``Parameter.__str__`` / ``Procedure.drop_statement``. Each plugin
    # overrides the deltas; defaults match the most common ANSI shape.
    # ------------------------------------------------------------------

    #: ``CREATE OR REPLACE PROCEDURE/FUNCTION`` is valid (Oracle, PostgreSQL).
    proc_supports_create_or_replace: bool = False
    #: Function return-type keyword. Oracle uses ``RETURN``; everyone
    #: else uses ``RETURNS``.
    proc_function_returns_keyword: str = "RETURNS"
    #: ``CREATE FUNCTION ... LANGUAGE plpgsql`` is supported (PostgreSQL).
    proc_supports_language_clause: bool = False
    #: Body wrap style. Opaque internal key (not a dialect name). One of:
    #:   ``"plain"`` (``AS\n{body}``)
    #:   ``"begin_end"`` (``AS\nBEGIN\n{body}\nEND``)
    #:   ``"dollar_quotes"`` (``AS $$\n{body}\n$$``)
    #:   ``"mysql_characteristics"`` (BEGIN/END plus characteristics — handled by
    #:   Procedure._render_mysql_body()).
    proc_body_wrap_style: str = "plain"
    #: Procedure ``DROP`` accepts ``IF EXISTS``. Oracle is the only
    #: ANSI dialect without it.
    proc_drop_supports_if_exists: bool = True
    #: Keyword for an INOUT parameter. SQL Server uses ``OUTPUT``;
    #: others use ``INOUT``.
    proc_param_inout_keyword: str = "INOUT"
    #: Procedure parameters accept ``= default``. DB2 does not.
    proc_param_supports_default: bool = True

    # ------------------------------------------------------------------
    # Index DDL hooks (story 26-5).
    # Drive ``Index._generate_basic_create_statement`` /
    # ``Index.drop_statement``.
    # ------------------------------------------------------------------

    #: Whether ``CREATE INDEX schema.idx`` qualifies the index name with
    #: its own schema. PostgreSQL / SQL Server / MySQL / MariaDB store
    #: the index in the table's schema, so the prefix is dropped.
    index_qualifies_with_schema: bool = True
    #: ``CREATE ONLINE INDEX`` / ``CREATE OFFLINE INDEX`` keyword (MySQL).
    index_supports_online_offline: bool = False
    #: ``USING <method>`` clause after ``CREATE INDEX ... ON tbl USING gin (...)``
    #: (PostgreSQL non-BTREE index types).
    index_supports_using_clause: bool = False
    #: ``CREATE BITMAP INDEX`` keyword variant (Oracle).
    index_supports_bitmap: bool = False
    #: ``CREATE INDEX ... LOCAL`` for partitioned-table indexes (Oracle).
    index_supports_local_partitioned: bool = False
    #: ``TABLESPACE foo`` clause (Oracle).
    index_supports_tablespace: bool = False
    #: Index types that do *not* accept ASC/DESC sort directions
    #: (PostgreSQL: GIN/GIST/BRIN/HASH/SPGIST). Names are uppercase.
    index_no_sort_types: "frozenset[str]" = frozenset()
    #: ``WITH (...)`` storage-options style. ``""`` = no options
    #: supported; ``"lowercase"`` = PG (``fillfactor=...``);
    #: ``"uppercase"`` = SQL Server (``FILLFACTOR=...``).
    index_with_options_style: str = ""
    #: ``DROP INDEX idx ON tbl`` shape — index name is bound to the
    #: table (SQL Server, MySQL, MariaDB).
    index_drop_includes_table: bool = False
    #: ``DROP INDEX IF EXISTS`` is supported in the
    #: index-bound-to-table shape (SQL Server: yes; MySQL: no).
    index_drop_table_form_supports_if_exists: bool = True
    #: ``DROP INDEX IF EXISTS`` is supported in the standalone shape
    #: (PostgreSQL, SQLite: yes; Oracle, DB2: no).
    index_drop_standalone_supports_if_exists: bool = True
    #: MySQL allows index-type prefixes in the CREATE INDEX header
    #: (FULLTEXT, SPATIAL, etc.).
    index_supports_mysql_typed_keywords: bool = False
    #: Comparator: dialect's canonical default index type used for normalization
    #: (e.g. ``BTREE`` for PG/MySQL, ``NONCLUSTERED`` for SQL Server,
    #: ``NORMAL`` for Oracle, ``REGULAR`` for DB2). The comparator treats
    #: ``BTREE`` and the dialect default as equivalent.
    default_index_type: str = "BTREE"
    #: Comparator: SERIAL/BIGSERIAL/SMALLSERIAL data types alias to
    #: INTEGER/BIGINT/SMALLINT respectively (PostgreSQL identity columns).
    serial_types_alias_integer: bool = False
    #: ``import-flyway`` reads the *source* Flyway table by its exact name
    #: rather than through ``get_applied_migrations`` (which folds the name
    #: to the dialect's catalogue case). True only for dialects whose
    #: history-name normalisation would otherwise miss a verbatim-cased
    #: Flyway table — Oracle, where ``get_applied_migrations`` uppercases.
    flyway_source_table_case_sensitive: bool = False

    # ------------------------------------------------------------------
    # Trigger DDL hooks (story 26-5).
    # Drive ``Trigger._generate_basic_create_statement`` and
    # ``Trigger._format_body``.
    # ------------------------------------------------------------------

    #: ``CREATE DEFINER = user@host TRIGGER`` is valid (MySQL/MariaDB).
    trigger_supports_definer_clause: bool = False
    #: ``FOR EACH ROW`` clause is emitted for row-level triggers.
    #: SQL Server has no ``FOR EACH ROW`` syntax — set to False there.
    trigger_supports_for_each_row: bool = True
    #: Statement terminator appended after the trigger body. Oracle
    #: SQL*Plus blocks end with ``\n/``; everyone else uses empty.
    trigger_terminator: str = ""

    def wrap_trigger_body(self, body: str) -> str:
        """Wrap a trigger body in dialect-specific delimiters.

        Default: strip surrounding whitespace and normalise empty input
        to an empty string. The pre-PR-C3 ``Trigger._format_body``
        always did this, regardless of dialect, so the base behaviour
        preserves that contract. Oracle overrides to additionally wrap
        the stripped body in ``BEGIN`` / ``END;`` when missing (valid
        PL/SQL block).
        """
        return (body or "").strip()

    def render_computed_column(
        self, col: Any, formatted_col_name: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Render a computed/generated column to ``(suffix_clause, new_parts0)``.

        ``suffix_clause`` is appended to the column DDL after the column type;
        ``new_parts0`` (when non-None) replaces the column-name+type prefix
        — used by SQL Server's ``col AS (expr) [PERSISTED]`` shape, where the
        type is omitted entirely.

        Default (``standard`` / DB2 / SQLite): ``GENERATED ALWAYS AS (expr)``.
        Override in plugin quirks for dialect-specific syntax (PR-G8).
        """
        if not getattr(col, "is_computed", False) or not getattr(col, "computed_expression", None):
            return None, None
        return f"GENERATED ALWAYS AS ({col.computed_expression})", None

    # ------------------------------------------------------------------
    # Sequence DDL hooks (story 26-5).
    # Drive ``Sequence._generate_basic_create_statement`` and
    # ``Sequence.drop_statement``.
    # ------------------------------------------------------------------

    #: ``CREATE TEMPORARY SEQUENCE`` is valid (PostgreSQL only).
    seq_supports_temp: bool = False
    #: Keyword for "do not cycle". Oracle / PostgreSQL / DB2 use
    #: ``NOCYCLE`` (no space); SQL Server uses ``NO CYCLE``.
    seq_nocycle_keyword: str = "NOCYCLE"
    #: When ``cache`` is unset, append ``NOCACHE`` (Oracle behaviour).
    seq_default_nocache_when_unset: bool = False
    #: Oracle treats ``CACHE 1`` (or 0) as ``NOCACHE``.
    seq_cache_one_means_nocache: bool = False
    #: ``DROP SEQUENCE IF EXISTS`` is supported (everyone except Oracle).
    seq_drop_supports_if_exists: bool = True
    #: Implicit "no max" sentinel for sequences. DB2 uses ``2**63 - 1``.
    #: ``None`` means no sentinel — comparison uses raw values.
    seq_implicit_max_value: Optional[int] = None

    # ------------------------------------------------------------------
    # Synonym DDL hooks (story 26-5).
    # Drive ``Synonym._generate_basic_create_statement`` and
    # ``Synonym.drop_statement``.
    # ------------------------------------------------------------------

    #: SYNONYM keyword. DB2 calls them ``ALIAS``; everyone else
    #: ``SYNONYM``. Used in CREATE / DROP statements.
    synonym_keyword: str = "SYNONYM"
    #: ``CREATE OR REPLACE SYNONYM`` is valid (Oracle only).
    synonym_supports_create_or_replace: bool = False

    # ------------------------------------------------------------------
    # View DDL hooks (story 26-5).
    # ------------------------------------------------------------------

    #: ``CREATE VIEW ... WITH (security_definer=true)`` clause
    #: (PostgreSQL only).
    view_supports_security_with_clause: bool = False
    #: ``DROP VIEW IF EXISTS`` is supported (everyone except Oracle).
    view_drop_supports_if_exists: bool = True

    # ------------------------------------------------------------------
    # Misc DDL flags (story 26-5).
    # ------------------------------------------------------------------

    #: Event scheduler supports MySQL-style ``STARTS '...'`` /
    #: ``ENDS '...'`` / ``AT '...'`` timestamp literal quoting.
    #: Only MySQL/MariaDB have CREATE EVENT.
    event_supports_mysql_schedule: bool = False
    #: ``CREATE TYPE ... AS OBJECT`` body uses semicolons (Oracle only).
    udt_object_body_uses_semicolons: bool = False
    #: Oracle composite types add ``" OBJECT"`` after ``AS``
    #: (``CREATE TYPE foo AS OBJECT (...)``).
    udt_composite_object_modifier: str = ""
    #: SQL Server distinct-type syntax: ``CREATE TYPE x FROM base`` vs.
    #: standard ``CREATE DISTINCT TYPE x AS base`` everywhere else.
    udt_distinct_uses_from_syntax: bool = False
    #: ``CREATE TABLE`` references ``ON [PRIMARY]`` / ``TEXTIMAGE_ON``
    #: (SQL Server filegroup syntax, used in cross-dialect comparisons).
    table_uses_filegroup_syntax: bool = False
    #: Oracle SQL*Plus preprocessing (DEFINE substitution, WHENEVER
    #: SQLERROR filtering). Only Oracle.
    supports_sqlplus_preprocessing: bool = False

    # ------------------------------------------------------------------
    # Table DDL generation hooks (story 26-5).
    # Drive ``BasicTableDdlGenerator`` dispatch.
    # ------------------------------------------------------------------

    #: DROP TABLE style. ``"cascade_constraints"`` → ``DROP TABLE x CASCADE
    #: CONSTRAINTS`` (Oracle); ``"if_exists"`` → ``DROP TABLE IF EXISTS x``
    #: (MySQL); ``"if_exists_cascade"`` → ``DROP TABLE IF EXISTS x CASCADE``
    #: (default — PG/MSSQL/DB2).
    table_drop_style: str = "if_exists_cascade"
    #: CREATE TABLE header for non-temporary tables uses
    #: ``CREATE CONTAINER`` (CosmosDB NoSQL quirk).
    table_create_keyword: str = "TABLE"
    #: Temporary table syntax. ``"global_temporary"`` for Oracle,
    #: ``"hash_prefix"`` for SQL Server, ``"temporary"`` for standard.
    table_temporary_style: str = "temporary"
    #: CHECK constraints must be added post-CREATE via ALTER (DB2).
    table_check_via_alter: bool = False
    #: Self-referencing FKs must be added post-CREATE via ALTER (DB2).
    table_self_ref_fk_via_alter: bool = False
    #: Inline COLLATE clause supported for character columns.
    table_supports_inline_collate: bool = False
    #: NOT NULL is implicit for identity-PK columns (DB2).
    table_not_null_implicit_on_identity_pk: bool = False
    #: NOT NULL is implicit for inline-PK columns (Oracle).
    table_not_null_implicit_on_inline_pk: bool = False
    #: Single-column UNIQUE constraints inlined in column def (DB2).
    table_inline_unique_single_col: bool = False
    #: FK ON UPDATE suppressed in DDL (Oracle does not support it).
    table_fk_suppress_on_update: bool = False
    #: Constraint deferrable clauses supported (PG, Oracle).
    table_supports_deferrable_constraints: bool = False
    #: Constraint enable/validate/disable/novalidate (Oracle).
    table_supports_constraint_state: bool = False
    #: Constraint WITH NOCHECK (SQL Server).
    table_supports_constraint_nocheck: bool = False
    #: Tablespace clause format. ``"quoted"`` (Oracle), ``"plain"``
    #: (PG/MySQL/MSSQL), ``"skip"`` (DB2 — tablespace in CREATE not used).
    table_tablespace_style: str = "plain"
    #: Oracle storage parameters (PCTFREE, PCTUSED, INITIAL, NEXT).
    table_supports_storage_params: bool = False
    #: MySQL/MariaDB ``ENGINE=`` storage-engine clause (and the sibling
    #: ROW_FORMAT / table COLLATE / AUTO_INCREMENT / CREATE_OPTIONS table
    #: options). Identifies the canonical plugin that owns the ``mysql``
    #: ``dialect_options`` namespace so framework code resolves it from the
    #: registry instead of a hardcoded dialect literal (ADR-26 E story 26-5).
    table_uses_storage_engine_clause: bool = False
    #: PostgreSQL ``INHERITS (parent1, parent2)`` clause.
    table_supports_inherits: bool = False
    #: Dialect inlines single-column PKs when there is no composite PK.
    #: Oracle and DB2 always inline via ``table_not_null_implicit_on_inline_pk``
    #: / ``table_check_via_alter``; this flag covers the PostgreSQL case where
    #: inlining is preferred but only when ``len(pk_constraints) <= 1``.
    table_prefers_inline_single_pk: bool = False
    #: MySQL/MariaDB CHECK expression cleanup (strip _utf8mb4 prefixes).
    table_check_strip_utf8mb4: bool = False

    def __init__(self, dialect_name: str = "") -> None:
        """Initialize the quirks instance with an optional ``dialect_name``.

        Empty ``dialect_name`` is allowed and signals "no dialect context"
        — the framework calls into ``BaseQuirks()`` from paths where the
        dialect is unknown (e.g. ``SqlGenerator.generate_ddl(dialect=None)``).
        All hooks return their generic defaults in that case. (PR #241 Bugbot.)
        """
        self.dialect_name = dialect_name

    # ------------------------------------------------------------------
    # Migration-script preprocessing hooks (Tier 1 plugin-isolation).
    # Replace 8 direct ``from db.plugins.<oracle|sqlserver>...`` imports
    # in core/. Defaults are no-ops; Oracle and SQL Server override via
    # lazy imports of their own plugin modules so core never has to.
    # ------------------------------------------------------------------

    def extract_script_context(self, sql: str) -> Optional[object]:
        """Return dialect-specific script-execution context, or ``None``.

        The returned object is opaque to core; it exposes (at most) the
        generic attributes ``wants_session_output: bool`` and
        ``prompts: list[str]`` that core reads via ``getattr``. Plugins
        may attach additional state used by their own
        :meth:`terminate_script_directives` /
        :meth:`apply_script_substitution` overrides.

        Default: ``None`` (dialect has no script-level execution context).
        """
        return None

    def terminate_script_directives(self, sql: str) -> str:
        """Append statement terminators to dialect-specific directive lines.

        Default: pass-through. Oracle overrides for SQL*Plus directives
        that are line-terminated rather than ``;``-terminated.
        """
        return sql

    def apply_script_substitution(self, sql: str, ctx: Optional[object]) -> str:
        """Substitute dialect-specific script variables in *sql* using *ctx*.

        Default: pass-through. Oracle overrides for SQL*Plus ``&var`` /
        ``&&var`` substitution.
        """
        return sql

    def is_script_directive(self, stmt: str) -> bool:
        """Return ``True`` when *stmt* is a non-executable client-side directive.

        Default: ``False``. Oracle overrides for SQL*Plus directives
        (``SET``, ``SPOOL``, ``DEFINE``, …) so the statement splitter can
        drop them before handing the rest to the SQL executor.
        """
        return False

    def parse_error_policy_directive(self, stmt: str) -> Optional[str]:
        """Parse a positional error-handling directive and return its policy.

        Returns ``"continue"`` or ``"exit"`` for Oracle ``WHENEVER SQLERROR``;
        ``None`` otherwise. Default: ``None``.
        """
        return None

    def is_batch_separator(self, stmt: str) -> bool:
        """Return ``True`` when *stmt* is a non-executable batch separator.

        Default: ``False``. SQL Server overrides for the T-SQL ``GO``
        separator emitted by SSMS / sqlcmd scripts.
        """
        return False

    def enable_session_output(self, connection: Any) -> None:
        """Enable dialect-specific session-level output capture.

        Default: no-op. Oracle overrides to enable ``DBMS_OUTPUT`` on the
        active database connection so DBMS_OUTPUT.PUT_LINE messages can be
        drained and surfaced via :meth:`read_session_output`.
        """
        return None

    def read_session_output(self, connection: Any, log: Any) -> None:
        """Drain pending session-level output from *connection* and route to *log*.

        Default: no-op. Oracle overrides to drain ``DBMS_OUTPUT``.
        """
        return None

    # ------------------------------------------------------------------
    # ErrorQuirks (ADR-26 T0)
    # ------------------------------------------------------------------

    def error_patterns(self) -> "list[tuple[re.Pattern[str], Any]]":
        """Default: no dialect-specific error-classification patterns."""
        return []

    # ------------------------------------------------------------------
    # ConnectionQuirks (ADR-26 T0)
    # ------------------------------------------------------------------

    def engine_pool_options(self) -> "dict[str, Any]":
        """Default: no dialect-specific engine/pool kwargs."""
        return {}

    # ------------------------------------------------------------------
    # DdlQuirks (story 26-3)
    # ------------------------------------------------------------------

    def ddl_generator_class(self) -> None:
        """OSS builds do not ship SQL generator implementations."""
        return None

    def alter_generator_class(self) -> None:
        """OSS builds do not ship ALTER generator implementations."""
        return None

    def parser_class(self, parser_type: str) -> Optional[type]:
        """Return the parser class for ``parser_type``, or ``None``.

        ``parser_type`` is one of ``"hybrid"``, ``"regex"``, or
        ``"sqlglot"``. Default returns None for every type. Plugins
        override to return their own parser class via lazy import
        (parser modules pull in heavy deps like ``sqlglot``, so we
        avoid importing them at quirks-class load time).

        Story 26-9 / 26-4 first slice: replaces the three static
        ``PARSER_MAP`` / ``REGEX_PARSER_MAP`` / ``SQLGLOT_PARSER_MAP``
        dicts in ``core/sql_parser/parser_factory.py``.
        """
        return None

    def normalize_view_name(self, name: str) -> str:
        """Normalize a raw catalog view name before downstream lookups.

        Default: return *name* unchanged. DB2 overrides to lowercase
        the name because the surrounding code path
        (``_get_object_column_names``) compares case-sensitively
        against catalog rows that come back lowercased.
        """
        return name

    def enrich_view_from_row(self, view: Any, row: Dict[str, Any], view_status: Any = None) -> None:
        """Add dialect-specific attributes to *view* from a vendor-query row.

        Called by the view extraction flow after the canonical ``View(...)``
        is constructed. Default: no-op. Plugins override to capture attributes
        that only exist on their dialect:

          * MySQL / MariaDB pulls ``DEFINER`` (and elsewhere ``algorithm``,
            ``sql_security``) from the catalog row.
          * PostgreSQL pulls ``security_definer`` / ``security_invoker``
            flags from ``pg_views`` + ``pg_proc`` joins.

        ``view_status`` is the same opaque ``ObjectCaptureStatus`` tracker
        passed to :meth:`enrich_trigger_from_row` — plugins call
        ``add_property_status(name, captured)`` when they look for a
        dialect-specific attribute so the introspection summary can
        report "definer captured: yes / no".
        """
        return None

    def enrich_materialized_view_from_row(self, mview: Any, row: Dict[str, Any]) -> None:
        """Add dialect-specific attributes to *mview* from a vendor-query row.

        Default: no-op. PostgreSQL overrides — its
        ``pg_matviews`` view exposes a ``relpersistence`` projection as
        ``is_unlogged`` (``"YES"`` / ``"NO"``).
        """
        return None

    #: Vendor-specific table-name prefixes that identify objects
    #: created by the engine to support its own materialized-view
    #: machinery (Oracle: ``MLOG$``, ``MVIEW$_``, ``SNAP$``, ``AQ$``,
    #: ``DR$`` …). Tables whose names start with any of these prefixes
    #: are filtered out of user-facing introspection results, and a
    #: non-empty tuple also tells :class:`TableExtractor` that it must
    #: preload materialized-view names so it can drop them from the
    #: vendor table listing. Default: empty tuple (no filtering).
    materialized_view_support_table_prefixes: Tuple[str, ...] = ()

    def enrich_table_extra(self, extractor: Any, schema: str, table_name: str, table: Any) -> None:
        """Apply dialect-specific table enrichment that needs extra catalog queries.

        Default: no-op. PostgreSQL overrides to capture row-security
        flags, single-table inheritance parents, and row-level security
        policies. The *extractor* gives the hook access to
        ``provider.query_executor``, ``connection``, ``vendor_queries``,
        ``get_row_value`` / ``parse_json_array`` helpers, and the
        ``track_warning`` sink.
        """
        return None

    def supplement_table_list(
        self, extractor: Any, schema: str, existing_tables: "list[Any]"
    ) -> "list[Any]":
        """Add tables that the dialect's base table query missed.

        Default: returns *existing_tables* unchanged. PostgreSQL
        overrides to append declarative-partitioned tables (``relkind
        = 'p'``) — the generic table query doesn't report them as ``TABLE``,
        so a vendor query is needed. The hook is responsible for
        populating columns and constraints on any new tables it
        creates by calling ``extractor.column_extractor`` /
        ``extractor.constraint_extractor`` when those are available.
        """
        return existing_tables

    def is_temporary_sequence(self, row: Dict[str, Any]) -> bool:
        """Return ``True`` if the catalog *row* describes a temporary sequence.

        Default: ``False``. PostgreSQL overrides — its
        ``pg_catalog.pg_class`` view exposes a ``relpersistence``
        column projected as ``is_temporary`` (``"YES"`` / ``"NO"``)
        by the PG vendor query.
        """
        return False

    def is_generated_not_null_check(self, row: Dict[str, Any], check_expr: str) -> bool:
        """Whether *row* is a system-generated ``IS NOT NULL`` check constraint.

        Default: ``False`` — non-Oracle dialects don't have this concept,
        so their check constraints are always kept. Oracle overrides to
        drop the implicit ``"<col>" IS NOT NULL`` constraints it creates
        for ``NOT NULL`` columns (``GENERATED NAME`` in the catalog).
        """
        return False

    def is_internal_sequence(self, sequence: Any) -> bool:
        """Return ``True`` to exclude *sequence* from user-facing results.

        Default: ``False``. Oracle overrides — its IDENTITY columns
        auto-generate backing sequences named ``ISEQ$$_<oid>`` that
        live in the user schema but aren't user-authored.
        """
        return False

    def should_skip_index(self, name: str) -> bool:
        """Whether the catalog *name* identifies an engine-internal index.

        Default: ``False``. Oracle overrides to drop ``SYS_*`` / ``SYS$*``
        system-generated index names that show up in ``ALL_INDEXES``.
        """
        return False

    def normalize_index_predicate(self, predicate: Optional[str]) -> Optional[str]:
        """Normalize a partial-index WHERE clause before storing it.

        Default: return *predicate* unchanged. PostgreSQL strips
        redundant ``::TEXT`` and ``CAST(<col> AS TEXT)`` decorations
        that the catalog re-introduces during introspection so the
        predicate compares equal to the source DDL.
        """
        return predicate

    def is_index_hidden_column(self, name: str) -> bool:
        """Whether *name* is an engine-generated hidden column in an index.

        Default: ``False``. Oracle overrides — function-based indexes
        materialize their expression columns under ``SYS_NCxxx``-style
        names which must be replaced by the original expression text
        when building the ``Index`` row.
        """
        return False

    def apply_index_vendor_properties(
        self, idx_data: Dict[str, Any], index_kwargs: Dict[str, Any]
    ) -> None:
        """Copy dialect-specific index fields from *idx_data* into *index_kwargs*.

        Default: no-op. Plugins override to surface their own knobs:

          * PostgreSQL: ``concurrently`` flag + ``tablespace``.
          * MySQL: carry over ``FULLTEXT`` / ``SPATIAL`` types.
          * Oracle: ``BITMAP`` type, ``tablespace``, and partition
            ``LOCAL`` / ``GLOBAL`` locality.
        """
        return None

    def fetch_unique_constraints(
        self, extractor: Any, schema: str, table: str
    ) -> "Optional[list[Any]]":
        """Fetch UNIQUE constraints for *table* using dialect-specific SQL.

        Default: ``None`` → caller falls through to the generic vendor-query
        path. Plugins override to use their richer catalog views:

          * DB2: ``SYSCAT.TABCONST`` (``TYPE='U'``).
          * SQL Server: ``sys.key_constraints`` (``type='UQ'``).
          * Oracle: ``vendor_queries.get_indexes_query`` filtered to
            unique non-PK indexes.
          * PostgreSQL: ``pg_constraint`` (``contype='u'``) — required
            so partial unique indexes stay in the *index* extractor
            path instead of collapsing into named UNIQUE constraints.
        """
        return None

    def sanitize_constraint_name(self, name: "Optional[str]") -> "Optional[str]":
        """Strip engine-generated constraint names; return ``None`` to drop.

        Default: returns *name* unchanged. Oracle drops ``SYS_*`` and
        ``SYS$*``; DB2 drops the ``SQL\\d+`` constraint pattern used
        for system-generated names in SYSCAT.
        """
        return name

    #: ``TIMESTAMP`` / ``TIME`` types take only the fractional-seconds
    #: argument (``TIMESTAMP(6)``), never a width-+-scale pair. PostgreSQL,
    #: Oracle, and DB2 all behave this way; defaults to ``False`` so other
    #: dialects fall through to the generic ``(width, scale)`` formatter.
    time_type_supports_only_fractional_precision: bool = False

    #: Catalog sentinels that the dialect uses to encode ``VARCHAR(MAX)`` /
    #: ``NVARCHAR(MAX)``. SQL Server reports either ``-1`` or
    #: ``2147483647`` for unbounded character types; when ``column_size``
    #: matches an entry the extractor emits ``(MAX)``.
    varchar_max_sentinel_sizes: Tuple[int, ...] = ()

    #: DB2 catalog data can require an identity-column fallback path;
    #: setting this to ``True`` enables a catalog-fallback path
    #: (``column_name`` in the preloaded identity set). Only DB2 enables
    #: this today.
    identity_uses_catalog_fallback: bool = False

    def correct_computed_column_flag(
        self, is_generated: bool, column_def: "Optional[str]", is_identity: bool
    ) -> bool:
        """Correct the generated-column flag for known catalog quirks.

        Default: returns *is_generated* unchanged. Plugins override to
        suppress false positives:

          * MySQL marks ``DEFAULT CURRENT_TIMESTAMP`` columns as
            generated — drop the flag when the default isn't a
            ``GENERATED ...`` clause.
          * DB2 marks IDENTITY columns as generated — drop the
            flag when ``is_identity`` is true.
        """
        return is_generated

    def enhance_columns(
        self, extractor: Any, schema: str, table: str, columns: "list[Any]"
    ) -> None:
        """Post-process the columns list with dialect-specific catalog data.

        Default: no-op. Plugins override to plug in extra queries:

          * SQL Server augments default values from ``sys.default_constraints``.
          * MySQL / MariaDB replace bare ``ENUM`` with the full
            ``enum('a','b',…)`` definition from ``COLUMN_TYPE``.
        """
        return None

    def clean_source_text(self, text: "Optional[str]") -> "Optional[str]":
        """Normalize raw routine / package source text.

        Default: returns *text* unchanged. Oracle overrides to remove
        the XML ``<E>...</E>`` aggregator markup and unescape entities
        that ``DBMS_METADATA`` injects when concatenating PL/SQL source
        rows across ``ALL_SOURCE``.
        """
        return text

    def normalize_partition_bound(self, value: Any) -> Any:
        """Normalize a partition boundary expression for readability.

        Default: returns *value* unchanged. Oracle overrides to collapse
        the ``TO_DATE(...,'SYYYY-MM-DD HH24:MI:SS','NLS_CALENDAR=...')``
        expressions that ``ALL_TAB_PARTITIONS`` emits into a plain
        ``YYYY-MM-DD`` literal when the time component is midnight.
        """
        return value

    def extract_partition_scheme_from_row(
        self, extractor: Any, row: Dict[str, Any], table: Any
    ) -> None:
        """Read partition method + columns from the vendor catalog row
        and set them on *table*.

        Default: no-op. Each plugin overrides because the projection
        differs:

          * Oracle: ``partitioning_type`` + ``partition_columns``
          * PostgreSQL: ``partition_definition`` parsed
            (``RANGE (col)`` etc.)
          * MySQL: ``partition_method`` + ``partition_expression``
            (with SQL-function stripping)
          * DB2: ``partition_definition`` (always RANGE)
          * SQL Server: ``partition_function`` + ``partition_type``
            + ``partition_columns``
        """
        return None

    #: Whether the dialect provides a view ``ALGORITHM`` clause that the
    #: introspector should record as a per-property capture status. Only
    #: MySQL / MariaDB (where the clause exists in the grammar) set this
    #: to True; other dialects can skip the capture tracking entirely.
    provides_view_algorithm: bool = False

    def fetch_view_algorithm(self, extractor: Any, schema: str, view_name: str) -> "Optional[str]":
        """Look up a view's algorithm (e.g. ``MERGE`` / ``TEMPTABLE``
        / ``UNDEFINED``) from a vendor-specific call.

        Default: ``None``. MySQL / MariaDB overrides via ``SHOW CREATE
        VIEW`` because ``information_schema.VIEWS`` doesn't expose the
        algorithm column.
        """
        return None

    def extract_computed_column_expression(self, text: "Optional[str]") -> "Optional[str]":
        """Strip the vendor's generation-clause wrapper from a
        catalog-returned computed-column expression.

        Default: returns *text* unchanged. DB2 overrides because its
        SYSCAT.COLUMNS.TEXT projection embeds the bare expression
        inside ``GENERATED ALWAYS AS (...)`` and the consumer needs
        the inner expression only.
        """
        return text

    def enrich_packages_from_catalog(
        self, extractor: Any, schema: str, packages: "list[Any]"
    ) -> None:
        """Fill in package source code from a vendor-specific catalog.

        Default: no-op. Oracle overrides to pull ``PACKAGE`` /
        ``PACKAGE BODY`` text from ``ALL_SOURCE`` (and from the
        per-extractor ``_oracle_package_specs`` cache populated by the
        procedure extractor) for packages that came back from the
        vendor query without an attached definition.
        """
        return None

    def filter_user_defined_types(
        self,
        extractor: Any,
        schema: str,
        user_defined_types: "list[Any]",
        get_tables_fn: Any,
    ) -> "list[Any]":
        """Filter the vendor-returned UDT list before it leaves the extractor.

        Default: returns *user_defined_types* unchanged. PostgreSQL
        overrides to drop the auto-created composite types that
        ``pg_type`` emits for every regular table — only explicitly
        ``CREATE TYPE ... AS (...)`` composites should surface to the
        user.
        """
        return user_defined_types

    def script_header_session_init(self) -> "list[str]":
        """Lines to prepend to a generated DDL script's header.

        Default: empty list. SQL Server overrides to inject
        ``SET ANSI_NULLS ON;`` / ``SET QUOTED_IDENTIFIER ON;`` so the
        emitted script behaves consistently regardless of the
        connection's default settings.
        """
        return []

    def fetch_routine_parameters_fallback(
        self, extractor: Any, schema: str, name: str, kind: str
    ) -> "list[Any]":
        """Catalog-based parameter fallback for procedures and functions.

        Default: empty list. Plugins override when the JSON parameter
        payload from the main routines query comes back empty:

          * MySQL queries ``information_schema.PARAMETERS``.
          * Oracle queries ``ALL_ARGUMENTS`` (procedures only — the
            function flow has its own DBMS_METADATA-driven path).

        ``kind`` is ``"procedure"`` or ``"function"``.
        """
        return []

    def fetch_routine_full_definition(
        self,
        extractor: Any,
        schema: str,
        name: str,
        kind: str,
        routine: Any,
        status: Any = None,
    ) -> None:
        """Update ``routine.definition`` (and possibly ``routine.body``)
        from a catalog-side DDL query.

        Default: no-op. Plugins override:

          * MySQL skips when ``routine.definition`` is already set,
            otherwise issues ``SHOW CREATE PROCEDURE`` / ``SHOW CREATE
            FUNCTION`` (BUG-01: ``information_schema.ROUTINES`` exposes
            only the body, not the full CREATE statement) and refreshes
            ``routine.body`` from the ``BEGIN`` offset.
          * Oracle always issues ``DBMS_METADATA.GET_DDL`` — its
            authoritative reconstruction takes precedence over the row
            text — and clears ``routine.body`` (DBMS_METADATA returns
            the full DDL, ``body`` becomes redundant).

        ``status`` is the ``ObjectCaptureStatus`` tracker (or ``None``);
        the override marks ``definition`` failures on it when needed.
        """
        return None

    def apply_routine_volatility_from_row(
        self, extractor: Any, routine: Any, row: Dict[str, Any]
    ) -> None:
        """Derive ``routine.volatility`` from a row column other than
        ``volatility`` itself.

        Called *before* the row's ``volatility`` projection is applied,
        so plugin-side derivation acts as a fallback that the row can
        still override. Default: no-op.

        Plugins override:

          * MySQL: empty / missing ``is_deterministic`` falls through
            to ``VOLATILE``; ``YES`` maps to ``IMMUTABLE``.
          * SQL Server: ``is_deterministic`` (``0`` / ``1`` / ``YES``
            / ``TRUE``) → ``IMMUTABLE`` / ``VOLATILE`` for functions.
        """
        return None

    def apply_routine_definer_from_row(
        self, extractor: Any, routine: Any, row: Dict[str, Any]
    ) -> None:
        """Apply the row's ``definer`` column to ``routine.definer``.

        Called *after* the generic ``execute_as_principal`` /
        ``EXECUTE AS OWNER`` detection in the main flow, preserving
        the legacy precedence in which MySQL's ``definer`` column had
        final authority. Default: no-op.

        Plugins override:

          * MySQL / MariaDB: copy ``row['definer']`` (``user@host``).
        """
        return None

    def postprocess_routine(self, extractor: Any, schema: str, routine: Any) -> None:
        """Final cleanup pass on a built procedure / function.

        Default: no-op. Oracle strips embedded ``CREATE OR REPLACE
        PACKAGE`` specs from procedure definitions (they're cached for
        later use during the misc-object pass)."""
        return None

    def enrich_trigger_from_row(
        self, trigger: Any, row: Dict[str, Any], trigger_status: Any = None
    ) -> None:
        """Add dialect-specific attributes to *trigger* from a vendor-query row.

        Called by the trigger extraction flow after the canonical
        ``Trigger(name=..., schema=..., timing=..., events=[], ...)`` is
        constructed. Default: no-op. Plugins override to capture attributes
        that only exist on their dialect:

          * MySQL / MariaDB pull ``DEFINER`` from the catalog row.

        ``trigger_status`` is an opaque tracker (``ObjectCaptureStatus`` or
        ``None``) — when present, plugins call its
        ``add_property_status(property_name, captured: bool)`` for any
        dialect-specific attribute they look for, so the introspection
        result summary can surface "definer captured: yes / no".
        """
        return None

    def apply_vendor_table_properties(self, table: Any, row: Dict[str, Any]) -> None:
        """Apply dialect-specific table properties from a vendor-query row.

        Called after ``vendor_queries.get_table_properties_query`` returns a
        result row. Default: no-op. Plugins override to enrich the
        introspected ``Table`` with dialect-specific attributes (SQL Server
        filegroup / memory-optimised / system-versioned, DB2 tablespace +
        compression, Oracle tablespace + storage params, MySQL storage_engine
        + row_format + collation + create_options).

        ``table`` is typed ``Any`` because each plugin assigns to a
        different set of attributes (filegroup, tablespace,
        storage_engine, ...) — the structural-typing surface diverges
        per dialect and pinning a Protocol here would be noise.
        """
        return None

    def render_drop_for_object(
        self,
        obj_type: str,
        obj_name: str,
        schema_prefix: str,
        table_name: Optional[str],
    ) -> Optional[str]:
        """Default: defer to the generic ``DROP ... IF EXISTS`` fallback."""
        return None

    def skip_index_ddl(self) -> bool:
        """Default: dialect manages indexes via SQL DDL."""
        return False

    def skip_index_ddl_comment(self) -> str:
        """Comment emitted when ``skip_index_ddl()`` returns True.

        Returned by the framework verbatim when an INDEX is encountered
        for a dialect that manages indexes outside SQL DDL. Plugins
        that set ``skip_index_ddl=True`` should override this with a
        dialect-appropriate explanation. Default is intentionally
        generic so the framework never names a dialect.
        """
        return (
            "-- This dialect manages indexes outside SQL DDL.\n"
            "-- Update the index policy via the database's native API."
        )

    def requires_dialect_specific_wrapping(self, object_type_name: str) -> bool:
        """Default: no delimiter wrapping required.

        Used by ``SqlGenerator.generate_ddl`` to decide whether to call
        ``wrap_dialect_specific_block`` around an object's CREATE
        statement. MySQL covers procedures/functions here; the wider
        set covering triggers/events is exposed via the separate
        ``requires_block_delimiter_wrapping`` hook (different code
        path, different separator).
        """
        return False

    def wrap_dialect_specific_block(self, sql: str) -> str:
        """Default: pass-through."""
        return sql

    def requires_block_delimiter_wrapping(self, object_type_name: str) -> bool:
        """Predicate for the ``$$``-flavoured MySQL DELIMITER helper.

        Distinct from :meth:`requires_dialect_specific_wrapping`: that
        hook governs CREATE-statement wrapping inside ``generate_ddl``
        (uses ``//`` markers, narrower object set). This hook governs
        the broader ``$$`` helper (``_requires_mysql_delimiter`` /
        ``_wrap_mysql_delimiter_block``) which historically covers
        procedures, functions, triggers and events.
        """
        return False

    def preserves_object_definition(self, object_type_name: str) -> bool:
        """Default: object definition may be re-rendered by the generator."""
        return False

    # ------------------------------------------------------------------
    # View comparison hooks (story 26-6 Wave A).
    # ------------------------------------------------------------------

    #: MySQL/MariaDB ``ALGORITHM = MERGE | TEMPTABLE | UNDEFINED`` on views.
    view_supports_algorithm: bool = False

    #: Oracle ``CREATE FORCE VIEW`` / ``CREATE OR REPLACE FORCE VIEW``.
    view_supports_force_noforce: bool = False

    #: PostgreSQL ``UNLOGGED`` materialized views and view-level
    #: ``security_definer`` / ``security_invoker`` attributes (used during
    #: comparison to decide whether to diff these attributes).
    view_supports_unlogged_and_security: bool = False

    # ------------------------------------------------------------------
    # Trigger comparison hooks (story 26-6 Wave A).
    # ------------------------------------------------------------------

    #: PostgreSQL ``CREATE CONSTRAINT TRIGGER`` (deferred row trigger).
    supports_constraint_triggers: bool = False

    # ------------------------------------------------------------------
    # Index comment hooks (story 26-6 Wave A).
    # ------------------------------------------------------------------

    #: SQL template for ``COMMENT ON INDEX``. Empty = dialect does not
    #: support index-level comments. Placeholders: ``{schema_prefix}``,
    #: ``{idx_name}``, ``{escaped_comment}``.
    index_comment_template: str = ""

    # ------------------------------------------------------------------
    # Type normalisation hooks (story 26-8 Wave A).
    # ------------------------------------------------------------------

    def type_equivalents(self) -> "dict[str, str]":
        """Return per-dialect type-alias → canonical-form mapping.

        Called by ``DataTypeNormalizer._build_type_equivalents()`` to
        get the dialect-specific synonym table (e.g. ``{"INT4": "INTEGER", ...}``).
        Default: empty dict (no aliases beyond the cross-dialect set).
        """
        return {}

    def type_preferences(self) -> "dict[str, str]":
        """Return per-dialect canonical → preferred-form mapping.

        Called by ``TypeMapper.get_dialect_preferred_type()`` to resolve
        the preferred name for a canonical type in this dialect
        (e.g. Oracle prefers ``NUMBER`` for ``INTEGER``).
        Default: empty dict (use canonical form as-is).
        """
        return {}

    # ------------------------------------------------------------------
    # Procedure/function comparison hooks (story 26-6 Wave A).
    # ------------------------------------------------------------------

    #: Oracle stores full procedure DDL in the ``definition`` field rather
    #: than ``body``; comparator should prefer ``definition`` when ``body``
    #: is empty.
    proc_uses_definition_field: bool = False

    #: MySQL cannot reliably introspect procedure parameters/body when empty
    #: (driver limitation). When True, comparator skips parameter and body
    #: diffs if the actual value is empty.
    proc_skip_empty_comparison: bool = False

    # ------------------------------------------------------------------
    # Table comparison hooks (story 26-6 Wave A).
    # ------------------------------------------------------------------

    #: Column DEFAULT values may contain ``ON UPDATE CURRENT_TIMESTAMP``
    #: (MySQL/MariaDB only). When True, the comparator strips that clause
    #: before comparing defaults so dialect-specific syntax doesn't generate
    #: false diffs.
    table_column_default_has_on_update: bool = False

    #: Sequence defaults use ``nextval('seq_name')`` syntax (PostgreSQL).
    #: Used by the comparator to detect and normalise sequence-based defaults.
    seq_uses_nextval_syntax: bool = False

    #: When True, introspection may set ``is_computed`` without a reliable
    #: ``computed_expression`` (e.g. PostgreSQL catalog/driver gaps). The table
    #: comparator then suppresses ``(expected_expr, None)`` noise that would not
    #: indicate a real drift vs. migration SQL.
    computed_column_introspection_incomplete: bool = False

    #: Whether the dialect supports both ``VIRTUAL`` and ``STORED`` computed
    #: columns. PostgreSQL only supports ``STORED``; the validator warns when
    #: the source declares a ``VIRTUAL`` column for a PG target.
    supports_virtual_computed_columns: bool = True

    #: DB2 ``COMPRESS YES/NO`` table clause.
    table_supports_compress: bool = False

    # ------------------------------------------------------------------
    # Migration engine transaction semantics (story 26-9 Wave C).
    # ------------------------------------------------------------------

    #: Dialect commits DDL during ``clean_schema`` (MySQL/DB2) — the
    #: caller must NOT issue ``rollback()`` after, since clean_schema
    #: already committed.
    clean_schema_auto_commits: bool = False

    #: Dialect needs an explicit ``connection.commit()`` after DDL
    #: completes successfully. Oracle and DB2 require this even when
    #: autoCommit is False.
    requires_explicit_commit_after_ddl: bool = False

    #: Dialect leaves implicit transactions open after read-only
    #: introspection (DB2 blocks subsequent queries until uncommitted
    #: transactions are resolved; MySQL InnoDB consistent-snapshot mode
    #: locks the snapshot until commit/rollback). The snapshot service
    #: rolls back after introspection for these dialects to free the
    #: connection.
    requires_rollback_after_introspection: bool = False

    def build_snapshot_table_ddl(
        self,
        qualified_table: str,
        snapshot_id_size: int,
        checksum_size: int,
    ) -> str:
        """Render the ``CREATE TABLE`` SQL for ``dblift_schema_snapshots``.

        The default produces the lowercase-identifier / ``VARCHAR`` /
        ``TEXT`` shape used by PostgreSQL, SQLite, and other dialects
        without a wider text type. Plugins override for Oracle
        (``VARCHAR2`` / ``CLOB`` / uppercase), SQL Server
        (``NVARCHAR`` / ``NVARCHAR(MAX)``), MySQL family
        (``LONGTEXT``), and DB2 (uppercase columns + explicit
        ``NOT NULL PRIMARY KEY``).
        """
        return (
            f"CREATE TABLE {qualified_table} ("
            f"snapshot_id VARCHAR({snapshot_id_size}) PRIMARY KEY, "
            f"captured_at VARCHAR({snapshot_id_size}) NOT NULL, "
            f"checksum VARCHAR({checksum_size}) NOT NULL, "
            f"model_data TEXT NOT NULL)"
        )

    # Whether the provider-compat snapshot DDL is self-guarding
    # (CREATE ... IF NOT EXISTS), letting the manager skip its pre-existence
    # check. Default False (the manager runs its normal existence short-circuit).
    provider_compat_snapshot_skips_existence_check: bool = False

    def build_provider_compat_snapshot_ddl(
        self, qualified_table: str, snapshot_id_size: int, checksum_size: int
    ) -> "Optional[str]":
        """Legacy provider-owned snapshot DDL for native providers that predate
        plugin-owned snapshot tables. Default None (no provider-compat DDL)."""
        return None

    def is_snapshot_table_already_exists_error(self, error_message: str) -> bool:
        """Whether ``error_message`` indicates the snapshot table already exists.

        Returning ``True`` lets ``BaseSnapshotManager`` swallow the
        exception (idempotent create). The default is ``False`` —
        ``CREATE TABLE IF NOT EXISTS`` covers most dialects so a real
        failure should propagate. Oracle overrides because it has no
        ``IF NOT EXISTS`` syntax and instead raises ORA-00955 (with
        locale-translated message text) when the table already exists.
        """
        return False

    # --- Data sets / Lane B table DDL (per spec: reuse snapshot codec pattern for change_set) ---

    #: Column type for the free-text ledger columns (``summary``/``note``).
    #: ``TEXT`` works on PG/MySQL/SQLite; Oracle/DB2 have no ``TEXT`` type and
    #: SQL Server prefers ``VARCHAR(MAX)``. Plugins override.
    data_history_text_type: str = "TEXT"
    #: Column type for the change-set payload (base64/gz row images, can be
    #: large). ``TEXT`` on PG/SQLite; large-object types elsewhere.
    data_change_set_blob_type: str = "TEXT"
    #: DDL for the ``installed_on`` timestamp column. SQL Server's ``TIMESTAMP``
    #: is a rowversion that rejects defaults (uses ``DATETIME2``); Oracle/DB2 use
    #: their own special registers. Plugins override.
    data_timestamp_column_ddl: str = "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"

    def build_data_history_table_ddl(
        self,
        qualified_table: str,
        id_size: int = 100,
        checksum_size: int = 128,
    ) -> str:
        """Render the ``CREATE TABLE`` SQL for a per-dataset data history ledger.

        Used by data sets (Lane B) to track applied corrections.
        """
        return (
            f"CREATE TABLE {qualified_table} ("
            f"id VARCHAR({id_size}) PRIMARY KEY, "
            f"dataset VARCHAR(100), "
            f"sql_checksum VARCHAR({checksum_size}), "
            f"installed_by VARCHAR(100), "
            f"installed_on {self.data_timestamp_column_ddl}, "
            f"status VARCHAR(20), "
            f"plan_fingerprint VARCHAR(128), "
            f"summary {self.data_history_text_type}, "
            f"vcs_ref VARCHAR(200), "
            f"note {self.data_history_text_type}"
            ")"
        )

    def build_data_change_set_table_ddl(
        self,
        qualified_table: str,
        history_id_size: int = 100,
        checksum_size: int = 128,
    ) -> str:
        """Render the ``CREATE TABLE`` SQL for ``dblift_data_change_set``.

        Stores before/after row images (b64/gz) using the same codec as snapshots.
        The ``(dataset, history_id)`` primary key enforces exactly one change-set
        row per applied correction (the table is shared across datasets, so the
        key is composite), making the apply write idempotent and guarding against
        duplicate change records.
        """
        return (
            f"CREATE TABLE {qualified_table} ("
            f"dataset VARCHAR(100) NOT NULL, "
            f"history_id VARCHAR({history_id_size}) NOT NULL, "
            f"checksum VARCHAR({checksum_size}), "
            f"model_data {self.data_change_set_blob_type} NOT NULL, "
            f"PRIMARY KEY (dataset, history_id)"
            ")"
        )

    def build_data_audit_table_ddl(
        self,
        qualified_table: str,
        history_id_size: int = 100,
        checksum_size: int = 128,
    ) -> str:
        """Render the ``CREATE TABLE`` SQL for the append-only audit log.

        An immutable, hash-chained record of apply/undo events (shared across
        data sets, chained per data set via ``seq``/``prev_hash``/``row_hash``)
        that makes ledger tampering — a deleted, reordered or edited event —
        detectable. The ``(dataset, seq)`` primary key gives the per-dataset
        ordering the chain is verified against.
        """
        return (
            f"CREATE TABLE {qualified_table} ("
            f"dataset VARCHAR(100) NOT NULL, "
            f"seq INTEGER NOT NULL, "
            f"history_id VARCHAR({history_id_size}) NOT NULL, "
            f"event VARCHAR(20) NOT NULL, "
            f"sql_checksum VARCHAR({checksum_size}), "
            f"installed_by VARCHAR(100), "
            f"recorded_on {self.data_timestamp_column_ddl}, "
            f"prev_hash VARCHAR(64) NOT NULL, "
            f"row_hash VARCHAR(64) NOT NULL, "
            f"PRIMARY KEY (dataset, seq)"
            ")"
        )

    def is_data_history_table_already_exists_error(self, error_message: str) -> bool:
        """Whether the error indicates the data history table already exists.

        Allows idempotent CREATE TABLE calls (mirrors snapshot handling).
        """
        return False

    def is_data_change_set_table_already_exists_error(self, error_message: str) -> bool:
        """Whether the error indicates the data change-set table already exists."""
        return False

    #: Dialect supports direct session autocommit control reliably. MySQL,
    #: DB2 and Oracle behave inconsistently; PostgreSQL and SQL Server support
    #: it cleanly.
    supports_session_autocommit: bool = True

    #: Dialect raises an error when ``Connection.commit()`` is called while
    #: ``autoCommit`` is True. Oracle throws ORA-17273; most drivers tolerate
    #: redundant commits silently. Used by the round-trip tester
    #: to decide whether to skip an explicit commit when autoCommit is on.
    commit_with_autocommit_raises: bool = False

    #: Some dialects require ``autoCommit=False`` for DDL like ``CREATE USER``
    #: (Oracle) — issuing DDL with autoCommit on can fail or silently
    #: not persist. The round-trip tester checks this before creating
    #: the test schema and flips autoCommit if needed.
    ddl_requires_autocommit_off: bool = False

    #: Round-trip-tester schema-creation policy. When True, a failure to
    #: create the test schema is fatal (Oracle: CREATE USER cannot be
    #: silently retried). When False, the round-trip tester logs a
    #: warning and continues because the schema might already exist
    #: (Postgres / MySQL / SQL Server CREATE SCHEMA IF NOT EXISTS).
    strict_schema_creation_errors: bool = False

    #: Whether unquoted identifiers are stored upper-cased in the data
    #: dictionary. True for Oracle (``USER_TABLES.TABLE_NAME``) and DB2
    #: (``SYSCAT.TABLES.TABNAME``); False for case-sensitive (PostgreSQL)
    #: or case-folding-to-lower (MySQL default) dialects. The round-trip
    #: tester uses this to know whether to upper-case an unquoted table
    #: name before formatting a DROP statement.
    unquoted_identifiers_uppercase_in_dictionary: bool = False

    #: Dialect benefits from retry-drop-and-create when a CREATE TABLE
    #: fails (Oracle/DB2 quirk where in-progress objects can interfere).
    retry_drop_create_on_error: bool = False

    def render_round_trip_drop_table_sql(self, target: str) -> str:
        """SQL to drop a table during round-trip-test cleanup.

        ``target`` is the already-formatted ``schema.table`` (or
        ``"schema"."table"``) identifier. The default rendering uses
        ``DROP TABLE IF EXISTS`` which works for PostgreSQL / MySQL /
        SQLite / SQL Server (with `quote_open` already applied at the
        call site).

        Oracle overrides to wrap in a PL/SQL ``BEGIN ... EXCEPTION``
        block (no ``IF EXISTS`` support, ``CASCADE CONSTRAINTS`` to
        handle FKs). DB2 overrides to drop the ``IF EXISTS`` clause
        (older DB2 versions reject it).

        Used by ``RoundTripTester._build_drop_sql`` /
        ``_retry_drop_and_create``.
        """
        return f"DROP TABLE IF EXISTS {target}"

    def replace_round_trip_schema_in_sql(
        self, sql: str, source_schema: str, target_schema: str
    ) -> str:
        """Rewrite ``source_schema`` references in CREATE-statement ``sql``.

        Used by ``RoundTripTester._replace_schema_in_sql`` to retarget
        generated SQL at the test schema before execution. The default
        implementation covers PostgreSQL / MySQL / SQLite — namely:

        * Quoted form ``"<source>"`` → ``"<target>"``.
        * Bare unquoted form ``<source>.`` / ``<source>`` → ``<target>``
          (no quote-wrap of the target).

        Vendors with dialect-specific identifier quoting or REFERENCES
        rewriting (Oracle, DB2, SQL Server) override to add their own
        rules on top of the generic forms.
        """
        import re as _re

        # Quoted form: "source".x → "target".x  /  "source" → "target".
        quoted_pattern = _re.escape(f'"{source_schema}"')
        sql = _re.sub(quoted_pattern, f'"{target_schema}"', sql, flags=_re.IGNORECASE)

        # Unquoted form (no quote-wrap of target).
        unquoted_pattern = _re.escape(source_schema)
        sql = _re.sub(
            rf"\b{unquoted_pattern}\.",
            f"{target_schema}.",
            sql,
            flags=_re.IGNORECASE,
        )
        sql = _re.sub(
            rf"\b{unquoted_pattern}\b",
            target_schema,
            sql,
            flags=_re.IGNORECASE,
        )
        return sql

    def build_retry_drop_strategies(
        self,
        query_executor: Any,
        connection: Any,
        schema_clean: str,
        table_clean: str,
    ) -> "list[str]":
        """Build the list of DROP-target identifiers to try in retry order.

        Used by ``RoundTripTester._retry_drop_and_create`` when a CREATE
        TABLE fails on Oracle/DB2 because the table is "already there"
        but the original DROP couldn't find it (case-folding, recycle
        bin, identifier-quoting quirks). The default returns the obvious
        two forms (quoted then unquoted) — adequate for PostgreSQL /
        MySQL / SqlServer / SQLite, which never reach this code path
        thanks to ``retry_drop_create_on_error = False``.

        Oracle overrides to look up the *actual* owner / table_name in
        ``ALL_TABLES`` (skipping ``BIN$`` recycle-bin entries) and
        prepend that exact form so the second DROP attempt targets the
        right identifier.

        DB2 overrides to look up the actual ``TABSCHEMA`` / ``TABNAME``
        in ``SYSCAT.TABLES`` and prepend that form.

        Args:
            query_executor: Vendor query executor with ``execute_query``.
            connection: Active connection on the test provider.
            schema_clean: Schema name without surrounding quotes.
            table_clean: Table name without surrounding quotes.

        Returns:
            Ordered list of DROP-target identifiers (typically 1-3
            entries). Empty list disables the retry.
        """
        return [
            f'"{schema_clean}"."{table_clean}"',
            f"{schema_clean}.{table_clean}",
        ]

    #: SQL Server memory-optimised tables (HEKATON).
    table_supports_memory_optimized: bool = False

    #: SQL Server system-versioned temporal tables.
    table_supports_system_versioned: bool = False

    def render_system_versioning_alter(
        self,
        formatted_table: str,
        enable: bool,
        history_formatted: Optional[str] = None,
        formatted_period_start: Optional[str] = None,
        formatted_period_end: Optional[str] = None,
    ) -> Optional[str]:
        """Return the dialect-specific ALTER TABLE text to toggle system versioning.

        Returns ``None`` when the dialect has no system-versioning syntax — the
        caller should then skip emission. SQL Server overrides to emit its T-SQL
        ``SET (SYSTEM_VERSIONING = ON|OFF …)`` shape. All identifier arguments
        arrive pre-formatted (quote rules already applied) so the hook only
        composes the surrounding SQL.
        """
        return None

    def introspector_class(self) -> "Optional[Type[Any]]":
        """Return the dialect-specific introspector class, or None.

        None means IntrospectorFactory falls back to SchemaIntrospector.
        Plugins override with a lazy import to avoid circular imports at
        module-load time.
        """
        return None

    def vendor_queries_class(self) -> "Optional[Type[Any]]":
        """Return the dialect-specific VendorMetadataQueries class, or None.

        ``None`` means the plugin doesn't ship its own catalog-query
        bundle and :class:`VendorQueriesFactory.create` returns ``None``
        for the dialect. Plugins override with a lazy import to keep
        the queries module out of the import graph until the factory
        actually needs it. Mirrors :meth:`introspector_class`.
        """
        return None

    #: SQL patterns whose matched statements cannot run inside a transaction.
    #: Each entry: ``(regex_pattern: str, reason: str)``. Checked in order by
    #: ``classify_execution_statement()``; first match wins.
    #: Default: empty — no dialect-specific non-transactional statements.
    non_transactional_sql_patterns: "tuple[tuple[str, str], ...]" = ()

    def existence_check_sql(self, table_name: str) -> str:
        """Return SQL to test whether *table_name* contains any rows.

        Returns a single ``has_data`` column (1 if rows exist, 0 otherwise).
        Default uses ``LIMIT 1``; Oracle overrides with ``ROWNUM``,
        SQL Server with ``TOP 1``.
        """
        return (
            f"SELECT CASE WHEN EXISTS (SELECT 1 FROM {table_name} LIMIT 1)"
            f" THEN 1 ELSE 0 END as has_data"
        )

    def fk_reference_query(
        self, schema: str, table: str, col: str
    ) -> "tuple[Optional[str], list[Any]]":
        """Return ``(sql, params)`` to find FK constraints referencing *col*.

        Returns ``(None, [])`` when the dialect has no implementation.
        SQL is parameterized; params order matches the placeholders.
        Params are produced by :meth:`fk_reference_bind_params` (already
        overridden by Oracle to pass schema twice).
        """
        return (None, [])

    def index_reference_query(
        self, schema: str, table: str, col: str
    ) -> "tuple[Optional[str], list[Any]]":
        """Return ``(sql, params)`` to find indexes that include *col*.

        Returns ``(None, [])`` when the dialect has no implementation.
        """
        return (None, [])

    # ------------------------------------------------------------------
    # Provider display / credential hooks (story 26-10 Wave B).
    # ------------------------------------------------------------------

    #: Default driver display string for ``--info`` output when live
    #: driver metadata is unavailable. Empty string = leave field as None.
    #: Each plugin may set a user-facing native driver name.
    native_driver_display: str = ""

    #: True when this dialect requires username + password credentials.
    #: SQLite and CosmosDB do not use traditional user/password auth.
    requires_credentials: bool = True

    #: True when a file path (``database`` / ``path`` config key) is
    #: sufficient to connect without a database URL. SQLite only.
    url_optional_when_file_path_given: bool = False

    #: Names of ``DatabaseConfig`` attributes that, if non-empty, satisfy the
    #: "is there enough information to connect?" check in
    #: :meth:`db.provider_registry.ProviderRegistry.validate_database_configuration`.
    #: Default is ``("url",)``. Plugins override to add their
    #: alternate identifiers — SQLite accepts ``url`` / ``path`` / ``database``;
    #: CosmosDB accepts ``url`` / ``account_endpoint``.
    connection_identifier_attrs: "tuple[str, ...]" = ("url",)

    #: Error message hint used by
    #: :meth:`db.provider_registry.ProviderRegistry.validate_database_configuration`
    #: when no connection identifier is set. Defaults to the generic database URL
    #: hint; dialects can override to name their preferred identifier.
    missing_connection_identifier_hint: str = (
        "Database URL not specified (use --db-url or set it in the config file)"
    )

    def has_connection_identifier(self, database_config: Any) -> bool:
        """Return whether *database_config* has enough fields to connect."""
        return any(
            str(
                (
                    database_config.get(attr)
                    if isinstance(database_config, dict)
                    else getattr(database_config, attr, None)
                )
                or ""
            ).strip()
            for attr in self.connection_identifier_attrs
        )


# Static guarantee: ``BaseQuirks`` satisfies the aggregate protocol.
# A failure here means a hook was added to a sub-protocol without a
# default body in ``BaseQuirks`` — fix by adding the default.
def _assert_base_satisfies_protocol() -> None:
    instance: DialectQuirks = BaseQuirks("placeholder")  # noqa: F841


__all__ = ["BaseQuirks"]
