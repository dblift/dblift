"""Default :class:`DialectQuirks` implementation.

Concrete plugins extend :class:`BaseQuirks` and override only the
hooks whose behaviour differs from the default. Hooks live in the
sub-protocols declared in ``core/dialect_boundary.py``; this class
provides their default bodies.
"""

from __future__ import annotations

import re
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    Optional,
    Sequence,
    Tuple,
    Type,
)

from dblift.core.dialect_boundary import DialectQuirks
from dblift.db.dml_analysis import (
    DEFAULT_QUOTE_PAIRS,
    DEFAULT_UPSERT_MARKER_PAIRS,
    DEFAULT_UPSERT_SET_MARKERS,
    DmlMutation,
    analyze_dml,
    is_full_table_dml,
    updates_restore_key,
)
from dblift.db.feature_gate import FeatureGate

if TYPE_CHECKING:
    from dblift.db.generator_protocol import AlterGeneratorProtocol, SqlGeneratorProtocol


class BaseQuirks:
    """Default implementation of :class:`DialectQuirks`.

    Subclasses (one per ``db/plugins/<X>/quirks.py``) inherit and
    override the hooks they need. The dialect identifier is mandatory;
    everything else is optional and gains a safe default.
    """

    dialect_name: str = ""

    #: Version/edition feature gates, keyed by feature name (the shared
    #: vocabulary lives in ``dblift.core.sql_model.feature_gates.KNOWN_FEATURES``).
    #: Resolved by ``dblift.core.sql_model.feature_gates.supports_feature``. Read
    #: as a plain class attribute: a subclass redeclaring this dict
    #: replaces it wholesale (no MRO merging) — an inheriting dialect such
    #: as MariaDB must restate every gate it wants. Base default is empty
    #: ("core doesn't know" for every feature).
    feature_gates: ClassVar[Dict[str, FeatureGate]] = {}

    # ------------------------------------------------------------------
    # Capability matrix.
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
    #: Same purpose as ``sqlglot_unsupported_sql_patterns``, but each entry
    #: is a regex matched against the upper-cased SQL text instead of a
    #: fixed literal phrase — for an unsupported *shape* that spans a
    #: variable identifier a literal substring can't express (e.g. "DROP
    #: INDEX ... ON <schema>.<table>", where an arbitrary index name sits
    #: between the two fixed keywords). When *any* pattern matches,
    #: ``HybridParser`` falls back to regex-only, the same as above.
    sqlglot_unsupported_sql_regex_patterns: "tuple[str, ...]" = ()

    # ------------------------------------------------------------------
    # DML undo-safety scanning (data corrections). The scanning mechanics
    # live dialect-free in ``dblift.db.dml_analysis``; these attributes carry the
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
        """Return True if *sql_content* is valid DDL that sqlglot cannot parse
        without raising, so a caller validating SQL can skip a
        false-positive syntax error. Plugins override for dialect-specific
        patterns (e.g. PostgreSQL ``DROP TRIGGER … ON table``, which sqlglot
        rejects only when the table is schema-qualified — see the override
        for exactly which forms that covers)."""
        return False

    def preprocess_sql_for_sqlglot(self, sql_content: str) -> str:
        """Transform SQL before passing it to sqlglot. Default: pass-through.
        Plugins override to normalize dialect-specific syntax that sqlglot
        can't handle natively."""
        return sql_content

    def derive_schema_name(self, database_config: Any) -> "Optional[str]":
        """Return a schema name derived from dialect defaults, or ``None``.

        Plugins override this when their effective schema comes from a
        non-``schema`` config field, such as MySQL's database/catalog or
        Oracle's current user. The base implementation covers dialects with
        a plain default schema name, such as PostgreSQL and SQLite.
        """
        return self.default_schema_name

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
    #: deliberately left untouched here to preserve historical behaviour.
    quote_qualified_folds_to_uppercase: bool = False
    #: Single-row SELECT statement used as a transaction-liveness
    #: probe (e.g. connection pre-flight). DB2 rejects bare ``SELECT 1``;
    #: Oracle requires ``FROM DUAL``.
    connection_probe_sql: str = "SELECT 1"

    #: Default schema name when the user supplies none. ``None`` means
    #: the dialect has no default — the framework returns ``""``.
    #: PostgreSQL=``"public"``, CosmosDB=``"default"``, SQLite=``"main"``.
    #: SQL Server's "dbo" is NOT set here — it's a parser hint only
    #: (``parser_default_schema``), never substituted for a missing schema.
    default_schema_name: Optional[str] = None
    #: Schema name the parser assigns to objects with no explicit schema.
    #: Falls back to ``default_schema_name`` when ``None``.
    #: SQL Server sets ``"dbo"`` here without setting ``default_schema_name``
    #: so a schema-less object keeps its empty schema when SQL is generated
    #: from the model, instead of being normalized to ``"dbo"``.
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
    #: This dialect is the ANSI/generic rendering reference when a model
    #: carries no dialect of its own (``dialect is None``). The single
    #: plugin that sets this True (PostgreSQL) is resolved via
    #: :meth:`dblift.db.provider_registry.ProviderRegistry.reference_dialect_name`,
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
    #: ``.sql`` migration files can be executed against this dialect.
    #: Document stores (Cosmos DB, and future NoSQL plugins) have no SQL
    #: DDL and drive their schema through the vendor SDK, so they run
    #: Python migrations only and set this False; the executor factory
    #: then rejects SQL migrations with ``DBLIFT-NOSQL-001`` instead of
    #: handing them to a translator. Kept separate from :attr:`is_nosql`
    #: so a future NoSQL dialect with a genuine SQL surface can opt back in.
    supports_sql_migrations: bool = True
    #: Native SQLAlchemy URL query parameter names that populate
    #: ``database.schema`` during config hydration. Plugins can add aliases
    #: without teaching ``config/`` about dialect-specific spellings.
    native_url_schema_params: Tuple[str, ...] = ("currentSchema",)
    #: Placeholder URL used by offline SQL lint when no real database
    #: connection exists. The lint-only path
    #: never opens a connection — but ``DbliftConfig.validate_complete_data``
    #: still requires a syntactically-valid URL of the right shape.
    #: ``None`` means the dialect can't be linted offline.
    lint_placeholder_url: Optional[str] = None

    # ------------------------------------------------------------------
    # Procedure / function DDL hooks.
    # Declare procedure/function syntax and parameter formatting. Each
    # plugin overrides the deltas; defaults match the common ANSI shape.
    # ------------------------------------------------------------------

    #: Keyword for an INOUT parameter. SQL Server uses ``OUTPUT``;
    #: others use ``INOUT``.
    proc_param_inout_keyword: str = "INOUT"
    #: Procedure parameters accept ``= default``. DB2 does not.
    proc_param_supports_default: bool = True

    # ------------------------------------------------------------------
    # Index DDL hooks.
    # Declare CREATE INDEX options and table-qualified/standalone DROP forms.
    # ------------------------------------------------------------------

    #: Index types that do *not* accept ASC/DESC sort directions
    #: (PostgreSQL: GIN/GIST/BRIN/HASH/SPGIST). Names are uppercase.
    index_no_sort_types: "frozenset[str]" = frozenset()
    #: ``DROP INDEX idx ON tbl`` shape — index name is bound to the
    #: table (SQL Server, MySQL, MariaDB).
    index_drop_includes_table: bool = False
    #: ``DROP INDEX IF EXISTS`` is supported in the
    #: index-bound-to-table shape (SQL Server: yes; MySQL: no).
    index_drop_table_form_supports_if_exists: bool = True
    #: ``DROP INDEX IF EXISTS`` is supported in the standalone shape
    #: (PostgreSQL, SQLite: yes; Oracle, DB2: no).
    index_drop_standalone_supports_if_exists: bool = True
    #: ``import-flyway`` reads the *source* Flyway table by its exact name
    #: rather than through ``get_applied_migrations`` (which folds the name
    #: to the dialect's catalogue case). True only for dialects whose
    #: history-name normalisation would otherwise miss a verbatim-cased
    #: Flyway table — Oracle and DB2, where ``get_applied_migrations``
    #: uppercases but Flyway creates a quoted lowercase table.
    flyway_source_table_case_sensitive: bool = False

    # ------------------------------------------------------------------
    # Trigger DDL hooks.
    # Drive ``Trigger._generate_basic_create_statement`` and
    # ``Trigger._format_body``.
    # ------------------------------------------------------------------

    #: ``CREATE DEFINER = user@host TRIGGER`` is valid (MySQL/MariaDB).
    trigger_supports_definer_clause: bool = False
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

    # ------------------------------------------------------------------
    # Misc DDL flags.
    # ------------------------------------------------------------------

    #: Event scheduler supports MySQL-style ``STARTS '...'`` /
    #: ``ENDS '...'`` / ``AT '...'`` timestamp literal quoting.
    #: Only MySQL/MariaDB have CREATE EVENT.
    event_supports_mysql_schedule: bool = False
    #: ``CREATE TABLE`` references ``ON [PRIMARY]`` / ``TEXTIMAGE_ON``
    #: (SQL Server filegroup syntax, used in cross-dialect comparisons).
    table_uses_filegroup_syntax: bool = False
    #: Oracle SQL*Plus preprocessing (DEFINE substitution, WHENEVER
    #: SQLERROR filtering). Only Oracle.
    supports_sqlplus_preprocessing: bool = False

    # ------------------------------------------------------------------
    # Table DDL generation hooks.
    # Declare table syntax choices for DDL generator implementations.
    # ------------------------------------------------------------------

    #: Oracle storage parameters (PCTFREE, PCTUSED, INITIAL, NEXT).
    table_supports_storage_params: bool = False
    #: MySQL/MariaDB ``ENGINE=`` storage-engine clause (and the sibling
    #: ROW_FORMAT / table COLLATE / AUTO_INCREMENT / CREATE_OPTIONS table
    #: options). Identifies the canonical plugin that owns the ``mysql``
    #: ``dialect_options`` namespace so framework code resolves it from the
    #: registry instead of a hardcoded dialect literal (ADR-26 E).
    table_uses_storage_engine_clause: bool = False
    #: PostgreSQL ``INHERITS (parent1, parent2)`` clause.
    table_supports_inherits: bool = False

    def __init__(self, dialect_name: str = "") -> None:
        """Initialize the quirks instance with an optional ``dialect_name``.

        Empty ``dialect_name`` is allowed and signals "no dialect context"
        — the framework calls into ``BaseQuirks()`` from paths where the
        dialect is unknown.
        All hooks return their generic defaults in that case. (PR #241 Bugbot.)
        """
        self.dialect_name = dialect_name

    def parse_server_version(self, raw: Optional[str]) -> Optional[object]:
        """Vendor-specific parse of a captured server version banner.

        Returns a ``DatabaseVersion`` (from the version-detector module —
        typed as ``object`` here because quirks stay decoupled from the
        introspection subsystem) or ``None`` to let the caller fall back
        to the generic dotted-run parse
        (``dblift.core.sql_model.server_info.ServerInfo.from_mapping``). Plugins
        whose banners need vendor handling (e.g. Oracle ``"23ai Free"``
        without a ``Release`` clause) override this. Never raises.
        """
        return None

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
    # DdlQuirks
    # ------------------------------------------------------------------

    def ddl_generator_class(self) -> Optional[Type["SqlGeneratorProtocol"]]:
        """Default: no dialect-specific DDL generator is provided."""
        return None

    def alter_generator_class(self) -> Optional[Type["AlterGeneratorProtocol"]]:
        """Default: no dialect-specific ALTER generator (factory raises)."""
        return None

    def parser_class(self, parser_type: str) -> Optional[type]:
        """Return the parser class for ``parser_type``, or ``None``.

        ``parser_type`` is one of ``"hybrid"``, ``"regex"``, or
        ``"sqlglot"``. Default returns None for every type. Plugins
        override to return their own parser class via lazy import
        (parser modules pull in heavy deps like ``sqlglot``, so we
        avoid importing them at quirks-class load time).

        Parser classes are owned by the plugin via this hook, not via
        static ``PARSER_MAP`` / ``REGEX_PARSER_MAP`` / ``SQLGLOT_PARSER_MAP``
        dicts in ``core/sql_parser/parser_factory.py``.
        """
        return None

    def normalize_view_name(self, name: str) -> str:
        """Normalize a raw catalog view name before downstream lookups.

        Default: return *name* unchanged. DB2 overrides to lowercase
        the name because its catalog rows come back lowercased.
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

        ``view_status`` is an optional capture tracker. Plugins call
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
    #: non-empty tuple also tells the catalog reader that it must
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

    def identity_owned_sequence_names(self, extractor: Any, schema: str) -> "set[str]":
        """Return catalog names of sequences owned by identity columns.

        Default: empty. PostgreSQL overrides via ``pg_depend`` with
        ``deptype = 'i'`` (internal identity dependency). Those sequences
        are created by ``GENERATED … AS IDENTITY`` and must not be
        emitted as standalone ``CREATE SEQUENCE``. Free-standing
        sequences (and SERIAL ``OWNED BY`` sequences, ``deptype = 'a'``)
        are not in this set.
        """
        return set()

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
        per-extractor package-spec cache populated by the
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
            FUNCTION`` (``information_schema.ROUTINES`` exposes
            only the body, not the full CREATE statement) and refreshes
            ``routine.body`` from the ``BEGIN`` offset.
          * Oracle always issues ``DBMS_METADATA.GET_DDL`` — its
            authoritative reconstruction takes precedence over the row
            text — and clears ``routine.body`` (DBMS_METADATA returns
            the full DDL, ``body`` becomes redundant).

        ``status`` is an optional capture tracker;
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

        ``trigger_status`` is an optional capture tracker — when present, plugins call its
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

    # ------------------------------------------------------------------
    # Type normalisation hooks.
    # ------------------------------------------------------------------

    def type_equivalents(self) -> "dict[str, str]":
        """Return per-dialect type-alias → canonical-form mapping.

        Called by ``DataTypeNormalizer._build_type_equivalents()`` to
        get the dialect-specific synonym table (e.g. ``{"INT4": "INTEGER", ...}``).
        Default: empty dict (no aliases beyond the cross-dialect set).

        Read by schema comparison, which installed extension packages provide —
        the per-dialect tables have no in-repository consumer and are not dead.
        See :mod:`dblift.core.normalization`.
        """
        return {}

    # ------------------------------------------------------------------
    # Table comparison hooks.
    # ------------------------------------------------------------------

    #: Whether the dialect supports both ``VIRTUAL`` and ``STORED`` computed
    #: columns. PostgreSQL only supports ``STORED``; the validator warns when
    #: the source declares a ``VIRTUAL`` column for a PG target.
    supports_virtual_computed_columns: bool = True

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

    #: English-locale substrings indicating a concurrent process won the
    #: race to create the migration-history schema/table (see
    #: ``MigrationHistoryManager.create_schema_and_history_table``).
    #: Covers PostgreSQL's aborted-transaction cascade and the generic
    #: "already exists" wording MySQL and PostgreSQL both use. Dialects with
    #: a bare ``CREATE TABLE`` (no ``IF NOT EXISTS``) whose driver message
    #: doesn't contain any of these — DB2, Oracle, SQL Server — override
    #: ``is_schema_history_race_error`` with a stable vendor error-code
    #: check instead, since driver message text is locale-translated.
    schema_history_race_markers: ClassVar[tuple[str, ...]] = (
        "already exists",
        "duplicate key",
        "tuple concurrently updated",
        "transaction is aborted",
        "concurrently",
    )

    def is_schema_history_race_error(self, error_message: str) -> bool:
        """Whether ``error_message`` indicates a concurrent process won the
        race to create the migration-history schema or table.

        Returning ``True`` lets ``MigrationHistoryManager`` retry instead of
        propagating the raw driver error. Default is an English-locale
        substring match against ``schema_history_race_markers``.
        """
        err = (error_message or "").lower()
        return any(marker in err for marker in self.schema_history_race_markers)

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

    def introspector_class(self) -> "Optional[Type[Any]]":
        """Return the dialect-specific introspector class, or None.

        ``None`` means the plugin does not supply a catalog reader.
        Plugins may override with a lazy import.
        """
        return None

    def vendor_queries_class(self) -> "Optional[Type[Any]]":
        """Return the dialect-specific VendorMetadataQueries class, or None.

        ``None`` means the plugin does not supply catalog queries.
        Plugins may override with a lazy import.
        """
        return None

    #: SQL patterns whose matched statements cannot run inside a transaction.
    #: Each entry: ``(regex_pattern: str, reason: str)``. Checked in order by
    #: ``classify_execution_statement()``; first match wins.
    #: Default: empty — no dialect-specific non-transactional statements.
    non_transactional_sql_patterns: "tuple[tuple[str, str], ...]" = ()

    # ------------------------------------------------------------------
    # Provider display / credential hooks.
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
    #: :meth:`dblift.db.provider_registry.ProviderRegistry.validate_database_configuration`.
    #: Default is ``("url",)``. Plugins override to add their
    #: alternate identifiers — SQLite accepts ``url`` / ``path`` / ``database``;
    #: CosmosDB accepts ``url`` / ``account_endpoint``.
    connection_identifier_attrs: "tuple[str, ...]" = ("url",)

    #: Error message hint used by
    #: :meth:`dblift.db.provider_registry.ProviderRegistry.validate_database_configuration`
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
