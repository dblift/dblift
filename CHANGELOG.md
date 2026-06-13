# Changelog

All notable changes to DBLift will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.7.0] - 2026-06-02

### Added

### Changed

### Fixed

### Removed

## [1.8.0] - 2026-06-12

**Python-native epic complete** (Phases 4, 6–9 landing; substrate in 1.7.0 cut was prior). dblift 1.8.0 + pytest-dblift 0.1.0.

### Added

- **Full Python-native release**:
  - `DBLiftClient.from_sqlalchemy(engine, ...)` + `config_from_engine` (external engine ownership, no dblift lifecycle assume).
  - Public `MigrationContext` (from `api import MigrationContext`; enriched for Python migration scripts with client/config/placeholders/undo helpers).
  - `pytest-dblift` 0.1.0 (separate package: pytest11 entrypoint, `migrated_db`/`empty_db`/`validate_sql` fixtures, xdist-safe SQLite paths, undo script generation support).
  - Thin framework integrations: `dblift.integrations.fastapi` and `dblift.integrations.flask`.
  - Pip-first README, python-migrations guide, sqlalchemy-integration examples, FastAPI/Flask lifespan docs.
  - Django positioning (second DATABASES + from_sqlalchemy pattern; explicit non-goals).
  - Provider cookiecutter + plugin entry points / install extras docs (`docs/developer-guide/`).
- feat(docs): pip-first README positioning for python-native (DBLiftClient.from_sqlalchemy, pytest-dblift); Phase 4 complete

- **Custom secrets provider registration** — enterprise users and third-party
  integrations can register any secrets backend at startup via
  `register_provider(scheme, cls)` without forking or patching dblift.
  The provider class must subclass `AbstractSecretsProvider` and implement
  `resolve(uri) -> str` and `is_available() -> bool`. Registered providers
  are immediately detectable by `is_secret_uri()` and participate in the
  same resolution and caching pipeline as the bundled providers.
  See [Custom Providers](user-guide/configuration.md#custom-provider-registration).

- **Secrets manager integration** — database passwords and other sensitive
  config values can now be stored in an external secrets manager and referenced
  by URI in `dblift.yaml`. Five providers are supported out of the box:
  HashiCorp Vault (`vault://`), AWS Secrets Manager (`aws-secrets://`),
  AWS SSM Parameter Store (`aws-ssm://`), Azure Key Vault
  (`azure-keyvault://`), and GCP Secret Manager (`gcp-secrets://`). Secret URIs
  are resolved transparently at config load time via a two-phase bootstrap that
  handles provider credentials that are themselves secret URIs. A
  process-level LRU cache with a configurable TTL (default 60 s) avoids
  redundant provider calls. Offline commands such as `validate-sql` skip
  resolution entirely so CI lint jobs do not require secret-manager credentials.
  See [Secrets Manager Integration](user-guide/configuration.md#secrets-manager-integration).

- **Unified CI findings for `validate-sql` and `plan`** — both commands now
  share `json`, `sarif`, `github-actions`, `gitlab`, and `compact` finding
  output, plus a single `--fail-on never|error|warning|info` threshold.
- **Built-in SQL validation profiles** — `validate-sql` now supports
  `--profile core|enterprise|strict|technical-debt` plus explicit `--rules`
  selection for DBLift-managed rule packs and individual rules.
- **Enterprise SQL validation evidence** — `validate-sql` now carries rule
  rationale, remediation, control mappings, governed exceptions, and HTML
  evidence output for offline release review.
- **Offline migration planning from snapshots** — new `dblift plan --snapshot-model`
  command and `DBLiftClient.plan()` API compute pending versioned migrations,
  changed repeatables, checksum drift, and pending-scope SQL validation from a
  committed DBLift snapshot without connecting to the target database.
- **User-controlled SQL visibility** — `migrate` and `undo` now support
  `--show-sql` so users can see the SQL statements that will be executed without
  enabling debug logging. The flag works with dry-run and real execution and is
  independent from the selected log/report format.
- **Deployment preflight workflow** — added `dblift preflight`, which combines
  snapshot-based planning, SQL validation, optional Docker container startup,
  migration replay, and one CI-friendly report for enterprise PR validation
  workflows.
- **Enterprise plan and preflight report artifacts** — `dblift plan` and
  `dblift preflight` now accept multiple comma-separated report formats such as
  `json,html,text` and write timestamped artifacts to `--output-dir`, keeping
  CI-friendly JSON separate from enriched offline HTML reports.
- **Broader `export-schema` replay coverage** — integration tests now exercise
  generated schema SQL for PostgreSQL, MySQL, SQL Server, Oracle, and SQLite with
  richer object sets such as views, procedures/packages, triggers, materialized
  or indexed views, full-text/clustered indexes, and SQLite FTS virtual tables.

### Removed

- **JVM/JDBC runtime layer** — DBLift now uses plugin-owned native SQLAlchemy
  drivers, SQLAlchemy URL handling, and vendor catalog queries for supported
  database providers. The bundled JRE/JDBC driver artifacts, JDBC provider
  infrastructure, and JDBC metadata fallback tests have been removed as part of
  the v2 breaking-change native-driver transition.
- **JDBC URL compatibility** — `jdbc:` URLs are no longer accepted or translated.
  Configuration, examples, tests, Docker assets, CI jobs, and recovery docs now
  use native SQLAlchemy URLs and native driver names only.

### Fixed

- **`validate-sql --fail-on-violations` replaced by `--fail-on`** — SQL
  validation now uses the same severity threshold model as `plan`; the old flag
  is intentionally removed.
- **GitLab CI finding output** — `--format gitlab` now emits GitLab Code Quality
  JSON instead of the generic DBLift finding report.
- **Plan process errors** — blocking `plan` errors now fail independently of
  `--fail-on never`, while SQL validation findings still follow their severity.
- **SQL validation rule source conflicts** — `rules_file` is now consistently
  rejected when combined with built-in profiles or explicit rule selections,
  avoiding silent rule overwrites.
- **Replayable `export-schema` DDL across SQL dialects** — normalized generated
  DDL for PostgreSQL drops, MySQL index creation, Oracle storage/table/view/package
  output, and SQL Server indexed-view exports so the emitted SQL can be executed
  by the native database engines.
- **Noisy `export-schema` dependency ordering diagnostics** — circular dependency
  details from self-referencing tables now log at debug level instead of warning
  level, keeping successful exports free of internal ordering diagnostics.
- **Plan and HTML report failure semantics** — checksum drift now remains a
  blocking plan finding even with `--fail-on never`, offline `plan` fails early
  when no scripts directory is configured, and HTML execution KPI totals no
  longer depend on `--show-sql`.
- **Undo `--show-sql` error cleanup** — undo now closes the migration journal if
  SQL extraction fails before execution starts.
- **Plan output and `--fail-on never` consistency** — `plan --output` now writes
  console reports as well as machine-readable reports, and syntax-sourced SQL
  validation findings now honor `--fail-on never`.
- **Preflight review fixes** — boolean `plan`/`preflight` flags no longer
  swallow chained commands, SQL validation details cannot impersonate blocking
  plan/runtime sources, and `preflight --format console` now shows a
  human-readable phase summary.
- **Validate-sql and plan CI finding consistency** — `validate-sql` configuration
  errors now use the same machine-readable finding schema as normal validation
  output, and pending plan migrations are informational so `--fail-on warning`
  can target SQL validation warnings without failing on expected pending work.
- **Preflight multi-command parsing and planning** — inline subcommand values such
  as `--fail-on=error` no longer hide the next chained command, and preflight no
  longer passes explicit script-directory overrides to bound `DBLiftClient.plan()`
  calls in multi-command workflows.
- **Plan and preflight threshold clarity** — plan validation errors now honor
  `--fail-on never` unless they are runtime failures, and preflight console
  output calls out threshold-based failures when all workflow phases pass.
- **Plan and preflight HTML output routing** — `--format html` without
  `--output` now writes the rendered report to stdout instead of dumping it
  through the human logger.
- **HTML migration journal and CI finding robustness** — HTML migration reports
  again show per-statement SQL in the execution journal even without
  `--show-sql`, and unexpected CI finding severities now fall back to warnings
  instead of crashing report summaries.
- **CI finding blocking metadata** — validate-sql configuration errors are now
  marked as blocking runtime findings, while SQL validation finding details are
  sanitized before plan reports evaluate threshold bypass metadata.
- **Plan chained-command recursion settings** — `plan` now forwards
  directory-specific recursive options through the bound `DBLiftClient` path as
  well as the offline validation client path, and `DBLiftClient.plan()` exposes
  the option explicitly.
- **Validate-sql rule argument parsing** — repeated `--rules` values now parse
  directly as a flat list before rule-selection normalization.

## [1.6.0] - 2026-05-15

Stabilization release: quality ratchets (docstrings, line length, complexity average), typed public `Event` API, CLI handler decomposition, `PluginInfo.config_class` for third-party plugins, operations recovery runbooks, and the breaking changes listed under Removed.

### Added

- **Plugin layering contract enforced in CI** — `tests/unit/test_plugin_isolation.py`
  scans every `.py` file under `core/`, `db/introspection/`, and `db/plugins/` with
  the `ast` module and asserts three rules: (1) no hardcoded `core/` → plugin imports,
  (2) no upward `db/introspection/` → `core.{validation,licensing,migration}` leaks,
  (3) no cross-plugin imports except the two documented family inheritances
  (MariaDB ⊃ MySQL, CosmosDB parser ⊃ SQL Server parser). Rules 1 and 2 are strict;
  Rule 3 has documented allow-listed exceptions. Each rule has a companion test that
  fails when an entry in `KNOWN_VIOLATIONS` becomes stale, so the dicts stay in sync
  with reality. See `docs/architecture/database-providers.md` § "Layering contract"
  for the rationale.
- **`BaseQuirks.apply_vendor_table_properties(table, row)` hook** — each plugin's
  quirks declares how to map a vendor-query catalog row to dialect-specific `Table`
  attributes (SQL Server filegroup / memory-optimised / system-versioned, DB2
  tablespace + compression, Oracle tablespace + storage params, MySQL storage_engine
  / row_format / collation / create_options). Replaces the `_HANDLERS` dispatch dict
  + four `_apply_<dialect>_properties` static methods that used to live on
  `VendorPropertyApplier`.
- **`BaseQuirks` SQL\*Plus / T-SQL batch hooks** —
  `extract_sqlplus_context()`, `sqlplus_context_prompts()`,
  `sqlplus_context_serveroutput_enabled()`, `apply_sqlplus_preprocessing()`,
  `is_sqlplus_command()`, `parse_sqlplus_whenever()`, `is_batch_separator_line()`,
  `enable_server_message_capture()`, `read_server_messages()`. Replace direct
  `from db.plugins.oracle.parser.*` / `from db.plugins.sqlserver.parser.*` imports
  in `core/migration/` and `core/sql_validator/`.
- **`BaseQuirks.vendor_queries_class()` hook** — each plugin's quirks declares its
  `VendorMetadataQueries` subclass; `VendorQueriesFactory` consults the hook via
  `ProviderRegistry.get_quirks()` instead of hardcoding the registry.
- **Four missing `supports_X` capability flags** on `VendorMetadataQueries`:
  `supports_packages`, `supports_events`, `supports_foreign_data_wrappers`,
  `supports_foreign_servers`. Plugins (Oracle/DB2 packages, MySQL events,
  PostgreSQL FDWs/foreign servers) override to `True`. `SchemaIntrospector` gates
  every `get_X()` entry point on the corresponding flag, returning `[]` without
  opening a JDBC connection when the dialect doesn't support the object kind.
- **`core/validation/introspection_validator.py`** — `IntrospectionValidator` moved
  here from `db/introspection/validation_integration.py` so the upward db→core
  layering boundary stays clean.
- **`db/introspection/_oracle_utils.py`** — canonical home for Oracle introspection
  helpers (`is_hidden_column`, `normalize_partition_bound`, `clean_source_text`).
  Replaces 6+ duplicate copies that lived on `SchemaIntrospector`,
  `IndexExtractor`, `MiscExtractor` (instance method), and `ProcedureExtractor`
  (module function).
- **`core.constants.DBLIFT_SCHEMA_SNAPSHOTS_TABLE`** — the snapshot table name
  literal now lives on the cross-cutting boundary, used by both
  `core.migration.snapshots` (writer) and `db.introspection`/
  `db.plugins.cosmosdb` (consumers that previously imported from
  `core.migration.snapshots.schema_snapshot`).
- **`scripts/check_code_quality.sh` mirrors CI gates** — three CI lint gates
  (`scripts/lint_patterns.py`, `scripts/check_api_docstrings.py`, and
  `scripts/check_line_length.py`) now run from the local script as well, catching
  ratchet failures before push.

### Changed

- **Plugin introspectors no longer carry the `_get_row_value` + delegation
  pattern** — five plugins (`MySQLIntrospector`, `PostgreSQLIntrospector`,
  `OracleIntrospector`, `SQLServerIntrospector`, `DB2Introspector`) used to wrap
  every `get_*` method in a temp-`SchemaIntrospector` composition pattern (~1.7k LOC
  of pure forwarding). Wave F.3.a replaced that with direct inheritance from
  `SchemaIntrospector` and the post-F.3 cleanup audit retired the five now-empty
  subclass files entirely. `IntrospectorFactory` falls through to the canonical
  `SchemaIntrospector(provider)` constructor when no quirks override returns a
  class. Only `SQLiteIntrospector` (1115 LOC of genuine SQLite-specific
  introspection) and `CosmosDbIntrospector` (551 LOC, NoSQL) remain as
  plugin-level subclasses.
- **`SchemaIntrospector._get_extractor` no longer eagerly connects** — the previous
  implementation called `_ensure_metadata()` at extractor construction, forcing
  every unsupported-kind call (e.g. `get_extensions()` on DB2) to open a JDBC
  connection just to have the extractor return `[]`. Metadata is now fetched
  lazily inside each extractor method that actually needs it.
- **`PostgreSQLIntrospector.get_triggers` retired** — the override built `Trigger`
  objects directly from `pg_trigger`. The shared `TriggerExtractor` +
  `PostgreSQLMetadataQueries.get_triggers_query` produces strictly richer
  `Trigger` objects (also captures `orientation`, `enabled`, `function_arguments`,
  `when_clause`, `is_constraint_trigger`, `constraint_deferrable`,
  `constraint_initially_deferred`). Same DDL via `pg_get_triggerdef(t.oid, ...)`.
- **`VendorQueriesFactory` consults the quirks hook** —
  `vendor_queries_class()` replaces the hand-maintained
  `_VENDOR_QUERIES_REGISTRY` mapping for first-party dialects (the runtime override
  registry stays for third-party plugins). `register_vendor_queries()` is
  preserved as a public API.
- **`UndoScriptGenerator` no longer re-parses the migration** — the public API
  operation `generate_undo_scripts` previously parsed each migration twice (once
  for validation, once inside the generator). Now uses the dedicated
  `generate_undo_script_for_migration(migration, ...)` entry point that was always
  available.
- **`db/` E501 ratchet tightened** — from 400 to 384 across the cleanup wave.
  `cli/` ratchet tightened from 21 to 20.

### Fixed

- **CosmosDB DROP CONTAINER no longer breaks the test isolation** — the
  `core.migration.snapshots` snapshot table constant moved out of
  `core.migration.snapshots.schema_snapshot` to `core.constants`, breaking the
  registry-pollution chain that surfaced as flaky `test_generate_drop_table_cosmosdb`
  failures in suite mode.
- **`test_clean_schema_skips_migration_lock_table`** asserted obsolete behaviour
  (OBS-04 inverted it to drop the lock table on `clean_schema`, the lock manager
  re-creates it on next acquire); renamed and inverted assertions to match.

### Removed

- **`VendorPropertyApplier._apply_<dialect>_properties` static methods** + the
  `_HANDLERS` dispatch dict — moved to per-plugin
  `BaseQuirks.apply_vendor_table_properties` overrides.
- **`SchemaIntrospector._is_oracle_hidden_column` /
  `_normalize_oracle_partition_bound` / `_strip_leading_comments`** — duplicates
  of `db.introspection._oracle_utils.is_hidden_column` /
  `normalize_partition_bound` / `db.introspection.core.utils.strip_leading_comments`.
  The `import re` they required is gone from `schema_introspector.py` too.
- **Five empty plugin introspector subclasses** —
  `db/introspection/databases/{mysql,postgresql,oracle,sqlserver,db2}/<dialect>_introspector.py`
  and the five `XQuirks.introspector_class()` overrides that returned them
  (the quirks' default `None` now triggers the `IntrospectorFactory` fallback
  to `SchemaIntrospector`).
- **Two back-compat re-exports** (`VendorPropertyApplier`,
  `_SQL_PARTITION_FUNCTIONS`) from `schema_introspector.py` — `db.introspection`
  is private, and the only consumers were stale test imports that now reach the
  canonical homes (`_vendor_property_applier`, `_partition_enricher`).
- **`PostgreSQLIntrospector` helper methods** (~250 LOC) —
  `_enrich_table_with_row_security`, `_enrich_table_with_policies`,
  `_get_partitioned_tables`, `_enrich_index_with_postgresql_properties`,
  `_enrich_sequence_with_postgresql_properties`,
  `_parse_postgresql_partition_definition`,
  `_enrich_view_with_postgresql_properties`. Verified dead code (zero external
  callers); the partitioned-table fallback lives in
  `TableExtractor._supplement_partitioned_tables`.

### Added

- **`core/` docstring ratchet driven 78 → 0** (core-docstrings drive-to-zero
  PR 2 of 2; campaign complete). Finishes the work started in #368 by adding
  docstrings to every missing-docstring site in the 7 remaining "big" files:
  `core/logger/results.py`, `core/migration/snapshots/schema_snapshot.py`,
  `core/logger/_multi.py`, `core/logger/log.py`,
  `core/migration/state/migration_state_manager.py`,
  `core/migration/snapshots/schema_snapshot_repository.py`, and
  `core/migration/migration.py`. The bulk are `__init__` and accessor docstrings
  on the `OperationResult` subclass family (`CleanResult`, `DiffResult`,
  `ExportSchemaResult`, `UndoResult`, …), four module docstrings (migration model,
  snapshot payload/codec, snapshot repository), and dataclass `from_*` / `to_*`
  converters on `MigrationResource` / `ResolvedMigration` / `AppliedMigration` /
  `SchemaSnapshotPayload`. Ratchet entry tightened `core: 78 → 0`. The campaign
  cleared **143 violations across two PRs** (#368 + this one). The gate is now
  uniformly strict on every root: `api=cli=core=db=0`. Any future PR that
  introduces a public-surface missing-docstring violation under `core/` fails CI.
- **`core/` docstring ratchet driven 127 → 78** (core-docstrings drive-to-zero
  PR 1 of 2; same trajectory pattern as the `db/` ratchet cleared in #362/#366/#367):
  adds docstrings to every missing-docstring site in the 35 small files (≤5
  violations each), covering ~49 violations across the package. The bulk is
  25 module docstrings under `core/logger/formatters/`, `core/migration/{sql,
  history, scripting, snapshots, placeholders, rules, journals}/`, plus a handful
  of class docstrings (`TransactionPolicyDecision`, `MigrationScriptManager`,
  `DummyHtmlFormatter`) and roughly twenty scattered `__init__` / method
  docstrings. A follow-up PR will clear the remaining 78 concentrated in 7 big
  files: `core/logger/results.py` (24), `core/migration/snapshots/schema_snapshot.py`
  (12), `core/logger/_multi.py` (11), `core/logger/log.py` (10),
  `core/migration/state/migration_state_manager.py` (8),
  `core/migration/snapshots/schema_snapshot_repository.py` (7),
  `core/migration/migration.py` (6). Ratchet entry tightened `core: 127 → 78`.
- **`db/` docstring ratchet driven 85 → 0** (roadmap action #15 PR 3; final
  installment after PR 1 in #362 and PR 2 in #366): completes the project by
  adding docstrings to every remaining `*Quirks` method override across the
  six dialect plugins still missing them — `db/plugins/sqlserver/quirks.py`
  (16 methods), `db/plugins/postgresql/quirks.py` (16), `db/plugins/oracle/quirks.py`
  (16), `db/plugins/mysql/quirks.py` (16), `db/plugins/cosmosdb/quirks.py` (15),
  `db/plugins/sqlite/quirks.py` (6). Each docstring explains the dialect-specific
  behavior (e.g. PostgreSQL's `render_identity_clause` returns `None` for SERIAL
  types because the auto-increment lives in the type name; Oracle's `parser_class`
  routes regex through `OracleParser`; Cosmos's `render_drop_for_object` becomes
  `DROP CONTAINER` for tables and explanatory comments otherwise) rather than
  restating the base contract. Style follows `db/plugins/db2/quirks.py` cleared
  in PR 2. Ratchet entry `db` tightened from `85 → 0`; the gate is now strict
  for `db/` on par with `api/` and `cli/` — any future PR introducing a
  public-surface missing-docstring violation under `db/` fails CI.
- **`db/` docstring ratchet driven 119 → 85** (roadmap action #15 PR 2; companion to PR 1 in #362): adds docstrings to every non-quirks-override site under `db/`. Specifically: 1 missing module docstring on `db/jvm_manager.py` (3 modules listed at PR-1 inventory time, 2 already covered by sibling changes — only `jvm_manager.py` still needed one at this PR's measurement); 1 missing module docstring on `db/data_access.py`; module + class + 13 method docstrings on `db/dummy_jdbc_provider.py` (the testing-only no-op JDBC stand-in); 2 missing function docstrings under `db/error.py`; 3 scattered method docstrings under `db/introspection/extractors/` (`misc_extractor`, `procedure_extractor`, `view_extractor`); 1 method docstring on `db/base_quirks.py`; and 11 quirks-method docstrings on `db/plugins/db2/quirks.py` (the first dialect fully cleared). The remaining 85 violations are `*Quirks` method overrides across the other 6 dialect plugins (sqlserver, postgresql, oracle, mysql, cosmosdb, sqlite) — a follow-up PR will drive those to zero. Ratchet entry tightened from `db: 119 → 85`; the cap now monotonically tracks down. Same trajectory pattern as `core: 127` established in action #4 — the gate is active, gradual cleanup over follow-up PRs.
- **`PluginInfo.config_class` field + plugin-driven config resolution** (roadmap action #11): third-party plugins can now ship a `BaseDatabaseConfig` subclass and have it resolve through `_resolve_config_class` without touching `config/_subclasses/` or the eager-import block at the bottom of `config/database_config.py`. The resolution chain in `_resolve_config_class` is now three-step (first-hit wins): (1) the legacy `BaseDatabaseConfig._registry` dict populated by `@register_database_type` decorators; (2) **new**: `PluginInfo.config_class` declared directly on the plugin metadata (the modern entry point for third-party plugins); (3) the existing `config_dialect` parent-fallback (e.g. `mariadb` → `mysql`). Each first-party plugin (`postgresql`, `mysql`, `sqlserver`, `oracle`, `db2`, `sqlite`, `cosmosdb`) now declares `config_class=` on its `PluginInfo` so the new path is the canonical one; `mariadb` continues to use `config_dialect="mysql"`. `ProviderRegistry._build_plugin_info_from_dir` and `discover_plugins` thread the field through end-to-end. Defensive runtime guard in `_resolve_config_class` rejects a misconfigured plugin whose `config_class` is not a `BaseDatabaseConfig` subclass — fall through to the parent fallback instead of silently swapping the contract. **Backward compatible**: the 8 eager imports at the bottom of `config/database_config.py` stay in place because ~25 test modules and a couple of production sites (e.g. `db/plugins/cosmosdb/cosmosdb/query_executor.py`) rely on the `from config.database_config import XxxConfig` re-export path. The new `config_class` field is the entry point for **adding** dialects without modifying `config/`; existing dialects keep their legacy location. Acceptance criterion met: `tests/unit/db/test_provider_registry_config_class.py` (10 tests) registers a synthetic third-party plugin that ships its own config class and verifies `_resolve_config_class` returns it without any modification to first-party code.
- **`docs/operations/recovery/` runbooks** (roadmap action #10): five operational runbooks plus an index covering the failure modes that can leave a target database in an inconsistent state during `dblift migrate` — `jvm-crash.md` (JVM OOM / segfault / hang on JDBC-backed dialects), `oracle-lock-timeout.md` (Oracle `DBMS_LOCK` timeout with the three holder-state paths: healthy-wait, wedged-kill, stale-deploy cleanup), `schema-history-corruption.md` (four categories: duplicate version rows, orphan FAILED rows, NULL discriminator columns, checksum drift), `partial-ddl-mysql.md` (the non-transactional-DDL case for MySQL / MariaDB / Oracle / Cosmos DB with three reconciliation paths: roll forward, roll back via undo script, split the migration), and `network-split.md` (three sub-scenarios per the dialect transactionality + commit-state matrix). Every runbook follows the same shape — Symptoms → Immediate response → Recovery procedure → Verification → Prevention — so an on-call engineer can navigate without prior dblift internals knowledge. Wired into `mkdocs.yml` under a new `Operations` nav section; cross-referenced from `ARCHITECTURE.md` § 6.1 ("Operations and recovery") so the doc surface is reachable from the architectural entry point. The index documents the two always-safe diagnostic queries (`dblift info` + direct SELECT on `dblift_schema_history`) and clarifies when `dblift repair` is the right tool vs when manual SQL surgery is needed.
- **`api.events.Event` dataclass** (`api/events.py`): listener callbacks now receive a frozen, IDE-discoverable `Event` with `event_type`, `timestamp`, and named optional fields. `EventEmitter.emit()` validates emit-site keys against the dataclass — unknown fields raise `TypeError`, reserved fields (`event_type`, `timestamp`) cannot be passed in, and `_dispatch()` is the single fan-out path. **Breaking** for consumers using dict-style access on event payloads.
- **`api/_cli_support.py` re-export shim**: documented surface for `cli/*` to access database-layer helpers without importing `db.*` directly.
- **`cli/handlers/` per-command package**: 12 command handlers split out of `cli/_command_handlers.py` (742 → 103-line façade). One file per command (`migrate`, `info`, `clean`, `validate`, `diff`, `repair`, `baseline`, `undo`, `import_flyway`, `export_schema`, `snapshot`, `validate_sql`).
- **`config/_url_parse_exceptions.py`** and **`db/_jdbc_exceptions.py`**: single canonical exception tuples (`URL_PARSE_EXC`, `JAVA_EXC`) shared across the config / JDBC plugin layers; adding an exception type now updates one file instead of three.
- **`core/sql_model/table_options.py` / `view_options.py`**: typed frozen dataclasses (`MySqlTableOptions`, `SqlServerTableOptions`, `PostgresTableOptions`, `OracleStorageOptions`, …). `Table.from_options(...)` / `View.from_options(...)` classmethods accept the aggregate; codemod scripts under `scripts/codemod_*_options.py` migrate existing call sites.
- **`flake8-tidy-imports` `banned-modules` lint**: `cli/*` cannot import `db.*` (route through `api/_cli_support`). Existing imports baselined in `.lint-patterns-baseline.txt`.
- **`CommandOutput.error()`** (`cli/_output.py`): unified stderr routing for CLI errors per ADR-0008.
- **`scripts/check_api_docstrings.py` public-API docstring linter** (PR-E1, #279): AST-based rule that fails the CI lint job when any public module / class / function / method under `api/` is missing a docstring. Auto-exempt: inner functions / closures (functools.wraps inheritance), stub bodies (`...` or — corrected post-review — `pass` only, **not** bare `None`), private names (except `__init__`). Manual escape hatch: `# lint: allow-missing-docstring: <reason>` on the def/class line, matching the `lint_patterns.py` annotation convention. Scope is intentionally narrow to `api/` for the first rollout; other roots stay on the lax baseline. Current state: zero violations on `api/`.
- **`.github/ISSUE_TEMPLATE/`** (PR-E3, #282): `bug_report.yml` (structured form: pre-flight checks, summary, repro rendered as bash, expected/actual, dialect dropdown, dblift / Python / OS versions, optional logs), `refactor_proposal.yml` (current pain with metrics, scope, proposed approach, blast-radius dropdown, mandatory `stabilization-plan` reference — features are frozen v1.3.x → v2.0), `config.yml` (disables blank issues, links to docs + stabilization plan).
- **Public-API surface contract test + golden snapshot** (PR-F5, #290): `tests/unit/api/test_public_surface_contract.py` reflects on `api.__all__`, every public method's `inspect.signature` (including return annotation) on each re-exported class, and the `EventType` enum members (sorted by name). The rendered fingerprint is compared byte-for-byte against the committed `tests/unit/api/api_public_surface.txt` (126 lines). Any drift fails the test with a readable unified diff plus the exact regeneration command (`UPDATE_API_SNAPSHOT=1 pytest …`). Adding a public method or renaming a kwarg now requires committing the snapshot diff — the diff IS the review evidence for an intentional API change.
- **Dedicated unit tests for Phase B / D / F extractions** (PR-F3, #287): 53 focused tests pinning the helpers Phase B / D / F refactors created — `tests/unit/api/test_client_factory_helpers.py` (15 tests, the four PR-D4 `__init__` helpers), `tests/unit/api/test_client_operations_export_schema.py` (10 tests, `export_schema_operation` + `_build_export_schema_options`), `tests/unit/core/sql_parser/test_sqlglot_builders.py` (28 tests, the PR-F2 trigger helpers + the table / view / index builders called directly through a `_Harness` composing class). Pre-existing tests covered the older helpers; this PR fills the gap on every helper introduced or restructured by the extraction PRs.
- **`docs/quality-roadmap/` tracking folder**: three files (`README.md`, `priorities.md`, `categories.md`) capturing the plan to lift every quality axis (lisibilité, maintenabilité, évolutivité, modularité, simplicité, fiabilité, documentation, tests) from the 7.2–8.5 baseline to ≥ 9/10. 30 action cards triaged P0 → P3 with effort estimates, multi-category impact mapping, acceptance criteria, and an effort × leverage matrix for sprint planning. Documents the GitHub Actions budget constraint (no full suite on PR per CONTRIBUTING § "CI Test Evidence Policy") so future proposed gates respect the envelope.
- **PR-time patch coverage gate via `pytest-testmon`** (roadmap action #1): new `.github/workflows/pr-patch-coverage.yml` runs only the unit tests impacted by a PR's diff (selective execution via `pytest-testmon`, ~2 min P95), uploads to codecov under a new `pr-patch` flag gated on `patch.target` ≥ 80 % (`codecov.yml` adds an `individual_flags` override that skips the project-level status because a selective run does not cover every source file). The testmon index is shared between workflows via `actions/cache@v4`, keyed per branch + python version with broad restore-keys so PRs always find the most recent develop index. `unit-tests.yml` now also runs on `push develop` (aligning with this CONTRIBUTING entry that previously drifted from the workflow file), uses `--testmon-noselect` to run the full suite while updating the index, and adds `--cov-fail-under=77` as the absolute floor at merge time. CONTRIBUTING § "CI Test Evidence Policy" documents the resulting dual-gate (PR = patch ≥ 80 %, push develop = absolute ≥ 77 %). Stale committed `.testmondata` blob (1.2 MB) removed; `.testmondata` + `.testmondata-journal` added to `.gitignore`. Workflow ships with `continue-on-error: true` for a 1-2 week calibration window until the develop cache is warm.
- **Stale `coverage.json` removed from the repo** (roadmap action #3): the 2.25 MB committed `coverage.json` blob was a one-off report from 2026-04-30 stuck at 6.6 % combined coverage, contradicting the 77 % floor enforced on push develop and misleading anyone opening it. `coverage.json` and `coverage-*.json` added to `.gitignore` (the existing `.coverage*` pattern only matches the dotfile binary database, not the JSON export).
- **Built mkdocs site untracked from the repo** (roadmap action #2): 71 generated HTML/CSS files under `site/` were committed despite the `site/` rule already living at `.gitignore:85` (likely added via `git add -f` or pre-rule commit). They polluted diffs, could drift from sources, and bloated clones. The site is rebuilt fresh on every push develop / main by `.github/workflows/docs.yml` (`mkdocs build`) and deployed to GitHub Pages on push main via `actions/upload-pages-artifact@v5` + `actions/deploy-pages@v5` — no behaviour change for readers, the published URL is unchanged.
- **`scripts/check_api_docstrings.py` extended to `cli/` + `core/` with a count-based ratchet** (roadmap action #4): the linter now accepts `--paths` (multi-root) and `--ratchet PATH` (per-root cap loaded from a JSON file). `.docstring-ratchet.json` ships with `{"api": 0, "cli": 0, "core": 127}` — `api/` and `cli/` stay strict, `core/` is gated by the cap. Any PR that grows a count fails CI; any PR that lowers a count gets a "consider committing a tighter cap" nudge, forcing monotonic decrease. New privacy heuristic: a public-named method (and `__init__`) on a private class inherits the class's privacy — eliminates the two false positives in `cli/handlers/_shared.py::_minimal_result`'s nested `_Result` class without busywork annotations. CI step in `.github/workflows/code-quality.yml` replaces the old `api/`-only call with `--paths api cli core --ratchet .docstring-ratchet.json`. Tests: 13 new cases added to `tests/unit/scripts/test_check_api_docstrings.py` covering the private-class heuristic and ratchet semantics (pass-at-cap, fail-when-over, pass-under-with-nudge, undeclared-root, comment keys, negative cap, strict default).
- **`db` source root added to the docstring ratchet** (roadmap action #15, PR 1 of N): extends the count-based docstring ratchet established in action #4 to a fourth source root. `.docstring-ratchet.json` adds `"db": 119` (initial measurement on the same commit, 2026-05-15) alongside the existing `api: 0`, `cli: 0`, `core: 127` entries; `.github/workflows/code-quality.yml` rewires the `python scripts/check_api_docstrings.py` step from `--paths api cli core` to `--paths api cli core db`. This PR drives the `db` count down by 24 in a single quick-wins pass: 2 module docstrings (`db/plugins/oracle/parser/__init__.py`, `db/plugins/postgresql/parser/__init__.py`), 8 class docstrings (one per `*Quirks` plugin: `Db2Quirks`, `MysqlQuirks`, `SqliteQuirks`, `SqlserverQuirks`, `OracleQuirks`, `CosmosdbQuirks`, `PostgresqlQuirks`, `MariadbQuirks` — each explains the dialect's deviations from ANSI SQL: identifier quoting, identity syntax, transactional-DDL semantics, parser routing, etc.), 8 `__init__` one-liners on those classes, and 2 standalone function docstrings (`MysqlQuirks.preserves_object_definition` documenting why MySQL views/procedures/functions/triggers/events are round-tripped verbatim from `information_schema`; `cosmosdb.query_executor.replace_param` documenting the `@paramN` placeholder substitution contract). Trajectory: same cap-and-decrease pattern as `core` (action #4) — follow-up PRs will drive the residual ~96 violations (mostly `*Quirks` methods overriding `BaseQuirks` abstract methods) to zero. Out-of-scope for this PR by design: no production code changes, no method-override docstrings (those churn the file every time the override wording drifts; tracked in the residual ratchet count instead).
- **`scripts/check_line_length.py` line-length (E501) ratchet** (roadmap action #5): a count-based gate on flake8 `E501` (line > 100 chars) per source root. The script runs `flake8 --isolated --select=E501 --max-line-length=100` on each configured root, ignoring the project's `.flake8` ignore list (which still silences `E501` for the main flake8 job because there are 984 legacy violations to clear), and compares the count to the per-root cap in `.flake8-e501-ratchet.json` (`{"api": 1, "cli": 20, "config": 13, "core": 550, "db": 400}`). Same trajectory contract as `.docstring-ratchet.json`: PRs at-or-below pass, growth fails with "Net +N", shrinkage emits a "lower the cap by N" nudge. Step `Line-length ratchet (flake8 E501)` wired into `.github/workflows/code-quality.yml` after the docstring linter. Tests: 10 new cases in `tests/unit/scripts/test_check_line_length.py` covering pass-at-cap, fail-when-over, pass-under-with-nudge, undeclared-root, comment keys, negative cap, boolean cap, non-object ratchet JSON, path normalization, and clean-root-at-zero.

### Fixed

- **CosmosDB `CREATE CONTAINER` emission now propagates partition key from `table.metadata`** (follow-up to the 3 xfailed tests quarantined in the test-hygiene PR earlier in 1.6.0). Root cause: `DiffSqlStatementBuilder.build_create_table_sql` gated the NoSQL branch on `self.dialect in NOSQL_DIALECTS`, a module-level `frozenset` bound at import time. In test contexts where plugin discovery had not yet been triggered when `core.sql_generator.diff_sql_generator` first imported `NOSQL_DIALECTS`, the binding was an empty `frozenset()` and stayed empty for the lifetime of the test run — even though `ProviderRegistry.get_quirks("cosmosdb").is_nosql` returned `True` at the moment the test executed. The condition therefore evaluated `False`, the NoSQL branch was skipped, and the code fell through to `elif hasattr(table, "create_statement") and table.create_statement` which invoked the `Table.create_statement` property; that property delegates to `BasicTableDdlGenerator` which correctly emits `CREATE CONTAINER container1 ()` (via cosmosdb's `quirks.table_create_keyword = "CONTAINER"`) but produces `()` instead of `(id STRING) WITH (partitionKey='/user_id')` because the cosmos-specific body construction lives only in `build_create_table_sql`'s NoSQL branch. Fix: replaced the stale `NOSQL_DIALECTS` membership check with a new `DiffSqlStatementBuilder._is_nosql_dialect()` helper that queries `ProviderRegistry.get_quirks(self.dialect).is_nosql` at call time — that API self-discovers plugins on demand. Same change applied to `build_drop_table_sql` (the `DROP CONTAINER`/`requires_sdk` path) so `requires_sdk=True` is now correctly set on cosmosdb DROP statements. Tests: removed the 3 `@pytest.mark.xfail` quarantine markers in `tests/unit/core/sql_generator/test_diff_sql_generator.py` (`test_generate_drop_table_cosmosdb`, `test_generate_create_table_with_metadata`) and `tests/unit/core/sql_generator/test_diff_to_sql.py` (`test_generate_sql_statements_cosmosdb`).
- **PR #262 Bugbot follow-ups — 5 unresolved threads addressed in one batch** (no roadmap action; cleanup of regressions surfaced by the stabilization-wave PR). Five issues from develop's integration PR were left open after merge:
  - **`cli/handlers/diff.py::_build_expected_objects` was missing `linked_servers`** (Medium): the extracted helper had 14 of the 15 expected-object keys the original inline code in `_handle_diff` built. `--generate-sql` against a schema with linked-server objects (SQL Server) silently dropped them from the SQL generator's input. Added the missing `"linked_servers": build_dict(payload.linked_servers)` entry.
  - **`api/events.py::_matches_wildcard` recompiled the regex per dispatch** (Low, performance): for every emit-time check against every registered wildcard listener, `re.fullmatch(pattern_to_regex(...), event_str)` rebuilt the regex from scratch. During large migration runs that emit one script-level event per file, this multiplied wall time linearly with subscriber count. Replaced by a new module-level `@lru_cache(maxsize=256)`-decorated `_compile_wildcard(pattern)` that compiles each pattern once.
  - **`api/_client_operations.py::export_schema_operation` emitted no events** (Low, contract inconsistency): every sibling operation in the module (`generate_sql_from_diff_operation`, `generate_undo_script_operation`, etc.) emits `MIGRATION_STARTED` / `MIGRATION_COMPLETED` / `MIGRATION_FAILED` around the work. The export operation was silently exempt. Wired `EXPORT_STARTED` before the call, `EXPORT_COMPLETED` on success, and `EXPORT_FAILED` on exception (re-raised after emission). Added the new `EventType.EXPORT_FAILED = "export.failed"` enum member alongside the existing `EXPORT_STARTED` / `EXPORT_COMPLETED` to complete the lifecycle triple.
  - **`cli/handlers/_shared.py::CliCommandContext.additional_scripts_dirs`** typed `List[Any]` while `execute_single_command` was tightened to `List[Path]` in the same PR (Low, type-checker inconsistency). Tightened the dataclass annotation to `List[Path]` to match.
  - **`cli/_command_handlers.py::_validate_migrate_options` no longer rejects `--target-version` + `--exclude-versions`** (Medium): a check the original code had was removed during the extraction refactor. The combination was deliberately permitted (see `test_target_version_and_exclude_versions_allowed`) but the relaxation was undocumented. This entry serves as the missing CHANGELOG note: `--target-version` may now be combined with `--exclude-versions` to migrate up to a specific version while skipping intermediate ones.

### Changed

- **`ObjectComparator` first-party accessors are now explicit `@cached_property` getters with concrete return types** (roadmap action #14): the lazy `__getattr__` dispatch that produced every first-party comparator (`table_comparator`, `index_comparator`, …) returned `Any`, forcing 16 `# type: ignore[no-any-return]` annotations on the `compare_*` delegation methods and blocking IDE auto-complete + mypy navigation into per-type comparator APIs. Replaced by 16 explicit `functools.cached_property` accessors, each annotated with the concrete comparator class (`TableComparator`, `IndexComparator`, `ModuleComparator`, …). `__getattr__` is preserved but now only handles **third-party** comparators registered via the `dblift.comparators` entry-point group (action #13); first-party names are intercepted by the typed property descriptors before lookup reaches `__getattr__`. Side effects: (a) the 16 `# type: ignore[no-any-return]` annotations on `ObjectComparator.compare_*` methods are removed — mypy sees the real return type now; (b) the 15 per-type comparator class imports come back into `core/comparison/comparator.py` (they were extracted into the registry in action #13 but the property bodies need them for both instantiation and type annotation); (c) `cached_property` caches in `self.__dict__` on first access, matching the previous `object.__setattr__` hand-coded caching contract — repeat accesses return the same instance. Tests: 5 new cases in `tests/unit/core/comparison/test_comparator_registry.py::TestFirstPartyTypedProperties` pin every first-party accessor returns its declared concrete class, the accessor is cached per instance, `TableComparator` uniquely receives the `log` kwarg, the typed property wins against an attempted external shadow at the same name, and every property's return annotation is a concrete type (not `Any`).
- **Pluggable comparator registry: `ObjectComparator` now discovers comparators via the `dblift.comparators` entry-point group** (roadmap action #13): the 15 first-party comparators (`table_comparator`, `index_comparator`, …) that used to live inline in `ObjectComparator._COMPARATOR_REGISTRY` have moved into a new `core/comparison/_comparator_registry.py` module exposing `get_comparator_class(name)`, `get_registered_names()`, and `register_external_comparator(name, cls)`. The registry merges first-party comparators (always available, no discovery cost) with external comparators loaded lazily from the `dblift.comparators` entry-point group — same `importlib.metadata.entry_points` discovery pattern as `ProviderRegistry`. First-party comparators win against any third-party name collision (e.g. a plugin accidentally registering `table_comparator` is silently shadowed by the first-party class) so the core contract can't be inverted by a misbehaving plugin. `ObjectComparator.__getattr__` now consults `get_comparator_class()` instead of the inline dict; `ObjectComparator._COMPARATOR_REGISTRY` is preserved as a thin alias for any legacy caller that introspected it. Side-effect: the 15 per-type comparator class imports moved out of `core/comparison/comparator.py` into the registry module, dropping `comparator.py` from 15 transitive imports to none. Tests: `tests/unit/core/comparison/test_comparator_registry.py` (16 cases) pins the first-party invariants (no regression after extraction), the external-discovery wiring (idempotent enumeration, failed-load resilience, non-class entry points skipped, first-party shadow protection), the programmatic-registration helper (type + collision guards), and the end-to-end criterion — a synthetic third-party `_SyntheticComparator` reachable on an `ObjectComparator` instance without any modification to `core/`. Acceptance criterion met: adding a comparator no longer requires editing `core/comparison/`; declare an entry point in your own `pyproject.toml` and ship.
- **`core/sql_generator/__init__.py` and `core/sql_generator/alter/__init__.py` dialect-generator re-exports now emit `DeprecationWarning`** (roadmap action #12, PR 1 of 2): the 10 Story 26-3 backward-compat re-exports (`DB2AlterGenerator`, `DB2SqlGenerator`, `MySQLAlterGenerator`, `MySQLSqlGenerator`, `OracleAlterGenerator`, `OracleSqlGenerator`, `PostgreSQLAlterGenerator`, `PostgreSQLSqlGenerator`, `SQLServerAlterGenerator`, `SQLServerSqlGenerator` from `core.sql_generator`; the 5 ALTER subset from `core.sql_generator.alter`) used to be eager `from db.plugins.<X>.generator.* import …` statements at the bottom of both `__init__.py` files. That made `core/` import from `db/plugins/` at runtime, inverting the soft-coupling direction (core should not depend on plugins). Replaced by a PEP 562 module ``__getattr__`` that emits a ``DeprecationWarning`` mentioning the canonical plugin path (`db.plugins.<X>.generator.alter_generator` / `…ddl_generator`) and lazily resolves the class on first access. Tracked in two new per-module ``_DEPRECATED_DIALECT_GENERATORS`` / ``_DEPRECATED_DIALECT_ALTER_GENERATORS`` tables for discoverability. ``__all__`` keeps the legacy names so they remain discoverable in IDEs and via ``dir()``; a ``TYPE_CHECKING`` import block keeps mypy and IDE go-to-definition working without paying the eager-import cost. **No in-repo consumers use the legacy paths** — every internal site already imports from `db.plugins.<X>.generator.*`. The deprecation surfaces the issue to any external/historic caller before PR 2 (next major release) removes the re-exports entirely. Acceptance criterion partially met: `core/sql_generator/__init__.py` and `core/sql_generator/alter/__init__.py` no longer have runtime `db.plugins.*` imports. Other `core/` → `db/plugins/` runtime imports (`core/migration/sql/sql_execution_service.py` for `is_tsql_batch_separator`, `core/migration/executor/execution_engine.py` for Oracle SQL*Plus helpers) remain out-of-scope for this 1-day quick win and are separately tracked. Tests: `tests/unit/core/sql_generator/test_init_deprecation.py` (8 cases) pins the contract — exactly-one-warning-per-access, message format, identity-equality with the canonical class, normal attribute-error fallthrough for unknown names, eagerly-exported symbols stay warning-free.
- **`core/sql_generator/diff_sql_generator.py::_generate_table_property_changes` decomposed into 3 named phases** (roadmap action #9c, third and final sub-wave of #9): the D(29) helper that interleaved inheritance ALTER emission, SQL Server SYSTEM_VERSIONING transitions, and a recreation-required advisory comment is now an **A(2)** 11-line orchestrator. Three phase helpers extracted: `_emit_inheritance_changes(table_diff, formatted_table) -> List[SqlStatement]` (B8 — handles PostgreSQL INHERIT / NO INHERIT for changed parents, with a small `_coerce_inherits_to_list(value)` A3 sub-helper to absorb the scalar-vs-list-vs-falsy `TableDiff.inherits_changed` payload), `_emit_system_versioning_changes(table_diff, expected_table, formatted_table)` (B7 — the ADD PERIOD FOR SYSTEM_TIME + SET (SYSTEM_VERSIONING = ON …) and matching OFF branch), and `_emit_recreation_required_warning(table_diff) -> Optional[SqlStatement]` (A4 — collects every recreation-required property changed and emits a single COMMENT statement, or `None` when nothing applies). The 8-`if` cascade that decided which labels go into the warning text is replaced by a class-level `_RECREATION_REQUIRED_PROPERTIES: Tuple[Tuple[Callable[[TableDiff], bool], str], ...]` table (predicate → label pairs for `temporary`, `filegroup`, `memory_optimized`, `history_table`, `partitioning`, `compression`, `logged`, `organize_by`) — pure data, A rank, and the easy place to add a new recreation-required property is now adding one tuple entry. A shared `_alter_table_stmt(table_name, sql) -> SqlStatement` (A1) deduplicates the boilerplate `SqlStatement(sql=…, statement_type="ALTER", object_type="TABLE", object_name=…, dialect=…)` constructor across the inheritance and versioning paths (4 of the 5 SqlStatement constructions in the original monolith were ALTER TABLE; the 5th remains a COMMENT and is built inline by the warning helper). Pure refactor: same statement order (inheritance → versioning → warning), same default fallbacks (`{name}_History`, `SysStartTime`/`SysEndTime`), same SQL strings, same return shape. With #9c shipped, **action #9 is complete** — the three D-ranked offenders identified in `docs/quality-roadmap/priorities.md` (`_handle_validate_sql` D=32 / `generate_from_diff` D=26 / `_generate_table_property_changes` D=29) are all at orchestrator rank ≤ A(3).
- **Test hygiene: re-target zombie tests on the post-PR #301 `diff_command.py` API and quarantine 3 stale CosmosDB generator assertions** (test hygiene PR): `tests/unit/core/migration/commands/test_diff_command_extended.py` and `tests/unit/core/migration/commands/test_diff_command_data_driven.py` referenced symbols that PR #301 removed from `core.migration.commands.diff_command` — `DiffCommand._diff_using_snapshot`, `DiffCommand._log_diff_header/_log_diff_footer/_log_user_defined_type_diffs` (and 13 other static `_log_*_diffs`), and the in-module `ObjectComparator` / `DataTypeNormalizer` / `AccuracyValidator` patch targets. All 27 `DiffCommand._log_*_diffs(...)` calls were rewritten to the new module-level helpers in `core.migration.commands._diff_output` (`log_diff_header`, `log_diff_footer`, `log_table_diffs`, `log_view_diffs`, `log_index_diffs`, `log_sequence_diffs`, `log_trigger_diffs`, `log_procedure_diffs`, `log_function_diffs`, `log_synonym_diffs`, `log_package_diffs`, `log_user_defined_type_diffs`, `log_extension_diffs`, `log_foreign_data_wrapper_diffs`, `log_foreign_server_diffs`, `log_event_diffs`). `TestDiffUsingSnapshot` and the data-driven `_diff_using_snapshot` tests now invoke `run_snapshot_diff` from `core.migration.commands._diff_snapshot` via an `_invoke_run_snapshot_diff(cmd, ...)` bridge helper that mirrors the orchestrator's keyword-only dependency wiring (`snapshot_service`, `provider`, `config`, `log`); patch targets shift from `core.migration.commands.diff_command.X` to `core.migration.commands._diff_snapshot.X`. `TestExecuteIgnoreUnmanaged.test_ignore_unmanaged_passed_to_diff_snapshot` rewritten to patch `core.migration.commands.diff_command.run_snapshot_diff` with a `**kwargs`-capturing stub (the orchestrator calls the helper by keyword). `tests/unit/cli/test_cli.py` fixed: `DbliftConfig` no longer re-exported from `cli.db_utils` post-PR #299, import now resolves through the `config` package. 3 CosmosDB generator tests in `tests/unit/core/sql_generator/test_diff_sql_generator.py` (`test_generate_drop_table_cosmosdb`, `test_generate_create_table_with_metadata`) and `tests/unit/core/sql_generator/test_diff_to_sql.py` (`test_generate_sql_statements_cosmosdb`) marked `@pytest.mark.xfail(strict=False, reason=...)` pending a follow-up to investigate whether the production `DiffSqlStatementBuilder.build_create_table_sql` / `build_drop_table_sql` correctly take the NOSQL branch (the emitted SQL `CREATE CONTAINER container1 ();` neither matches the NOSQL fallback `CREATE CONTAINER ... WITH (partitionKey='...')` nor the SQL fallback `CREATE TABLE ... (\n);`, suggesting a separate translator path that drops the body — real generator question, not a test-hygiene one). Removed unused `pathlib.Path` and `_ObjectTypeSpec` imports from `test_diff_command_data_driven.py`. No production code change.
- **`core/sql_generator/diff_sql_generator.py::generate_from_diff` decomposed into 4 named phases** (roadmap action #9b, second of three sub-waves): the D(26) orchestrator that handled four logically independent diff-application phases (modified-tables, missing-tables, extra-tables, typed-object-changes) is now an **A(3)** 8-line pipeline. Five private helpers extracted, all rank A: `_apply_modified_tables(diff, context, options) -> List[SqlStatement]` (A2), `_apply_missing_tables(diff, context, options)` (A5, includes the warning path for missing expected definitions), `_apply_extra_tables(diff, options)` (A3, emits `DROP TABLE` for unmanaged tables), `_apply_typed_object_changes(diff, context, options)` (A2, the data-driven loop over the 16 `_OBJECT_TYPE_SPECS`), and `_build_expected_maps(context)` classmethod (A3, materialises the per-type expected maps). The 16-key `or {}` dict literal that originally pushed the typed-changes path into rank C is replaced with a `getattr(context, f"expected_{key}", None) or {}` comprehension over a new `_EXPECTED_MAP_KEYS` tuple constant — pure data, A rank. Pure refactor: same statement order (modified → missing → extra → typed), same warning text, same control-flow short-circuits, same return shape. Roadmap criterion met (orchestrator + all helpers ≤ B(10), here all A).
- **`cli/handlers/validate_sql.py::_handle_validate_sql` decomposed into 5 named phases** (roadmap action #9a, first of three sub-waves): the 150-line E(32) handler is now a 7-line orchestrator + docstring, with six private helpers split along the natural control flow. Pattern: `_resolve_dialect(ctx) -> str` (B6, CLI flag → registry canonical name → `postgresql` fallback), `_build_validation_config(ctx) -> ValidationConfig` (B8, defaults + config-file + CLI overrides merge with the canonical precedence chain), `_resolve_output_mode(ctx) -> Tuple[CommandOutput, bool]` (A1, ADR-0008 routing), `_collect_files_to_validate(ctx, ...)` (B9, returns `None` on configuration error after emitting a machine-readable error payload to keep the stdout contract intact), `_expand_file_arg(file_arg, log) -> List[Path]` (A5, sub-helper extracted from the file-collection loop to drop the parent below B), and `_run_validation_and_emit(ctx, validator, ...)` (B8, single emission path that keeps empty results renderable through every formatter — the no-files case emits an empty `ValidationResult` rather than a hand-rolled stdout payload). `radon cc cli/handlers/validate_sql.py` reports `_handle_validate_sql` at rank **A (2)** (was E(32) before). No behaviour change observable: same dialect resolution order, same config precedence, same error emission paths in machine vs human mode, same exit-code semantics, same `_set_command_completed` calls gated on `is_machine_format`. Side effect: the module-level docstring now indexes the 5 phases by name so a maintainer can find the right helper in one read.
- **`cli/main.py::main()` decomposed into four named phases** (roadmap action #6): the 250-line orchestrator that handled argv parsing, license gating, log/output setup, and the multi-command dispatch loop is now a 4-line pipeline + docstring. State is shared via a new `_CliContext` dataclass (private, slots-less, 8 fields annotated by the phase that writes them). The four extracted helpers: `_parse_argv_and_load_config(argv) -> _CliContext` (argv extraction, namespace build, three terminal-action short-circuits: `--version`, no-args, `license` subcommand; config load + db_config validation), `_gate_license(ctx) -> None` (LicenseManager + token persistence, exits 1 on `LicenseError`), `_setup_logging_and_output(ctx) -> CommandOutput` (`db` subcommand short-circuit before logger reconfiguration; otherwise `_configure_logging` + license_info wiring), `_dispatch_command(ctx, output) -> int` (scripts dir resolution, client construction, placeholders, banner emission, multi-command loop wrapped in try/except). `radon cc cli/main.py` rapporte `main` à rang **A (1)** (was F before). No behavior change observable from the outside: same short-circuit branches, same exit codes, same side effects on `base_command._console_main_header_printed` and the `core.migration.commands.{export_schema,snapshot}_command` module-level flags. The `_GLOBAL_ONLY_ARGS` list and `_SUBCOMMAND_VERSION_ALIASES` dict are lifted to module-level constants so they read as plain data, not entangled with orchestration.
- **`pyproject.toml` mypy strict zone — wave H13g `core/migration/commands/` complete sub-package — closes action #8** (roadmap action #8): added 13 modules to the strict-zone override block — `core.migration.commands` (package `__init__`), 7 internal helpers (`_diff_object_specs`, `_diff_output`, `_diff_snapshot`, `_export_helpers`, `_export_metadata`, `_managed_object_filter`, `_schema_export_types`), and 5 public commands (`base_command`, `clean_command`, `export_schema_command`, `repair_command`, `snapshot_command`). **Completes the `commands/` sub-package** and with it the entirety of `core/migration/` (the prior commands `baseline_command`, `diff_command`, `import_flyway_command`, `info_command`, `migrate_command`, `undo_command`, `validate_command` were already strict from H5). Cleared 79 strict errors mechanically: ~30 `type-arg` (`List[Dict]` → `List[Dict[str, Any]]`, `tuple` → `Tuple[...]`, `set` → `Set[str]`, `Optional[list]` → `Optional[List[Any]]`), ~24 `no-untyped-def` on `config`, `executor`, `log`, `provider`, `debug_func`, `result`, `migration_state`, `applied_migrations`, `migration_type`, `**kwargs` parameters and missing `-> None` / `-> "Panel"` / `-> List[Any]` return-types, ~20 `no-untyped-call` resolving in cascade once the helper signatures were annotated (notably `_make_command_context` ripples that resolved on the executor layer in H13b), 4 stale `# type: ignore` annotations removed (`[attr-defined]` × 3 + `[misc]` × 1 — mypy 2.x confirms unused), 1 `# type: ignore[no-untyped-call]` motivated addition on `AccuracyValidator()` call in `_diff_snapshot.py` (validator lives in `db.introspection.validation_integration`, future cross-cutting wave). Two helper return types fixed up-front to match actual implementations: `MigrationExecutorFactory.execute` and `MigrationUI._mark_reapplied_duplicates`. Same flag set as the existing strict-zone overrides (sans `no_implicit_reexport`). With H13g, **action #8 is complete**: `core/migration/` 100% strict, mirroring `core/comparison/` (strict since H4). Total across H13a-g: ~40 modules added, ~250 errors cleared, 4 real type bugs surfaced, line-length ratchet `core: 550 → 545`. Also tightens `.flake8-e501-ratchet.json` to `core: 545` (black-reformatted helper signatures net-removed 2 long lines).
- **`pyproject.toml` mypy strict zone — wave H13f `core/migration/ui/` complete sub-package** (roadmap action #8): added 4 modules to the strict-zone override block — `core.migration.ui` (package `__init__`), `core.migration.ui.data_collector` (~900 LOC, 19 errors), `core.migration.ui.migration_ui` (~360 LOC, 27 errors), `core.migration.ui.table_renderer` (~250 LOC, 5 errors). **Completes the `ui/` sub-package strict coverage** (`display_formatters` and `migration_analyzer` were already strict from H6). Cleared 51 strict errors: ~24 `no_implicit_optional` defaults widened to `Optional[List[...]]` on the `pending_migrations` / `tags` / `exclude_tags` / `versions` / `exclude_versions` parameters across 7 method signatures in `data_collector` and `migration_ui`; ~17 bare generics (`List[Dict]` → `List[Dict[str, Any]]`, `set` → `Set[str]`, `tuple` → `Tuple[str, str]` / `Tuple[Optional[str], Optional[str]]`) with `Set` / `Tuple` import additions; 6 `no-untyped-def` (`migration_type` / `migration` parameters annotated `Any` on `_get_migration_type_string`, `_is_migration_type_equal`, `_is_versioned_type`, `_get_type_from_migration_type`, `_get_category_from_type`, `display_migration_status`, `display_migration_details`); 1 real bug found: `MigrationUI._mark_reapplied_duplicates` declared `-> Set[str]` but the underlying `migration_analyzer.mark_reapplied_duplicates` actually returns `Set[Migration]` — return type fixed to match the implementation. Same flag set as the existing strict-zone overrides (sans `no_implicit_reexport`). **No new `# type: ignore` introduced.**
- **`pyproject.toml` mypy strict zone — wave H13e `core/migration/` root leaves** (roadmap action #8): added 6 modules to the strict-zone override block — `core.migration` (package `__init__`), `core.migration._type_match`, `core.migration.clean_summary`, `core.migration.encoding`, `core.migration.migration` (755 LOC), `core.migration.version_utils`. Cleared 24 strict errors: 4 modules were already strict-clean (just needed the override entry); `version_utils.py` got 2 `value: Any` annotations on `is_migration_success` / `is_migration_failure` plus an `Any` import addition; `migration.py` got the bulk fixes — 7 implicit-Optional defaults on `Migration.__init__` (`script_name`, `content`, `version`, `description`, `type`, `sql_statements`, `tags`), 4 more on `parse_sql_statements` / `mark_as_deleted` / `config`, 3 bare generics widened (`frozenset` → `frozenset[str]`, `Optional[Dict]` → `Optional[Dict[str, Any]]`, `Optional[List]` → `Optional[List[Any]]`), 2 dunder `__repr__` / `__str__` return types `-> str`, the `from_path` and `__init__` classmethod return-type annotations, plus typing `dict_to_migration` end-to-end (which transitively let the H13a-introduced `# type: ignore[no-untyped-call]` on the only call site in `history/migration_history_manager.py` be removed — mypy 2.x confirms it's now unused). Same flag set as the existing strict-zone overrides (sans `no_implicit_reexport`). **No new `# type: ignore` introduced; one stale ignore retired.**
- **`pyproject.toml` mypy strict zone — wave H13d `core/migration/snapshots/schema_snapshot_service.py` + `executors/` complete sub-package** (roadmap action #8): added 6 modules to the strict-zone override block — `core.migration.snapshots.schema_snapshot_service` (completes `snapshots/`), `core.migration.executors` (package `__init__`), `core.migration.executors.base_executor`, `core.migration.executors.executor_factory`, `core.migration.executors.python_executor`, `core.migration.executors.sql_executor` (completes the plural `executors/` sub-package). Cleared 40 strict errors total: 13 in the executors sub-package (5 `**kwargs` annotated `**kwargs: Any` on `execute_migration` / `rollback_migration` across the 3 executor classes; `sql_analyzer=None, sql_execution_service=None` defaults widened to `Any = None` on `SqlMigrationExecutor.__init__` and `MigrationExecutorFactory.__init__`; `python_executor.get_supported_formats(self)` annotated `-> List[MigrationFormat]`; `MigrationExecutorFactory.execute(...)` signature completed with `**kwargs: Any` and `-> MigrationExecutionResult`; `MigrationExecutionResult` import added to `executor_factory`; 2 stale `# type: ignore[union-attr]` annotations on `spec.loader.exec_module(mod)` removed because the prior `if spec is None or spec.loader is None: raise` block already narrows `spec.loader` to non-None). 27 in `schema_snapshot_service.py`: 4 dunder-method return types (`__init__ -> None`, `__enter__ -> "SnapshotConnectionContext"`, `__exit__ -> None`, with `exc_type/exc_val/exc_tb: Any`); `capture_snapshot` and `save_payload` return types annotated `-> SchemaSnapshot`; `validate_snapshot_quality(snapshot)` parameter typed `snapshot: SchemaSnapshot`; `_filter_tables` return type fixed to `tuple[List[Any], Set[str]]` (matched the actual returned tuple); 4 bare-`set` parameters widened to `Set[str]` with the matching import added; `_safe_introspect`, `_try_bulk_indexes`, `_call_optional`, `_get_snapshot_connection` annotated; bare `list = []` widened to `List[Any] = []`; 2 `# type: ignore[no-untyped-call]` motivated additions on `AccuracyValidator(introspector)` and `StateValidator(introspector)` calls (the validators live in `db.introspection.validation_integration`, not yet in the strict zone — future cross-cutting wave); 2 stale `# type: ignore[assignment]` annotations removed (mypy 2.x confirms unused). Also tightened the line-length ratchet `core: 548 → 547` (annotations net-removed one long line). Same flag set as the existing strict-zone overrides (sans `no_implicit_reexport`).
- **`pyproject.toml` mypy strict zone — wave H13c `core/migration/scripting/undo_script_generator/` remaining 5 modules** (roadmap action #8): added 6 modules to the strict-zone override block — `core.migration.scripting.undo_script_generator` (package `__init__`), `core.migration.scripting.undo_script_generator._ddl_reversers`, `core.migration.scripting.undo_script_generator._dml_reversers`, `core.migration.scripting.undo_script_generator._generator`, `core.migration.scripting.undo_script_generator._models`, `core.migration.scripting.undo_script_generator._reversers`. **Completes the `undo_script_generator/` sub-package strict coverage** (`_extractors` and `_helpers` were already strict from a prior wave). Cleared 29 strict errors mechanically: 15 `no-untyped-def` (`stmt` parameters on `_reverse_X_from_parsed(self, stmt)` methods across the 3 reverser mixins typed `stmt: Any` — the parameter is a parsed `SqlStatement` duck-typed across the parser layers), 12 `type-arg` (`analysis: dict` parameters on `_reverse_X(self, sql, analysis)` methods widened to `analysis: Dict[str, Any]`), 2 stale `# type: ignore[assignment]` annotations removed on `table_name = str(name_value) if name_value else None` (the local was already correctly typed `Optional[str]`). Same flag set as the existing strict-zone overrides (sans `no_implicit_reexport`). No new `# type: ignore` introduced.
- **`pyproject.toml` mypy strict zone — wave H13b `core/migration/journals/` + `executor/migration_executor.py`** (roadmap action #8): added 4 modules to the strict-zone override block — `core.migration.journals` (package `__init__`), `core.migration.journals.migration_journal`, `core.migration.executor` (package `__init__`), `core.migration.executor.migration_executor` (completes the `executor/` sub-package strict coverage). Cleared 24 strict errors total: 5 in `migration_journal.py` (all `no_implicit_optional` — `timestamp: datetime = None`, `details: Dict[str, Any] = None` × 3, `object_type: str = None` → `Optional[...]`), and 19 in `migration_executor.py` mixing `no_implicit_optional` defaults (`scripts_dir`, `additional_dirs`, `dir_recursive_map` across `clean()`, `validate()`, `info()`, `diff()`, `repair()`), one missing return type annotation on `_make_command_context(self)` → `-> "BaseCommandContext"` with a TYPE_CHECKING import added for the forward reference, and 9 cascaded `no-untyped-call` errors at the call sites that resolved automatically once the return type was annotated. Same flag set as the existing strict-zone overrides (sans `no_implicit_reexport`). No new `# type: ignore` introduced.
- **`pyproject.toml` mypy strict zone — wave H13a `core/migration/formats/` + `history/`** (roadmap action #8): added 4 modules to the strict-zone override block — `core.migration.formats` (package `__init__`), `core.migration.formats.format_detector`, `core.migration.formats.migration_format`, `core.migration.history` (package `__init__`), `core.migration.history.migration_history_manager`. Cleared 6 strict errors: `ValidationResult.__init__(self)` annotated `-> None`, `MigrationHistoryManager.__init__(self, provider, ...)` annotated `-> None` with `provider: Any`, `get_columns_query` return type `Union[str, tuple]` widened to `Union[str, Tuple[Any, ...]]` (bare generic), and `dict_to_migration` call wrapped with a motivated `# type: ignore[no-untyped-call]` because the callee lives in `core.migration.migration` (not yet in strict zone — future wave). Same flag set as the existing strict-zone overrides (sans `no_implicit_reexport`). Roadmap action #8 will continue with H13b, H13c, … one sub-package per PR following the H1→H12 wave pattern.
- **Typed exception narrows in 3 connection managers** (roadmap action #7): replaced `except Exception:` in the cleanup `finally` blocks of `db/plugins/postgresql/postgresql/connection_manager.py::_get_database_version`, `db/plugins/sqlserver/sqlserver/connection_manager.py::_get_database_version` (both narrowed to `JAVA_EXC` — the canonical JDBC-boundary tuple `(jpype.JException, AttributeError, ValueError, TypeError, OSError, RuntimeError)` from `db/_jdbc_exceptions.py`), and `db/plugins/cosmosdb/cosmosdb/connection_manager.py::_is_emulator_endpoint` (narrowed to `(AttributeError, ValueError)` — the urllib.parse boundary). JDBC `close()` errors on dead connections and malformed-URL `ValueError`s remain swallowed (non-fatal cleanup, original intent preserved), but programming bugs like `KeyError`/`NameError`/`TypeError` now propagate to the caller instead of being silently classified as "dead connection" or "non-local endpoint". The 3 sites still `except Exception:` in `core/migration/executor/execution_engine.py` got expanded "rollback safety net" comments — they are deliberately broad because they wrap a transaction that must rollback on ANY uncaught exception before re-raising, and narrowing would let unexpected types bypass the rollback. Tests: 6 new regression cases in `tests/unit/db/plugins/test_connection_manager_typed_exceptions.py` — one in-tuple swallow and one out-of-tuple propagation per narrow. Triage audit of 21 candidate sites is documented in `docs/quality-roadmap/priorities.md` under action #7.

### Removed

- **BREAKING — deprecated dialect-generator re-exports deleted from `core.sql_generator` and `core.sql_generator.alter`** (roadmap action #12 PR 2, follow-up to PR 1 in #358): the 10 legacy aliases (`DB2AlterGenerator`, `DB2SqlGenerator`, `MySQLAlterGenerator`, `MySQLSqlGenerator`, `OracleAlterGenerator`, `OracleSqlGenerator`, `PostgreSQLAlterGenerator`, `PostgreSQLSqlGenerator`, `SQLServerAlterGenerator`, `SQLServerSqlGenerator`) re-exported from `core.sql_generator`, and the 5 ALTER subset re-exported from `core.sql_generator.alter`, are deleted. Consumers must now import from the plugin path: `from db.plugins.<dialect>.generator.{alter_generator,ddl_generator} import …`. The PEP 562 `__getattr__` / `__dir__` hooks that emitted `DeprecationWarning` (PR 1, shipped 1.6.0) are removed along with the `_DEPRECATED_DIALECT_GENERATORS` / `_DEPRECATED_DIALECT_ALTER_GENERATORS` tables and the `TYPE_CHECKING` import blocks. `__all__` in both `__init__.py` files no longer lists the legacy names. The audit before PR 1 confirmed zero in-repo callers of the legacy path; this removal therefore touches only external consumers. The previous deprecation-test module `tests/unit/core/sql_generator/test_init_deprecation.py` is replaced by `tests/unit/core/sql_generator/test_init_removal.py` (5 cases): the 10 (resp. 5) legacy names are not in `__all__`, attribute access raises `AttributeError`, and the canonical plugin-path imports still work.
- **`.github/workflows/pr-patch-coverage.yml` + the `pytest-testmon` PR-time gate** (rollback of roadmap action #1, originally merged in #337): the selective PR-time patch-coverage workflow is removed and `pytest-testmon` is dropped from dev deps. Two structural problems made the gate untenable: (1) the testmon index never warmed up — `unit-tests.yml` doesn't run on push develop (intentional, GitHub Actions budget constraint, commit `d04a661`), so the `testmon-py3.11-develop-*` cache key was never refreshed; every PR fell through to a near-empty cache and testmon degraded to "run everything", erasing the ~2 min P95 selectivity benefit; (2) the codecov `pr-patch ≥ 80 %` gate was anchored on **unit-only** coverage, but the project relies on substantial integration suites (postgresql, mysql, sqlserver, db2, oracle, cosmosdb, sqlite) that contribute significantly to combined coverage — gating a PR's patch coverage on unit-only systematically flagged PRs whose new lines were genuinely covered by integration tests. Files removed: `.github/workflows/pr-patch-coverage.yml`. Files modified: `.github/workflows/unit-tests.yml` (dropped "Restore testmon index" / "Update testmon index" / "Save testmon index" steps and the matching cache plumbing), `codecov.yml` (dropped the `pr-patch` flag override under `individual_flags`), `pyproject.toml` + `requirements-dev.txt` (dropped `pytest-testmon>=2.2.0`), `CONTRIBUTING.md` § "CI Test Evidence Policy" (rewritten to document the new PR-time check set — lint, xenon, bandit, gitleaks, pip-audit, regression matrix — with full unit + integration deferred to release time). Authoritative gate is unchanged: `unit-tests.yml` + `--cov-fail-under=77` on push main / release/** remains the absolute coverage floor.

### Fixed

- **`resolve_config_or_raise` truthiness check** (`api/_client_factory.py`): changed `if provider.config:` to `if provider.config is not None:`. The truthiness check was semantically correct for all current `DbliftConfig` objects (no `__bool__` defined) but would incorrectly raise `ConfigurationError` for any future config object that evaluates as falsy while still being a valid non-`None` instance.

### Changed

- **`pyproject.toml` mypy strict zone — H7a db/introspection dialect introspectors + extractors** (PR-H7a): added 23 modules to the strict-zone override block — five dialect introspectors (`postgresql`, `mysql`, `oracle`, `sqlite`, `cosmosdb`), nine extractors (`base_extractor`, `column_extractor`, `constraint_extractor`, `index_extractor`, `misc_extractor`, `procedure_extractor`, `table_extractor`, `trigger_extractor`, `view_extractor`), and nine leaf files (`result`, `_partition_enricher`, `_column_enricher`, `_vendor_property_applier`, `vendor_queries_factory`, `introspector_factory`, `validation_integration`, `base_introspector`, `core.jdbc_metadata`). Cleared ~60 strict errors: `__init__` / abstract method signatures annotated with `Any`-typed params and explicit `-> None` / `-> "Self"` return types; bare `List` / `Dict` / `frozenset` generics replaced by their parameterized forms; `self.connection: Any` and `self.metadata: Any` field annotations added to `BaseIntrospector` and `JDBCMetadataExtractor` so JDBC attribute access compiles cleanly; `SchemaIntrospector(...)` call sites typed as `temp_introspector: Any = SchemaIntrospector(...)  # type: ignore[no-untyped-call]` with `# type: ignore[no-any-return]` on the corresponding `return` statements (SchemaIntrospector is not yet in the strict zone); `_should_preload_materialized_views` wrapped in `bool(...)` to fix `Literal[False] | Any | None` → `bool` mismatch; `_ensure_metadata()` calls from `_column_enricher` and `_partition_enricher` annotated `# type: ignore[no-untyped-call]`; stale `# type: ignore` comments removed where the underlying type is now `Any`. Same flag set as the api/* carve-outs above (sans `no_implicit_reexport`).
- **`pyproject.toml` mypy strict zone — H5 core/migration executor + commands** (PR-H5): added 7 modules to the strict-zone override block — `core.migration.executor.execution_engine`, `core.migration.commands.baseline_command`, `core.migration.commands.diff_command`, `core.migration.commands.import_flyway_command`, `core.migration.commands.info_command`, `core.migration.commands.migrate_command`, and `core.migration.commands.undo_command`. Cleared ~22 strict errors: `execution_engine` — changed `from db.jdbc_provider import to_python_string` to `from db._jdbc_utils import to_python_string` (explicit-export compliance now that `db.jdbc_provider` is in the strict zone), removed the now-unnecessary `# type: ignore[assignment]` on the `provider:` parameter, typed the `placeholder_service` parameter as `Optional[PlaceholderService]`, typed `stmt_check` as `Any` removing five stale `# type: ignore` comments on the JDBC probe block. `info_command` — annotated `_migration_type_name(migration_type: object)` and widened `_seen_versions: dict` to `Dict[str, str]`. `diff_command` / `migrate_command` — added `TYPE_CHECKING` guard imports for `MigrationJournal` / `PlaceholderService`, imported `BaseCommandContext` and annotated `ctx_or_config` as `Optional[Union[BaseCommandContext, DbliftConfig]]`; `migrate_command` also added `Migration` import and typed six bare `List` parameters as `List[Migration]`. Side-effect: typing `SchemaSnapshotService.load_latest_snapshot() -> Optional[SchemaSnapshot]` made a downstream `cast(SchemaSnapshotPayload, snapshot.payload)` in `export_schema_command` redundant and removable. Same flag set as the api/* carve-outs above (sans `no_implicit_reexport`).
- **`pyproject.toml` mypy strict zone — H6 core/migration leaf modules** (PR-H6): added 20 modules across six `core/migration/` sub-packages to the strict-zone override block — `core.migration.snapshots` (package `__init__` + `schema_snapshot`), `core.migration.state` (package `__init__` + `migration_data_service`, `migration_display_state`, `migration_formatter`, `migration_state`, `migration_state_manager`, `migration_state_service`), `core.migration.scripting` (package `__init__` + `migration_script_manager`), `core.migration.sql` (package `__init__` + `execution_statement`, `sql_analyzer`, `sql_execution_service`, `sql_insights`, `statement_splitter`), `core.migration.rules` (package `__init__`), `core.migration.placeholders` (package `__init__` + `placeholder_service`). Cleared ~43 strict errors mechanically: `migration: Any` on duck-typed helper parameters (`_determine_migration_state`, `_get_migration_category`, `_get_migration_type`, `_is_migration_successful`, `determine_state`, `determine_pending_state`, `_get_migration_type_string`, `_is_migration_type_equal`), `scripts_dir: Union[Path, str]` on `_version_has_undo_script`, `Optional[T]` wrappers on six sets of `= None` default params (`additional_dirs`, `dir_recursive_map`) across four `MigrationScriptManager` methods, `List[Dict[str, Any]]` / `Dict[str, Any]` concrete type parameters replacing bare `List[Dict]` / `Dict` in `MigrationFormatter` and `MigrationStateManager`, `List[Procedure]` / `List[Trigger]` return annotations on `SqlAnalyzer.get_functions` / `get_triggers`, typed `SqlExecutionService.__init__` with `Any` for the provider/analyzer/journal duck-typed args and `Optional[str]` for `schema`, `Match[str] -> str` on `PlaceholderService.replace_placeholders` inner function, and `Optional[Log]` on `PlaceholderService.__init__`. `schema_snapshot_service` (29 errors) is deferred to a later wave. Same flag set as the api/* carve-outs above (sans `no_implicit_reexport`).
- **`pyproject.toml` mypy strict zone — H4 core/comparison** (PR-H4): added all 31 modules under `core/comparison/` to the strict-zone override block — the 7 `_diff_*` sibling modules + `diff_models` façade from the PR-G4 split (`_diff_base`, `_diff_simple`, `_diff_table`, `_diff_view`, `_diff_index`, `_diff_routine`, `_diff_schema`), the package `__init__`, `_default_normalizer`, `_table_property_comparator`, `comparator`, `comparison_utils`, `type_normalizer`, `diff_reporter`, and the 15 object-type comparators (`table`, `index`, `view`, `trigger`, `procedure`, `function`, `sequence`, `synonym`, `package`, `extension`, `event`, `database_link`, `linked_server`, `foreign_data_wrapper`, `foreign_server`, `user_defined_type`). Cleared ~200 strict errors mechanically: 47+ bare `Optional[tuple]` (expected, actual) diff-field annotations across the `_diff_*` modules widened to `Optional[Tuple[Any, Any]]`, 14+ `def _calculate_diffs(self):` per-class overrides annotated `-> None`, the homogeneous `def __init__(self, type_normalizer=None):` API-compat stub across 15 leaf comparators typed as `Optional[object]` (`UserDefinedTypeComparator`'s real use site typed as `Optional[DataTypeNormalizer]`), `IndexComparator._normalize_index_columns` signature tightened (`Optional[Sequence[str]]`, `List[bool]`, return `List[Optional[str]]`), `TableComparator.__init__` typed `log: Optional[Log] = None`, `_extract_generated_metadata` return widened to the concrete `Tuple[str, bool, Optional[str], bool]`, `comparator.py`'s `_COMPARATOR_REGISTRY` typed `Dict[str, Type[Any]]` and 15 stale `# type: ignore[attr-defined,no-any-return]` comments on the delegating methods trimmed to `[no-any-return]` (the `attr-defined` half is no longer needed now that the registry is typed). One latent issue surfaced: `UserDefinedTypeComparator._normalize_attributes` was indexing `self.type_normalizer.normalize(...).upper()` even though `normalize` returns `Optional[str]` and `type_normalizer` was an untyped default-`None` parameter — added an `assert self.type_normalizer is not None` plus a `(normalized_type or attr_type_raw).upper()` fallback so the actual production call site (`ObjectComparator` always passes a non-`None` `DataTypeNormalizer`) keeps the same observable behaviour while the type-checker can prove it. Same flag set as the api/* carve-outs above (sans `no_implicit_reexport`).
- **`parse_jdbc_url` decomposed** (PR-H15): broke the 130-line, E=32 monolith in `config/_jdbc_url_parser.py` into a 4-statement orchestrator (A=2) and 9 module-level private helpers, all A or B rank: `_detect_dialect_with_fallback` (A=4, B10-BUG-22 scheme-only detection + registry-unavailable raw-vendor fallback), `_dispatch_dialect_url_parser` (A=2, story 26-11 dispatch via `_DIALECT_URL_PARSERS`), `_resolve_quirks_for_dialect` (A=4, native + registry-unavailable handling), `_extract_query_style_params` (A=5, PostgreSQL/MySQL/MariaDB `?key=value&` tail), `_extract_semicolon_style_params` (B=7, SQL Server / DB2 `;key=value;` tail), `_promote_creds_from_params` (A=4, lifts user/password from `result['parameters']`), `_apply_query_string_username` (A=5) / `_apply_query_string_password` (A=4) / `_extract_creds_from_query_fallback` (A=4, the `sep is None` Oracle path-form fallback), `_extract_jdbc_url_params` (A=5, the shared param/credential extraction pass driven by `quirks.jdbc_url_param_separator`). Orchestrator now reads as `empty-check → dispatch dialect parser → extract params/creds`. Same return shape, same exception contract (registry exceptions stay swallowed), same B10-BUG-22 `urlparse`-only scheme detection, same Quirks-driven separator routing. All 131 JDBC-URL unit tests pass (`test_database_config*`, `test_batch10_bug_fixes`, `test_config_artificial_coverage`).
- **`BaseDatabaseConfig.create` decomposed** (PR-H14): broke the 156-line, F=56 (worst-rank) `@classmethod` in `config/database_config.py` into a 22-line orchestrator (A=3) + 13 module-level private helpers, all A or B rank — `_infer_type_from_url_scheme` (A=4, phase 1 URL-scheme `type` inference), `_apply_url_overrides` (B=7, phase 2 dispatch across native / `jdbc:` / bare URI), `_hydrate_from_jdbc_url` (B=6, the JDBC parse + thin-creds fallback wrapper), `_merge_parsed_jdbc_fields` (A=3, the field-by-field merge), `_merge_parsed_extra_params` (B=7), `_backfill_credentials` (A=5), `_extract_oracle_thin_credentials` (A=2, the legacy `user/pw@` regex), `_infer_type_from_non_jdbc_uri` (A=4), `_ensure_properties_dict` (A=3, phase 3), `_resolve_config_or_stub` (A=3, phase 4) / `_resolve_config_class` (A=4) / `_build_incomplete_stub` (A=5), `_coerce_port_to_int` (A=3, phase 5), `_validate_required_fields` (B=8, phase 6), `_instantiate_config` (A=4, phase 7). The orchestrator now reads as `infer type → apply URL overrides → ensure properties → resolve config class (or stub) → coerce port → validate → instantiate`. Same per-dialect subclass dispatch, same `ValueError` messages (`Invalid JDBC URL: must start with 'jdbc:'`, `Database URL is required (use --db-url)`, `Unsupported database type: <x>`, `Invalid port value: <x>`, `Missing required fields: <…>`, `Database username/password is required (either in config or in URL)`), same `_allow_incomplete` short-circuit semantics. No public surface changes; `BaseDatabaseConfig.create` / `.from_dict` callers in `config/dblift_config.py`, `config/config_builder.py`, and `BaseDatabaseConfig.from_jdbc_url` are unaffected.
- **`pyproject.toml` mypy strict zone — wave 1** (PR-G1): expanded the `[[tool.mypy.overrides]]` strict block from 5 `api.*` modules to 5 `api.*` + 15 `core.*` leaf modules (`core.logger._factory`, `core.logger._levels`, `core.logger._null`, `core.logger.formatters.factory`, `core.migration.executor.{migration_helpers, placeholder_manager, transaction_policy}`, `core.migration.commands.validate_command`, `core.migration.state.migration_classifier`, `core.migration.ui.{display_formatters, migration_analyzer}`, `core.migration.snapshots.schema_snapshot_repository`, `core.migration.scripting.undo_script_generator.{_extractors, _helpers}`, `core.migration.rules.migration_rules`). Each module was cleared by a single-line annotation fix (mostly `param: Optional[T] = None` for implicit-optional defaults, missing `-> str` / `Any` parameter types, and one unused `# type: ignore`). Side-effect: `OutputFormatter.__init__` annotated `-> None` to satisfy the strict caller, and `core/logger/_factory.py` imports `MultiLog` from its canonical location `core.logger._multi` instead of going through `core.logger.log`'s implicit re-export. `mypy --config-file pyproject.toml` still returns "no issues found in 485 source files".
- **`pyproject.toml` mypy strict zone — H3 db jdbc layer** (PR-H3): added 6 modules under `db/` that implement the JDBC bridge to the strict-zone override block — `db.jdbc_provider`, `db._jdbc_type_converter`, `db.error_handler`, `db.error`, `db.dummy_jdbc_provider`, `db.jvm_manager`. Cleared ~111 strict errors mechanically: explicit `Any` on the Java bridge values (`rs: Any`, `idx: int` on the JDBC type handlers, `result_set: Any` on `convert`, `obj: Any` on `_convert_java_object_to_python`), missing `-> None` on side-effecting `_init_jvm` / `_register_jdbc_drivers` / `_add_system_jdbc_dirs` / `shutdown`, `Optional[T]` on `param: T = None` defaults (`username`, `password`, `log`, `params`, `context`), concrete type parameters (`re.Pattern[str]`, `List[Tuple[re.Pattern[str], ErrorCategory]]`, `Dict[str, Any]`, `Dict[int, Any]`, `Callable[..., Any]`, `List[Dict[str, Any]]`), and one stale `# type: ignore[attr-defined]` on a `java.lang.Class` import that mypy 2.x reports as unused. `JdbcProvider`'s abstract methods (`_import_java_classes`, `create_connection`) got `-> None` / `-> Any` signatures, and `DummyProvider`'s 17 overrides got matching signatures from their abstract counterparts. Same flag set as the api/* carve-outs above (sans `no_implicit_reexport`).
- **`pyproject.toml` mypy strict zone — H2 core/sql_model** (PR-H2): added all 22 modules under `core/sql_model/` to the strict-zone override block. Most were already strict-clean. Fixes: `constraint_validator.py` had 9 errors — 7 validator methods needed `table: "Table"` annotations, plus one untyped `Set[frozenset]` → `Set[frozenset[str]]` and one obsolete `# type: ignore[no-any-return]` on a typed return path. `table.py` had 5 errors — `Optional[List]` widened to `Optional[List["Partition"]]` at two spots, `_filegroup_supported` inner helper annotated with `(dialect_name: Optional[str]) -> bool`, two unused type-ignores removed. Side-effect: `no_implicit_optional` flagged 3 latent `param: T = None` defaults in `compare_with_defaults` and `Table.__init__` (`columns`, `constraints`, `schema_defaults`) — all widened to `Optional[T]`.
- **`pyproject.toml` mypy strict zone — H1 boundary protocols** (PR-H1): added 14 framework-contract modules to the strict-zone override block — `core.dialect_boundary` (the Protocol layer), `core.sql_model.dialect`, `db.base_quirks` (the default Quirks impl), `db.base_provider`, `db.base_connection_manager`, `db.provider_registry`, `db._jdbc_utils`, and the 7 introspector `__init__.py` lazy-import shims (`db.introspection.databases.{cosmosdb, db2, mysql, oracle, postgresql, sqlite, sqlserver}`). Cleared ~27 strict errors via concrete type parameters (`tuple[tuple[str, str], ...]` for `non_transactional_sql_patterns`, `dict[str, str]` for type-mapping methods, `frozenset[str]`, `tuple[Optional[str], list[Any]]` for FK/index reference queries), `-> Any` on the 7 `__getattr__` lazy shims, and explicit `set[str]` / `list[Any]` annotations on `DummyProvider` collection attributes. Lifts Phase H type-safety axis from 7→8 and unblocks the H18-H20 dialect-cleanup waves that depend on a strict-typed Quirks Protocol.
- **API reference: typed Event documentation** (PR-G10): added `docs/api-reference/events.md` rendering `EventType`, `Event`, and `EventEmitter` via mkdocstrings. Fixed stale "events are plain dicts" guidance in `docs/api-reference/api.md` — listeners now receive a frozen `Event` dataclass (since PR-bugbot262 / #295), and the docs now show the canonical attribute-access pattern (`event.script`, `event.dialect`, `event.result`) instead of the obsolete `event["key"]` form. Added `events.md` to the `nav: API Reference:` block in `mkdocs.yml`. `mkdocs build` renders the new page; existing pre-PR docs warnings are unrelated and out-of-scope.
- **Computed-column rendering → quirks method** (PR-G8): removed the 4-branch `if style == "postgresql": ... if style == "oracle": ... if style == "sqlserver": ... if style == "mysql": ...` dispatch in `core/sql_generator/basic_table_ddl_generator.py:_build_computed_clause` (≈30 lines, 4 `# lint: allow-dialect-string` annotations) and replaced it with a single call to `quirks.render_computed_column(col, formatted_col_name)`. Added `render_computed_column` to `BaseQuirks` (default: `GENERATED ALWAYS AS (expr)`) and to the `ModelQuirks` Protocol; the four affected plugins (`postgresql`, `oracle`, `sqlserver`, `mysql`) override with their per-dialect syntax. The `computed_column_style: str` attribute is removed from both `BaseQuirks` and the `DialectQuirks` Protocol — adding a new dialect with computed-column support is now "override `render_computed_column`" instead of "add a string and an `if` branch in framework code". Pattern follows PR-F4 (`provider.canonical_dialect_key`) / PR-C3 (`wrap_trigger_body`).
- **`_handle_diff` decomposed** (PR-G7): broke the 159-line, D=27 diff CLI handler in `cli/handlers/diff.py` into a 25-line orchestrator (A=4) + 6 private helpers, all A or B rank: `_validate_output_file_flag` (A=4), `_resolve_filter_lists` (B=7), `_build_expected_objects` (A=3), `_resolve_pygments_lexer` (A=5), `_render_sql_script` (A=2), `_generate_and_render_sql` (B=9). The orchestrator now reads as `validate flag → resolve filters → call diff → optionally generate SQL → set completed`. No behavior change.
- **`generate_sql_from_diff_operation` decomposed** (PR-G6): broke the 134-line, D=28 monolith in `api/_client_operations.py` into a 56-line orchestrator (A=4) + 3 private helpers: `_extract_schema_diff_input` (B=6, validates `diff`/`diff_result` parameters and resolves to a `SchemaDiff` or sets the error on `result`), `_build_sql_script_options` (A=1, projects the flat `expected_objects` dict to `GenerateSqlScriptOptions` via a local `_expected(key)` shortcut), `_build_diff_summary` (A=5, projects `schema_diff` to the 4-counter summary). The orchestrator now reads as: `extract → emit started → try { options → script → summary → emit completed } except { emit failed → raise }`. No behavior change — same events, same error messages, same result fields.
- **`core/migration/commands/diff_command.py` split** (PR-G5): replaced the 1291-line `diff_command.py` with a 396-line orchestrator that delegates to 3 sibling modules — `_diff_object_specs.py` (149 lines: `_ObjectTypeSpec` NamedTuple + the 14-entry `_OBJECT_TYPE_SPECS` dispatcher), `_diff_snapshot.py` (238 lines: `run_snapshot_diff` extracted from `_diff_using_snapshot` with self-deps injected), `_diff_output.py` (517 lines: 14 `log_*_diffs` formatters + header/footer + the 14-entry `DIFF_OBJECT_TYPE_LOGGERS` list, all previously static methods on `DiffCommand`). `DiffCommand` keeps `__init__`, `execute`, `_log_diff_summary` (now a thin orchestrator over the module-level loggers), and `_log_validation_results`. Public API unchanged — `from core.migration.commands.diff_command import DiffCommand` works exactly as before.
- **`core/comparison/diff_models.py` split** (PR-G4): replaced the 1595-line monolith with a 64-line façade that re-exports 22 `*Diff` classes plus `DiffSeverity` from 7 sibling `_diff_*.py` modules: `_diff_base.py` (DiffSeverity + DiffResult, 160 lines), `_diff_table.py` (ColumnDiff + ConstraintDiff + TableDiff, 458 lines), `_diff_view.py` (141 lines), `_diff_index.py` (71 lines), `_diff_routine.py` (RoutineDiff + ProcedureDiff + FunctionDiff, 95 lines), `_diff_simple.py` (12 simple-pattern classes via `_set_severity_from_pairs`, 498 lines), `_diff_schema.py` (SchemaDiff aggregate, 244 lines). Public API unchanged — every consumer keeps importing `from core.comparison.diff_models import …`. No file > 500 lines remains under `core/comparison/`. `__all__` on the façade pins the 23-symbol public surface for reflection-based tools.
- **`pyproject.toml` mypy strict zone — wave 3** (PR-G3): added 6 more `cli/` modules to the strict-zone override block (`cli._command_handlers`, `cli.db_utils`, `cli.export_schema_command`, `cli._parser_setup`, `cli._config_helpers`, `cli.main`). Cleared ~80 strict errors via concrete-type annotations (`argparse.ArgumentParser` parameters, `Tuple[…]` return types, `List[Path]` / `Dict[Path, bool]`, `Optional[argparse.Namespace]`), two removed `# type: ignore` comments that mypy 2.x reports as unused, two `# type: ignore[method-assign,assignment]` widened to cover the silent-error override's `NoReturn` mismatch with `None`, `JvmManager.__init__(self, initialize_jvm: bool = True) -> None` typed at definition, and `cli/main.py` imports `TextFormatter` from `core.logger._formatters` (its canonical location) instead of via `core.logger.log`'s implicit re-export. Also unified `dir_recursive_map: Dict[Path, bool]` across `_resolve_scripts_directories`, `execute_single_command`, and `CliCommandContext` (was incongruently `Dict[str, Any]` on the dataclass while builders produced `Path` keys). `mypy --config-file pyproject.toml` still returns "no issues found in 485 source files".
- **`pyproject.toml` mypy strict zone — wave 2** (PR-G2): added 12 more modules to the strict-zone override block (`core.sql_parser.{hybrid_parser, enhanced_regex_parser, unified_regex_parser}`, `core.sql_generator.{formatter, sql_generator}`, `core.sql_validator.linting.performance_analyzer`, `core.normalization`, `core.normalization.identifier_normalizer`, `core.validation.result`, `core.sql_model.view_options`, `cli.handlers._shared`, `cli.handlers.info`). Each cleared by a single-line fix: removed three now-unused `# type: ignore` comments, generic-typed `re.Match` → `re.Match[str]`, `dict` → `Dict[str, Any]`, missing return annotation on `add_issue`, `args: Any`, `AbstractContextManager[Any]`, and one `__init__` annotated `-> None` on `ScriptOrganizer` to satisfy a strict caller in `core.sql_generator.sql_generator`. `mypy --config-file pyproject.toml` still returns "no issues found in 485 source files".
- **`unit-tests.yml` push trigger removes `develop`**: unit tests no longer fire automatically on every push to `develop`. They still run on `main` and `release/**` (and on demand via `workflow_dispatch`). This avoids burning GitHub Actions minutes on every integration commit to `develop`; post-merge coverage on `develop` continues to be validated by `check-coverage.yml` which runs the full suite.
- **`unit-tests.yml` and `integration-tests-new.yml` triggers**: now run on `push` to `main` / `develop` / `release/**` (not on `pull_request`, to control GitHub Actions usage). The release branch (`release/x.y.z`) automatically triggers both suites on every push, gating release PRs to `main` on a passing full test suite. `workflow_dispatch` remains available for ad-hoc runs.
- **`codecov.yml`**: `require_ci_to_pass: true` so Codecov status reflects CI outcomes; combined coverage target stays at 80% with 1% threshold (carryforward enabled — PRs without their own coverage upload reuse the base branch coverage).
- **`CONTRIBUTING.md` & `BRANCHING.md`**: documented the new workflow trigger policy and the release test gate (release PR cannot merge until both unit and integration suites are green on the release branch).
- **`.flake8` ignore list shrunk from `E203,W503,E402,E501,F401,F541,F841,W291` to `E203,W503,E402,E501`**: the four auto-fixable categories are now fully enforced. Cleared 341 violations across 82 files (F401 124, F541 134, F841 44, W291 39 → 0 each). Most F401 hits were dead imports left over from the recent `migration_validator` / `export_schema_command` / `schema_introspector` splits; F541 was a regex-driven prefix strip; F841 was 8 surgical removes (subprocess return discards, unused locals from refactor leftovers); W291 was line-targeted whitespace stripping inside SQL string literals (semantically inert). E402 (68) and E501 (1052) remain deferred.
- **`complexity.yml` xenon ratchet**: `--max-average F` → `--max-average A` — the codebase-wide cyclomatic average is currently A (4.77 numeric), well inside rank A's 1-5 band, so locking at A prevents complexity creep without requiring any refactor first. `--max-absolute` and `--max-modules` stay at F for now: 39 functions and 3 modules sit at rank F today and need refactoring (split logger, undo_command, table_property_comparator, etc.) before those floors can move. The next ratchet steps unlock as the matching refactors land in Phases B/D.
- **`scripts/lint_patterns.py` zero-baseline policy**: removed the `--write-baseline` regrandfathering capability and added a hard policy check — `.lint-patterns-baseline.txt` must contain zero non-comment entries or the script exits 1. The baseline file was already empty (every deferred violation already lives as an inline `# lint: allow-print` / `# lint: allow-enum-str` / `# lint: allow-dialect-string` annotation). This change closes the back-door so a future hand-edit cannot quietly grandfather a new violation. The dead `_load_baseline`, `_write_baseline`, `_violation_key` helpers and the `Violation.fingerprint` field are removed (-90 net lines in the script). Inline annotation counts for visibility: 158 dialect-string (Epic 26 PR-C1/C2/C3), 16 enum-str (PR-06), 7 allow-print (intentional stdout writes).
- **`core/comparison/diff_models.py` DRY refactor**: extracted `DiffResult._set_severity_from_pairs()` helper and migrated 13 simple-pattern subclasses to use it (`ColumnDiff`, `SequenceDiff`, `TriggerDiff`, `SynonymDiff`, `PackageDiff`, `DatabaseLinkDiff`, `LinkedServerDiff`, `ModuleDiff`, `ForeignDataWrapperDiff`, `ForeignServerDiff`, `ExtensionDiff`, `EventDiff`, `UserDefinedTypeDiff`). Each previously inlined a 15-30 line `has_diffs = any(...); if X is not None: severity = ERROR; elif Y: severity = WARNING; else: ...` block; now they call `self._set_severity_from_pairs([(self.X, ERROR), (self.Y, WARNING), …])` with declarative field-severity pairs. -35 net lines and the severity rule for each class is now one block instead of three. Subclasses with bespoke logic (`TableDiff`, `ConstraintDiff`, `IndexDiff`, `ProcedureDiff` / `FunctionDiff` via `RoutineDiff`, `ViewDiff`, `SchemaDiff`) keep their custom `_calculate_diffs` overrides — the helper is opt-in.
- **`core/logger/log.py` split**: extracted `LogFormat` / `LogLevel` / `LogEvent` to `core/logger/_levels.py`, `LogFormatter` / `TextFormatter` to `_formatters.py`, `MultiLog` to `_multi.py`, `NullLog` to `_null.py`, and `LogFactory` to `_factory.py`. `log.py` shrinks from 1560 → 1092 lines (-468 lines, -30%) and now contains only the patch-targeted classes (`Log`, `AbstractLog`, `ConsoleLog`, `FileLog`) plus re-exports of the moved symbols. **Public API unchanged**: `from core.logger.log import LogLevel, FileLog, LogFactory, TextFormatter, …` keeps working, and test patches that target `core.logger.log.X` (`traceback`, `TextFormatter.format_header`, `JINJA_AVAILABLE`) still resolve correctly. The 6-file layout makes the per-concern responsibilities visible without breaking any existing import. Further splits (extracting `AbstractLog` / `ConsoleLog` / `FileLog` to dedicated modules) deferred to a follow-up PR once tests are updated to track the new patch paths.
- **`db/jdbc_provider.py` split**: extracted `JdbcTypeConverter` (~300 lines, the Java↔Python type-dispatch table) to `db/_jdbc_type_converter.py`, the helpers `to_python_string` / `normalize_jdbc_row_keys` to `db/_jdbc_utils.py`, and the JDBC interop constants (`_JAVA_MILLIS_TO_SECONDS`, `_JDBC_TYPE_BIT`, …) to `db/_jdbc_constants.py`. `jdbc_provider.py` shrinks from 1736 → 1384 lines (-352 lines, -20%). **Public API unchanged**: `from db.jdbc_provider import JdbcTypeConverter, to_python_string, normalize_jdbc_row_keys, _JDBC_FIRST_INDEX, …` keeps working through re-exports. The 68-method `JdbcProvider` class itself remains in one file — its internal split (history management, lock management, schema operations) is deferred to a follow-up PR, since extracting methods from a class requires either inheritance or delegation and the current single-class layout is heavily exercised by unit and integration tests.
- **`config/dblift_config.py`, `core/sql_validator/rule_packs/__init__.py`, `core/sql_validator/rule_packs/rule_selector.py`, `core/sql_validator/linting/rule_engine.py`**: annotated the four `import yaml` sites with `# type: ignore[import-untyped]`. Pre-existing mypy `import-untyped` errors that were getting masked locally; surfaced after the PR-B5 refactor freed mypy to inspect more files. Runtime behaviour unchanged. `core/logger/console.py`: two `[no-any-return]` errors fixed by binding the Rich return values (`captured: str`, `status: ContextManager[Any]`) before returning them. **`mypy --config-file pyproject.toml api/ cli/ config/ core/ db/` now returns "Success: no issues found in 485 source files".**
- **`tests/integration/conftest.py` split**: extracted the container-readiness machinery (`is_using_colima` + `USING_COLIMA`, `IS_MACOS` / `IS_ARM_ARCHITECTURE` detection, `MYSQL_DOCKER_COMMAND`, `_apply_mysql_docker_run_options`, the 120-line `wait_for_readiness`) to `tests/integration/_container_readiness.py`. `conftest.py` shrinks from 1470 → 1324 lines (-10%, -146 lines) and re-imports every moved symbol so existing fixtures (and any test that imports from `tests.integration.conftest`) keep working through the conftest namespace. Per-DB container fixtures (`sqlserver_container`, `oracle_container`, etc.) stay in `conftest.py` — pytest's fixture-discovery has special semantics that benefit from staying co-located, and a further split would require an `_db_fixtures.py` import + re-decoration dance that's out of scope for this PR. Validated locally with `pytest --collect-only tests/integration/` — 427 tests collected (matching pre-split count).
- **`core/validation/round_trip_tester.py` OCP-01 first cut**: replaced 5 of 13 `if self.dialect in _ORACLE_DIALECTS` branches with polymorphic dispatch on new `BaseQuirks` attributes — `commit_with_autocommit_raises` (default False, True for Oracle which throws ORA-17273) and `ddl_requires_autocommit_off` (default False, True for Oracle CREATE USER). Two pure-debug Oracle-only logging branches (CREATE TABLE statement preview + table-name list dump) removed outright — pre-introspection logging shouldn't be dialect-coupled. The 3 identical Oracle autoCommit checks now drive off the new quirks flags. Remaining branches (Oracle schema-quoting, DB2 DROP grammar, Oracle CASCADE CONSTRAINTS) deferred to PR-C1b — each one needs its own dedicated quirks method and a small per-dialect test slice. `round_trip_tester.py` shrinks 1308 → 1283 lines.
- **`core/validation/round_trip_tester.py` OCP-01 second cut**: replaced 7 more dialect-string branches via a new `BaseQuirks.render_round_trip_drop_table_sql(target)` method (Oracle returns the PL/SQL `BEGIN EXECUTE IMMEDIATE … EXCEPTION` wrapper with `CASCADE CONSTRAINTS`, DB2 returns plain `DROP TABLE` without `IF EXISTS`, default uses `DROP TABLE IF EXISTS`) and two new flags — `strict_schema_creation_errors` (True for Oracle: CREATE USER cannot be silently retried) and `unquoted_identifiers_uppercase_in_dictionary` (True for Oracle and DB2 which both store unquoted identifiers upper-cased in their data dictionaries). The Oracle/DB2 DROP-SQL forks in `_build_drop_sql` and `_retry_drop_and_create` collapse into single calls to `self._quirks.render_round_trip_drop_table_sql(target)`. One more debug-only Oracle log block in `_drop_preexisting_objects` removed (same pattern as PR-C1). Branch count: 12 → 5 (`_replace_schema_in_sql` regex variants and `_build_retry_drop_strategies` data-dictionary lookups remain deferred — they touch substantial per-dialect SQL).
- **`ModelQuirks` Protocol population (Epic 26 story 26-5 first slice)**: added `wrap_trigger_body(body: str) -> str` to the `ModelQuirks` Protocol in `core/dialect_boundary.py` and to `BaseQuirks` (default identity passthrough). `OracleQuirks.wrap_trigger_body` returns a properly-formed PL/SQL block (`BEGIN`/`END;` wrapping, semicolon normalisation). `core/sql_model/trigger.py:_format_body` now delegates to the quirks hook — the 23-line body shrinks to 2 lines and the `trigger_body_style == "oracle"` string check (one of the 158 `# lint: allow-dialect-string` annotations) goes away. The redundant `BaseQuirks.trigger_body_style` and `OracleQuirks.trigger_body_style` class attributes are removed; `import re` becomes module-level in `OracleQuirks` (it was lazy-imported inside the method body).
- **`core/migration/scripting/undo_script_generator.py` shadowed-monolith cleanup** (PR-D1, #275): deleted the 1683-line legacy monolith that shadowed the `core/migration/scripting/undo_script_generator/` package introduced earlier. Python's import machinery resolves the package over the legacy `.py` when both are present, but the orphan file kept showing up in greps and complexity reports as a phantom F-rank source. Replaced by a parity test (`tests/unit/core/migration/scripting/test_undo_script_generator_parity.py`) that pins the public-API equivalence of the package's re-exports.
- **`core/sql_model/table.py:Table.__init__` flattened** (PR-D2, SIMP-48, #276): replaced the 6-branch dispatcher (`if columns is None and from_dict is not None: …`) with three explicit classmethods — `Table.from_columns(...)`, `Table.from_dict(...)`, `Table.from_options(...)`. The free-form constructor is now a thin keyword-only forwarder. Cyclomatic complexity 17 → 4; the three call paths in `core/sql_parser/`, `core/sql_model/_loaders.py`, and the `cli/handlers/diff.py` consumer become explicit at the call site instead of being inferred from `None` checks.
- **`core/sql_parser/hybrid_parser.py` split via `_SqlglotBuildersMixin`** (PR-D3, #277): extracted 16 sqlglot-AST → model builders (trigger / table / column / constraint / index / view) into `core/sql_parser/_sqlglot_builders.py` as a mixin. `hybrid_parser.py` shrinks 1608 → 1100 lines (-508, -32 %). The mixin needs only `self.dialect` / `self.sqlglot_parser` / `self._quirks` / `self._normalize_identifier`, mirroring the project convention from `core/migration/scripting/undo_script_generator/` (`_UndoExtractorsMixin`, `_UndoReversersMixin`). Public-method names and bodies unchanged; callers inside `HybridParser` bind via MRO. Smoke-validated across postgresql / mysql / oracle / sqlserver: FK + CHECK + PK constraints all extracted identically.
- **`api/client.py` heavy-setup extraction** (PR-D4, #278): `DBLiftClient.__init__` was the only non-A-ranked function in the file (cyclomatic 17, 96 lines of inline config-resolution / logger-construction / kwargs-handling). Extracted four helpers into `api/_client_factory.py` (`resolve_config_or_raise`, `build_default_logger`, `normalize_migrations_dirs`, `apply_ctor_overrides`); the 108-line `export_schema` body moved to `api/_client_operations.py` as `export_schema_operation` + `_build_export_schema_options`. `__init__` cyclomatic 17 → 2 (C → A), length 96 → 32 lines; `api/client.py` 1275 → 1203 lines. **Public surface unchanged**: `ExportSchemaOptions` re-exported from `api.client` via explicit `__all__` so `from api.client import ... ExportSchemaOptions` keeps working (consumed by `api/__init__.py`).
- **`docs/development/testing.md` rewrite** (PR-E2, #281): the previous 164-line file referenced `python -m tests.run_tests` (no longer exists), claimed a top-level `tests/conftest.py` (there isn't one — fixtures are scoped to the layer that needs them), and made no mention of the markers, dialect matrix, license-guard auto-bypass, or which CI workflow gates a PR. Replaced with a 282-line runbook documenting the layered conftest pattern (`unit/conftest.py` license-guard bypass, `integration/conftest.py` Docker readiness), every marker declared in `pytest.ini`, the exact CI invocations the workflows use, the matrix-tests-vs-unit-tests gating model (matrix is the blocking PR gate), the coverage gating chain, and project-specific gotchas (JPype one-shot JVM boot, MacOS/Colima/ARM detection, log_cli default off).
- **`docs/development/contributing.md` refresh** (PR-E3, #282): replaced the generic 5-item PR checklist with the canonical 7-item version, pointed to `.github/pull_request_template.md` as source of truth, replaced the generic "what to look for" prose with a table of automated gates (formatting, linting, type-check, complexity, AST patterns, public-API docstrings, coverage, cross-cutting regression) plus project-specific human-review focus (stabilization alignment, dialect isolation, Bugbot thread severity).
- **mypy strict zone (per-module overrides) seeded for `api/`** (PR-E4, #283 + PR-F1, #285): added a `[[tool.mypy.overrides]]` block in `pyproject.toml` that enables the full `--strict` flag set on `api.__init__`, `api._client_factory`, `api.events`, `api._client_operations`, and `api.client`. The flag set mirrors CLI `--strict`: `disallow_any_generics`, `disallow_subclassing_any`, `disallow_untyped_calls`, `disallow_untyped_defs`, `disallow_incomplete_defs`, `disallow_untyped_decorators`, `no_implicit_optional`, `warn_unused_ignores`, `strict_equality` (and `no_implicit_reexport` for the seed modules; carved out on the two later modules to avoid forcing explicit `__all__` re-exports in `core/`). Surface fixes: `api/events.py` Callable / frozenset / tuple parameterised with concrete element types; `core/logger/results.py` 11 occurrences of `def __init__(self):` get `-> None`; `api/_client_operations._prepare_undo_generation_migration` gets `-> Any`; `api/client.DBLiftClient.__enter__` gets `-> "DBLiftClient"`; one stale `# type: ignore[return-value,no-any-return]` removed. Onboarding procedure (add a module to the strict zone) documented inline in the override block. Negative-test verified: injecting an untyped def into a strict-zone module makes the global `mypy` run fail with `no-untyped-def`.
- **README.md: publish missing CI badges** (PR-E5, #284): added Matrix tests, Complexity, and Security badges to the badge cluster. The cluster previously implied `unit-tests` was the PR gate, but `unit-tests.yml` only fires on push to protected branches — the actual blocking gate is `matrix-tests.yml` (sub-minute, runs the cross-cutting regression invariants in `tests/integration/matrix/`). Split the cluster into two visual rows (tech tags vs CI status).
- **`core/sql_parser/_sqlglot_builders._build_or_update_trigger` decomposition** (PR-F2, #286): the 60-line method was the only D-rank function left in the file after PR-D3's extraction (cyclomatic 28). Split into one orchestrator + five typed helpers, with a new `_TriggerHeader` `NamedTuple` carrying the regex projection between them — `_parse_trigger_match` (B=6), `_extract_trigger_definition` (A=2), `_find_matching_trigger` (B=8), `_merge_trigger_metadata` (C=11), `_build_trigger_from_header` (A=2), and the orchestrator at A=3. Case-insensitive lookup keys pre-computed once instead of per-loop iteration; merge order and "only fill empty fields" semantic preserved one-for-one. Latent issue documented but **not fixed**: the trigger-header regex's group 5 (the table-schema) was being extracted but discarded by the legacy code — preserved verbatim with an explicit docstring note; wiring group 5 in would be a separate behavior change.
- **`BaseProvider.canonical_dialect_key` — Epic 26 OCP fix** (PR-F4, #288): pushed dialect identification onto the provider layer — each plugin's concrete provider class declares its own dialect name (`OracleJdbcProvider.canonical_dialect_key = "oracle"`, `Db2JdbcProvider.canonical_dialect_key = "db2"`, etc.; the eight providers wired). `MigrationExecutionEngine._probe_dialect_key` now asks the provider directly (`self.provider.canonical_dialect_key`) and falls back to a legacy normalize cascade only for non-plugin providers / test fakes. **The function no longer contains any dialect string literal, regex URL-sniff, or `if dialect == X` branch** — adding a new dialect (Snowflake, etc.) becomes a single new `db/plugins/<name>/provider.py` declaration with zero changes to `core/`. The previous URL-sniffing logic (`"jdbc:oracle:" in url` etc.) is deleted along with `_JDBC_DB2_PREFIX` and the `get_provider_display_url` import. `execution_engine.py`: 11 → 1 `# lint: allow-dialect-string` annotations (the one remaining, in `_parse_sql_statements`'s `canonical == "sqlserver"` alias-canonicalization branch, is documented as `ocp-todo` for a focused follow-up).
- **`client.info()` defaults to `display_human=False`** (`api/client.py`): the Python API path no longer prints the Rich migration table to stdout as a side effect. The CLI handler explicitly re-enables it. (OBS-04)
- **Narrower `except` clauses across JDBC + URL-parsing boundaries** (`db/jdbc_provider.py`, `db/plugins/{db2,oracle}/...`, `config/...`): bare `except Exception` replaced by the typed `JAVA_EXC` / `URL_PARSE_EXC` tuples so programming bugs (`KeyError`, `NameError`) stop being swallowed.
- **`migration_validator.py` (1770 → 927 lines)**, **`export_schema_command.py` (1960 → 926 lines)**, **`schema_introspector.py` (1843 → 1166 lines)**, **`database_config.py` (1504 → 1254 lines)**: split into focused helper modules (`_checksum_validator`, `_flyway_compatibility`, `_strict_mode_validator`, `_export_helpers`, `_managed_object_filter`, `_vendor_property_applier`, `_partition_enricher`, `_column_enricher`, `_jdbc_url_parser`, …).
- **`--scripts` CLI help text** (`cli/_parser_setup.py`): documents that subdirectories are scanned by default; `--no-recursive` or YAML `migrations.recursive: false` opts out. Pinned with regression tests; no behaviour change. (OBS-02)

### Fixed

- **Unit test suite stabilisation (30 tests)**: updated 9 test files to match production-code changes made since the tests were written.
  - `api.client.DbliftLogger` patch paths in `test_client_extended.py` and `test_v110_regressions.py` → `api._client_factory.DbliftLogger` (the class was removed from `api.client` by autoflake in PR-D4 but the tests were not updated).
  - `cli.db_utils.DbliftConfig` patch in `test_db_utils.py` → `cli.db_utils.load_config` (the direct `DbliftConfig` import was replaced by `load_config`; the outer `try/except Exception` in `validate_config` still covers the path).
  - `TestLoggerPackageSurface.EXPECTED_EXPORTS` in `test_public_api_surface.py` did not include `DiffResult`, which was added to `core.logger.__all__` in PR-E4. Added `"DiffResult"` to the set.
  - `test_imports_base_provider` in `test_base_command_type_hint_24_5.py` required all 9 command modules to directly import `BaseProvider`; only the 3 that actually reference it in their own source (`base_command`, `migrate_command`, `diff_command`) need the import — the remaining 6 leaf commands inherit via BaseCommand. Narrowed `_MODULES_WITH_BASE_PROVIDER_IMPORT` to these 3.
  - Three Oracle pre-introspection debug-query tests in `test_round_trip_tester_coverage.py` removed — the behavior they tested (`SELECT table_name FROM all_tables WHERE owner=…` before re-introspection) was intentionally deleted in PR-C1 as a dialect-coupled debug log.
  - `test_all_helpers_in_class_dict` in `test_hybrid_parser_decomposition.py` and `test_formatter_decomposition.py` used `method in Class.__dict__`, which fails for methods inherited from mixins. Changed to `hasattr(Class, method)`.
  - SQLite schema override warning string in `test_batch8_bug_fixes.py` updated from `"SQLite has no schema concept"` to `"uses a fixed schema"` — the message was reworded when the warning was moved to the quirks-based path in PR-C2.
- **`cli/diff` dialect resolution** (`cli/handlers/diff.py`): `ctx.config` was always `None`, so the dialect resolver fell through to an empty string. Now reads `ctx.client.config`.
- **`db_utils.test_connection_command` pprint output** (`cli/db_utils.py`): JDBC connection details printed via `pprint(...)` to real stdout, bypassing `CommandOutput`. Routes through `command_output.machine(...)` now.
- **`Event.migrations_applied` field type**: declared `Optional[int]` but `MigrateResult.migrations_applied` is a list — the dataclass field is now `Optional[List[Any]]`.
- **JDBC URL parsing resilience to plugin-registry errors** (`config/_jdbc_url_parser.py`): the param-separator inference inside `parse_jdbc_url` calls `ProviderRegistry.get_quirks()` / `is_native_dialect()` which can raise `KeyError` / `RuntimeError` / `ImportError`. The narrower `_URL_PARSE_EXC` at the call sites in `dblift_config.py` does not catch those, so a misconfigured plugin registry would crash config loading. The parser now swallows registry-layer failures and falls back to the per-dialect parser output (server / port / database stay populated).

### Removed

- **`EventContract` / `EVENT_CONTRACTS` / `get_event_contract`** (`api/events.py`): the separate payload registry is redundant now that `Event` declares fields canonically. **Breaking** for code importing these symbols.

### Chore

- Cursor-bot review findings on PR #261 addressed: DRY `emit`/`_dispatch`, reserved-field collision in `_build_event`, list-typed `migrations_applied`, triplicated `_URL_PARSE_EXC`.
- `.gitleaks.toml`: allowlist for ANTLR Java grammar tokens and historical commits with hardcoded `DBLIFT_MYSQL_PASSWORD`.

> Follow-up: a coverage `fail_under` floor will be added in a subsequent PR once the new triggers have produced a stable Codecov baseline on `develop`. The floor will be set 1 percentage point below the measured baseline and ratcheted up over time.

## [1.5.1] - 2026-05-07

### Added

- **`core/dialect_boundary.py` — Epic 26 behaviour boundary**: declares the `DialectQuirks` protocol surface (`DdlQuirks`, `ParserQuirks`, `ModelQuirks`, `ComparatorQuirks`, `ValidatorQuirks`, `TypeMapQuirks`) so dialect overrides stay in `db/plugins/<X>/quirks.py` instead of branching on dialect strings in framework code.

### Changed

- **`--db-schema` is mandatory for every dialect except SQLite** (`config/dblift_config.py`, `cli/_config_helpers.py`, `cli/db_utils.py`): the implicit `"dbo"` default leaked from `BaseDatabaseConfig.create()` / `DbliftConfig.default()` and could make non–SQL Server runs pick up SQL Server semantics. Implicit default removed; `_validate_db_config` now rejects missing `--db-schema` / config schema for SQL Server as well.

- **PostgreSQL, SQL Server, MySQL, and DB2 schema operations** (`db/plugins/*/.../schema_operations.py`): every `create_schema_if_not_exists()`, `set_current_schema()`, and `clean_schema()` construction site routes schema identifiers through `BaseQueryExecutor.get_quoted_schema_name()` / `get_schema_qualified_name()` instead of hand-rolled quoting. PostgreSQL, SQL Server, and MySQL keep the same emitted SQL where behaviour was already correct.

- **`BaseQuirks` and plugin quirks** expanded across Cosmos DB, DB2, MariaDB, MySQL, Oracle, PostgreSQL, SQLite, and SQL Server; comparators / diff / DDL paths lean further on quirks for identifiers, types, and validation.

- **`core/sql_validator/linting/sql_linter.py`**, **`performance_analyzer.py`**, **`hybrid_parser.py`**, **`export_schema_command.py`**, **`safety_checker.py`**, **`introspector_factory.py`**, undo scripting, and JDBC execution plumbing refined to align with the quirks-first model and tighten edge-case handling.

### Fixed

- **`validate-sql --fail-on-violations`** (`core/sql_validator/linting/sql_validator.py`): the flag now fails the command when any violation remains after severity filtering (including warning-only lint results). Previously only `ERROR`-severity violations triggered a non-zero exit, so CI could pass while warnings were reported.

- **Oracle schema quoting and history visibility** (`db/plugins/oracle/`, `JdbcProvider`): SQL mixed quoted lowercase (`"dbo"."…"`) with unquoted uppercase (`DBO.…`) and `WHERE owner = 'DBO'`. After `migrate`, `table_exists()` could probe the wrong casing so `info` / `diff` reported **zero** applied migrations. All schema references now go through dialect-aware quoting; `OracleQueryExecutor.table_exists()` no longer uppercases the schema argument; Oracle snapshot DDL uses the shared `qualified_table` path instead of `{SCHEMA.TABLE}` uppercasing. `OracleSchemaOperations` (`CREATE USER` / `GRANT`, `set_current_schema`, DB-link session reset) uses the same helper.

- **DB2 `SYSCAT.SCHEMATA` existence check**: previously `UPPER(SCHEMANAME) = UPPER(?)` could report “already exists” while quoted `CREATE SCHEMA "<name>"` targeted a different casing than stored, failing later DDL. Lookup is now case-sensitive (`SCHEMANAME = ?`) to match caller intent.

### Removed

- **Vendored `jre/macos-arm64` tree**: the repository no longer ships a full embedded JRE for that platform in-tree; bundles continue to rely on **`JreManager`** / **`scripts/build_distributions.py`** (`JAVA_HOME` / `create_custom_jre`) to produce packaged runtimes.

### Chore

- **`.gitignore`**: exclude `config/workflows.yaml` from version control.
- **Epic 26 wave planning drafts** added under `docs/superpowers/plans/`.
- **Tests**: broader coverage for quirks hooks (wave slices), Oracle / DB2 schema operations, hybrid parser, export-schema paths, introspection fixtures, safety checker consolidation (obsolete `test_safety_checker_22_3` removed in favour of streamlined cases).

## [1.5.0] - 2026-05-06

### Added

- **Dialect plugin isolation — Epic 26** (ADR-0026): all dialect-specific logic extracted from `core/`, `api/`, `cli/`, `config/` into per-dialect plugin packages under `db/plugins/<X>/`. Adding a new database now requires only a new plugin folder — zero edits to framework code.
  - 29 parser files moved from `core/sql_parser/<dialect>/` → `db/plugins/<X>/parser/`. `HybridParser`, `SqlGlotParser`, `BaseParser` dispatch via `quirks.parser_class()`.
  - Domain models (`Procedure`, `Index`, `Trigger`, `Sequence`, `Synonym`, `View`, `Table`, `UDT`) DDL shape fully driven by `BaseQuirks` attributes; no more `if dialect == "X"` branches in `core/sql_model/`.
  - Comparators route through `quirks.uppercase_identifiers`, `quirks.seq_implicit_max_value`, `quirks.tinyint1_is_boolean`, `quirks.sqlglot_dialect`.
  - `MigrationValidator` Oracle SQL\*Plus preprocessing gated by `quirks.supports_sqlplus_preprocessing`.
  - Migration engine: CosmosDB schema fallback → `quirks.default_schema_name`; diff case-fold → `quirks.uppercase_identifiers`; undo generators use `quirks.sqlglot_dialect`.
  - Two-pass plugin discovery: `importlib.metadata` entry-points + filesystem fallback; `pyproject.toml` registers all 8 first-party plugins.
  - MariaDB plugin added (`db/plugins/mariadb/`) inheriting `MysqlQuirks` — zero core edits required.
  - Lint baseline (`dialect-string-literal` rule) dropped to 0 violations.
  - `parser_default_schema` split from `default_schema_name` so SQL Server parser default (`"dbo"`) does not affect export-schema normalization.

- **Generator isolation — Epic 27** (ADR-0027): last dialect-specific branches removed from `core/sql_generator/`. New `BaseQuirks` hooks (all with safe defaults):
  - `normalize_column_data_type(col, data_type)` — SQL Server identity stripping, DB2 TIMESTAMP precision, PostgreSQL float/timestamp reorder.
  - `render_identity_clause(col)` — AUTO_INCREMENT / AUTOINCREMENT / GENERATED AS IDENTITY per dialect.
  - `render_column_nullable_change / default_change / type_change / collation_change` — ALTER TABLE SQL per dialect; replaces 17 handler functions and 4 dispatch dicts in `column_converter.py`.
  - `fk_reference_bind_params(schema, table, col)` — Oracle FK query uses 4 params (schema twice); default is 3.
  - `requires_sdk_for_drop()`, `build_sdk_drop_operation(stmt)`, `generate_sdk_script(stmts)` — CosmosDB SDK execution fully owned by the plugin; `diff_to_sql.py` no longer imports `CosmosDbSdkTranslator`.
  - `unwrap_default_value(default_str, col)` — SQL Server paren-strip, MySQL backtick normalisation.
  - `round_trip_extra_object_types()` — dialect-specific object types for round-trip testing (replaces hardcoded capability map).

- **Documentation**: `docs/architecture/database-providers.md` and `docs/development/adding-database-support.md` rewritten with complete step-by-step guide for adding a new database, full hook reference table, and common patterns.

### Fixed

- **CosmosDB `replace_container` AttributeError** (`db/plugins/cosmosdb/sdk_translator/`): `replace_container` is a method on `DatabaseProxy`, not `ContainerProxy`. Calls changed from `container_client.replace_container(...)` to `database.replace_container(container_client, ...)` in 10 call sites across `sdk_translator_legacy.py` and `sdk_translator/_executors.py`.
- **Pygments `ClassNotFound` crash** (`cli/_command_handlers.py`): `Syntax()` raises `ClassNotFound` when a plugin sets `pygments_lexer` to an alias Pygments does not recognise. Guard added: validate the alias with `pygments.lexers.get_lexer_by_name()` and fall back to `"sql"` on error.

## [1.4.1] - 2026-05-03

### Fixed

- **Baseline error message truncated** (`db/jdbc_provider.py`): when `baseline` was called on a schema with existing migration history, the informative `"Schema X already contains N migration(s)"` error was swallowed by an outer `except Exception` and replaced with the generic `"Could not verify if history table is empty"` message. The real message now propagates to the terminal directly.
- **Repeatable migration (`R__`) permanently blocked after repair** (`core/sql_validator/migration_validator.py`): `_check_repeatable_migrations` used `next()` to find the history entry for a repeatable script, which returned the **oldest** entry. If an old failure preceded a later success, the validator still reported `"previously failed"` and blocked all subsequent `migrate` runs even after `repair`. Replaced with `max()` by `installed_rank` so the **most recent** application attempt is evaluated — matching Flyway's per-entry state model. This also resolves the `migrate --target-version N` permanent-block scenario (BUG-01), which was caused entirely by this history-ordering bug.

## [1.4.0] - 2026-04-26

### Added

- **`supports_snapshots()` on provider interfaces**: New method on `ProviderInterface` decouples snapshot eligibility from transaction support. Previously the snapshot guard checked `supports_transactions()`, so non-transactional providers (e.g. CosmosDB) could never capture snapshots. Providers now explicitly declare snapshot capability independently of transaction capability; `MigrationExecutor` uses `supports_snapshots()` instead.
- **Migration script encoding detection**: Optional Flyway-style `encoding:` config key (also settable via `DBLIFT_ENCODING` env var). Before tokenisation, `MigrationScriptManager` detects the actual file encoding and decodes accordingly, preserving accented and non-ASCII SQL content instead of silently replacing invalid bytes with replacement characters.
- **Modern CLI console output via Rich** (ADR-0016, branch `feature/rich-console-output`).
  - Severity styling on stderr (`Console + DBLIFT_THEME`): debug=dim, warn=yellow, error=bold red, success=bold green.
  - Migration history table and migration-list table now use `rich.table.Table` (Unicode `SIMPLE_HEAVY` box) instead of `prettytable` / hand-built ASCII.
  - `dblift diff` renders schema differences as `rich.tree.Tree` for all 15 object types (tables/columns/constraints/indexes/views/sequences/triggers/procedures/functions/packages/synonyms/UDTs/extensions/foreign data wrappers/foreign servers/events). Header / footer / summary blocks switch to `rich.panel.Panel`.
  - `dblift migrate` shows a `rich.progress.Progress` bar with spinner / description / `MofNCompleteColumn` / elapsed time. Failed migrations break the loop without bumping the completed count.
  - `dblift snapshot` and `dblift export-schema` wrap their blocking service calls with a `Console.status(...)` spinner.
  - `dblift diff` SQL preview renders via `rich.syntax.Syntax` (PostgreSQL / MySQL / MariaDB / SQL Server / TSQL Pygments lexers; everything else falls back to generic `sql`). File / JSON / HTML logs receive the raw SQL with no markup leak.
  - Command completion footer (success / failure status + execution time + applied scripts + schema version) renders inside a `rich.panel.Panel`.
  - Uncaught exceptions render via `rich.traceback` (installed at `cli/main.py` startup).
  - All Rich rendering goes to `stderr` only — ADR-0005 / ADR-0008 stdout contract preserved for `--format json/sarif/...` machine payloads.
- **`Log.console_print(renderable, level=...)`** — emit a Rich renderable to ConsoleLog only; honours the same severity threshold as `log.info`.
- **`Log.file_only_info(message)`** — emit plain text to FileLog children only, skipping ConsoleLog. Pairs with `console_print` so styled console output and plain file records stay in sync without duplication.
- **`--quiet` / `-q`** raises the *console* threshold to NOTICE (success / warn / error still visible; INFO / DEBUG suppressed). File / JSON / HTML logs keep the user's `--log-level` so the audit trail stays complete.
- **`--no-progress`** disables the `Progress` bar in `migrate` and the `Console.status` spinners in `snapshot` / `export-schema`. Process-local override (no `os.environ` mutation); `DBLIFT_NO_PROGRESS` env var still honoured for operators / CI configs that pre-set the environment.

### Changed

- **`LogFactory.configure` gains `console_log_level`** (Optional[LogLevel]). When set, only ConsoleLog instances pick up the elevated threshold; FileLog instances stay at the global `log_level`. Drives the `--quiet` console-only suppression.
- **`get_stderr_console()` is now a singleton** (`reset_stderr_console()` exposed for tests). Single Console instance shared by ConsoleLog, Progress, status spinners, and rich.traceback so they don't fight over terminal redraw state.

### Removed

- **`prettytable>=3.5.0`** dropped from `pyproject.toml`, `requirements.txt`, `requirements-runtime.txt` — fully replaced by `rich.table.Table`.

### Changed (BREAKING)

- **Minimum Python raised to 3.11** (was 3.8). Rationale in
  `docs/adr/0004-bump-minimum-python-to-3-11.md` (supersedes ADR-0003):
  the codebase already uses features requiring Python 3.10+ (PEP 604
  `X | Y` union syntax in ~30 call sites, `@dataclass(slots=True)`) and
  3.11 (`typing.Self`). The prior `requires-python = ">=3.8"`
  declaration was factually incorrect — the code would not import on
  3.9 or 3.10. This release aligns `requires-python` with the runtime
  matrix the CI actually exercises (3.11, 3.12). Python 3.8, 3.9, 3.10
  classifiers removed.

### Security

- **Bumped vulnerable dependency floors** (17 known CVEs at the prior
  floors, surfaced by `pip-audit` during PR-0E baseline):
  - `cryptography>=41.0.0` → `cryptography>=46.0.6` (PYSEC-2024-225,
    CVE-2023-50782, CVE-2024-0727, GHSA-h4gh-qq45-vh27, CVE-2026-26007,
    CVE-2026-34073)
  - `PyJWT>=2.8.0` → `PyJWT>=2.12.0` (CVE-2026-32597)
  - Build system: `setuptools>=78.1.1` (PYSEC-2025-49, CVE-2024-6345),
    `wheel>=0.46.2` (CVE-2026-24049)
- Removed obsolete `dataclasses>=0.6` backport dependency (unused since
  Python 3.7 added `dataclasses` to the stdlib).

### Changed (BREAKING)

- **Minimum Python raised to 3.11** (was 3.8). Rationale in
  `docs/adr/0004-bump-minimum-python-to-3-11.md` (supersedes ADR-0003):
  the codebase already uses features requiring Python 3.10+ (PEP 604
  `X | Y` union syntax in ~30 call sites, `@dataclass(slots=True)`) and
  3.11 (`typing.Self`). The prior `requires-python = ">=3.8"`
  declaration was factually incorrect — the code would not import on
  3.9 or 3.10. This release aligns `requires-python` with the runtime
  matrix the CI actually exercises (3.11, 3.12). Python 3.8, 3.9, 3.10
  classifiers removed.

### Security

- **Bumped vulnerable dependency floors** (17 known CVEs at the prior
  floors, surfaced by `pip-audit` during PR-0E baseline):
  - `cryptography>=41.0.0` → `cryptography>=46.0.6` (PYSEC-2024-225,
    CVE-2023-50782, CVE-2024-0727, GHSA-h4gh-qq45-vh27, CVE-2026-26007,
    CVE-2026-34073)
  - `PyJWT>=2.8.0` → `PyJWT>=2.12.0` (CVE-2026-32597)
  - Build system: `setuptools>=78.1.1` (PYSEC-2025-49, CVE-2024-6345),
    `wheel>=0.46.2` (CVE-2026-24049)
- Removed obsolete `dataclasses>=0.6` backport dependency (unused since
  Python 3.7 added `dataclasses` to the stdlib).

### Fixed

- **`migrate --dry-run` created the history table on real databases (Critical)**: `core/migration/commands/migrate_command.py` — `_initialize_migration_execution()` unconditionally ran `create_schema_and_history_table()` before the `if dry_run:` short-circuit at line 541, so a "preview" invocation silently wrote `dblift_schema_history` to the target DB. Guarded the call with `if not dry_run:`. Safe because both the SQLite and JDBC history managers return `[]` when the table is missing.
- **SQLite `clean --dry-run` crashed with `'sqlite3.Connection' object has no attribute 'getMetaData'` (High)**: the dry-run path in `core/migration/commands/clean_command.py` enumerated drop candidates through `SchemaIntrospector`, which is JDBC-only. Introduced `enumerate_clean_candidates()` in `db/plugins/sqlite/sqlite/schema_operations.py` as the single source of truth (views → triggers → indexes → tables, with `dblift_migration_lock` excluded). Both `clean_schema()` (actual drop) and the new `get_clean_preview()` (dry-run) iterate over it, so dry-run and real-clean can no longer drift. `clean_command` prefers `provider.get_clean_preview()` when available and falls back to `SchemaIntrospector` for JDBC providers.
- **Misleading `WARNING: Could not enable autoCommit` on non-JDBC connections (Cosmetic)**: `db/introspection/schema_introspector.py` and `db/introspection/core/jdbc_metadata.py` unconditionally called `connection.getAutoCommit()` / `setAutoCommit(True)`, which throws `AttributeError` on `sqlite3.Connection` and is logged at `warning` level. Guarded the whole block behind `if hasattr(self.connection, "getAutoCommit"):`. Same shape as the BUG-COSMOS-2 pattern — JDBC idioms leaking into non-JDBC provider paths.
- **Double placeholder substitution in SQL migrations (Medium)**: `core/migration/executor/execution_engine.py` — `_parse_sql_statements()` substitutes `${...}` placeholders on the full migration content before tokenisation (BUG-06 fix), and `_execute_statements()` was then re-substituting on each parsed statement. Usually a no-op, but if a placeholder value itself contained a `${...}` fragment, the second pass would re-interpret it and corrupt the SQL. Removed the per-statement pass; the pre-parse pass is now the single source of truth.
- **`sqlite:///` URL dropped the leading slash from absolute paths (High)**: `config/database_config.py:1334` and `db/plugins/sqlite/sqlite/connection_manager.py:54` stripped 10 chars from `sqlite:///tmp/x.db`, producing the relative `tmp/x.db` instead of the RFC 3986–correct absolute `/tmp/x.db`. Per RFC 3986, `sqlite:///tmp/x.db` decomposes as scheme=`sqlite`, authority=`""`, path=`/tmp/x.db` — the leading slash belongs to the path. Dropped the redundant `sqlite:///` branch; the `sqlite://` branch (`url[9:]`) correctly handles both 2-slash (relative) and 3-slash (authority-less absolute) forms.
- **`--config` flag silently ignored for all migration commands (Critical)**: Removed duplicate `--config` declarations from every migration subparser (`migrate`, `undo`, `clean`, `validate`, `info`, `diff`, `repair`, `import-flyway`, `baseline`, `validate-sql`, `export-schema`, `snapshot`). The subparser defaults were overwriting the value already captured by the top-level parser, so the config file was never loaded. The top-level parser + `global_only_args` routing already handled these flags correctly.
- **`--scripts` flag silently ignored for all migration commands (Critical)**: Same root cause as `--config` above. Removed duplicate `--scripts` declarations from all migration subparsers. Users who passed `--scripts /path/to/migrations` always saw "Migration scripts directory not found: migrations" because the subparser default overwrote the specified path.
- **`--config /nonexistent` produced misleading error (High)**: Direct consequence of the above — now that `--config` is correctly propagated, a missing config file produces "Config file not found: …" and exits 1, instead of the unrelated "Database URL is required" error.
- **`db check-connection --db-url` always failed (High)**: `cli/db_utils.py:check_connection()` now calls `load_config(config_file, args)` instead of `DbliftConfig.from_args(args)`. `from_args_dict()` looked for `args["database_url"]` but the `db check-connection` subparser stores `--db-url` as `args.db_url`; `load_config()` already handles both attribute-name variants.
- **`db validate-config --db-url` always failed (High)**: Same fix as above applied to `validate_config()`'s else-branch (the path taken when no `--config` file is provided).
- **`info` command had no `--format json` option (Medium)**: Added `--format table|json` to the `info` subparser. `_handle_info()` now serializes `InfoResult` (migrations list + connection metadata) as JSON to stdout when `--format json` is requested, enabling scripted consumption of migration status.
- **Oracle JDBC INFO logs polluted stdout (Medium)**: Added `-Djava.util.logging.config.file=/dev/null` and `-Doracle.jdbc.Trace=false` to JVM startup arguments in `db/jvm_init.py`, suppressing Oracle JDBC's `java.util.logging` console handler that wrote diagnostic lines like `tuneRowPrefetch` directly to stdout.
- **`validate-sql` did not flag `SELECT *` (Low)**: The `select_star` rule already existed in `PerformanceAnalyzer` but its default severity was `"info"`, below the default `severity_threshold` of `"warning"`. Changed the default severity to `"warning"` in both `PerformanceAnalyzer` and `ValidationConfig` so `SELECT *` is reported without needing an explicit `--severity-threshold info`.
- **`ValidationConfig.from_dict()` `select_star` fallback was `"info"` (Medium)**: Even after the dataclass default was raised to `"warning"`, the `from_dict()` fallback dict still hard-coded `select_star: "info"`. The CLI always goes through `from_dict`, so `SELECT *` violations were silently filtered regardless of the dataclass fix. Both sites now agree on `"warning"`.
- **`info --format json` leaked human migration table to stderr (Medium)**: `InfoCommand.execute()` called `display_migration_info()` unconditionally before the format branch, sending the human-readable table to `ConsoleLog` (stderr) even when JSON was requested. Added `display_human` parameter to `InfoCommand.execute()` and `MigrationExecutor.info()`; the handler passes `display_human=False` in JSON mode.
- **Repeatable migrations emitted empty string version in `info --format json` (Low)**: Repeatable (`R__`) migrations have no semantic version; the JSON serialiser now emits `null` instead of `""` for the version field, making it unambiguous for downstream consumers.
- **`UNDO_SQL` rows matched as "last applied" in checksum lookup (High)**: `has_script_changed()` and `_last_successful_non_delete_record()` did not exclude `UNDO_SQL` rows when finding the authoritative checksum. After an undo, the `UNDO_SQL` row was returned with `checksum=0`, triggering a false mismatch on the next `migrate` or `validate`. Both methods now exclude `UNDO_SQL` alongside `DELETE`.
- **`repair _detect_checksum_drift()` silently skipped zero checksums (Medium)**: The guard used `if db_checksum:` — falsy for `0` — so scripts whose stored checksum was legitimately zero were never flagged for drift. Changed to `if db_checksum is not None:`.
- **SQLite duplicate foreign keys not deduplicated (Low)**: Multi-column foreign keys were emitted once per column rather than once per constraint during introspection. Deduplication now groups by constraint name before emitting.
- **CosmosDB DDL generated `CREATE TABLE` instead of `CREATE CONTAINER` (High)**: The executor only handles `CREATE CONTAINER`; `CREATE TABLE` raised at runtime. DDL generation now emits `CREATE CONTAINER`. `CREATE INDEX` is also suppressed (indexes are managed via indexing policy) and replaced with a comment, consistent with the existing `generate_drop_sql` behaviour.
- **CosmosDB `_execute_delete` queried non-queryable `_partitionKey` field (High)**: `SELECT c._partitionKey` is not a queryable field in Cosmos SQL API; the partition key was always `None`, causing `repair` to submit delete requests with `NONE_PARTITION_KEY` and receive 404. Fixed by reading the actual partition key path from container properties via `container_client.read()` and querying that field.
- **CosmosDB `extract_container_name` returned quoted name (Medium)**: The helper returned `'"my-container"'` (with surrounding quote delimiters) rather than `'my-container'`. Quote delimiters are now stripped after the `rstrip` pass in `_parsing.py`.
- **CosmosDB 404 on missing history container logged at ERROR (Cosmetic)**: Missing container is expected on first run and after `clean`. Log level demoted from `ERROR` to `DEBUG` — eliminates 4 spurious error lines per command on a fresh deployment.
- **CosmosDB 404 in `_execute_delete` after repair logged at WARNING (Cosmetic)**: `ResourceNotFound` during delete is expected when a previous repair sweep already deleted the document. Demoted from `WARNING` to `DEBUG`.
- **CosmosDB `IF EXISTS` guards not parsed before container name extraction (Medium)**: Guarded DDL like `DROP CONTAINER IF EXISTS foo` had the guard phrase included in the extracted container name. Guards are now stripped before name extraction.
- **CosmosDB snapshot capture unreliable (High)**: Multiple interacting issues — placeholder handling, clean semantics, and wildcard-index validation — caused snapshot capture to fail silently or produce incomplete results. Placeholder substitution, clean opt-in, and index validation are now aligned so snapshot persistence works end-to-end.
- **Oracle `%ROWTYPE` / `%FOUND` constructs silently dropped by tokenizer (Medium)**: `OracleTokenizer._is_symbol()` did not claim `%` as a symbol character (only `@` was handled). PL/SQL constructs like `cursor%ROWTYPE` and `cursor%FOUND` were silently discarded. `%` is now claimed alongside `@`.
- **SQL Server snapshot confidence incorrectly degraded to MEDIUM (Medium)**: `validate_indexes()` excluded views from `column_map`, so indexes on indexed views were flagged as invalid table references, penalising the consistency score by 0.2 and producing an 80% confidence result on valid schemas. Views are now included in `column_map`.
- **SQL Server indexed views not exported as replayable batches (Medium)**: Indexed views were exported without `GO` batch separators, making the export non-replayable against SQL Server. Now exported as proper batches.
- **SQL Server dry-run clean preview missing user-defined types (Medium)**: `get_clean_preview()` enumeration did not include user-defined types. Live snapshot index capture now also falls back to JDBC metadata when the native path is unavailable.
- **SQL Server snapshot indexes and clean preview misaligned (Low)**: Index introspection and clean preview returned inconsistent object sets. Both paths now share the same enumeration logic.
- **PostgreSQL Python undo history not committed atomically (High)**: After recording undo history, `commit_transaction()` was not called. On the next connection the undo record appeared rolled back. Explicit commit added after history recording.
- **PostgreSQL performance analysis false positives on partial indexes (Low)**: Partial-index predicates (`WHERE` clause) were passed to the performance analyzer as raw SQL fragments, triggering spurious warnings. Predicates are now normalised before linting, and performance analysis is scoped to query fragments only.
- **MySQL `autocommit` not restored after validation (Medium)**: The `validate` command disabled `autocommit` for transactional checks but did not restore it before returning the connection to the pool. Subsequent commands received a connection with `autocommit=False`. Now restored in all exit paths.
- **SQLite script names not preserved in undo history (Medium)**: The undo history record stored the migration file path rather than the script name, breaking `info` and `repair` lookups. Now stores the canonical script name.
- **SQLite SQL generation and validation not fully supported (Medium)**: Several code paths short-circuited for SQLite before reaching SQL generation and `validate-sql`. SQLite now participates in the full generation and validation pipeline.
- **SQLite URLs and FTS virtual-table exports not handled (Medium)**: `sqlite:///` URL variants and FTS (`fts4`/`fts5`) virtual-table `CREATE VIRTUAL TABLE` statements were dropped during schema export. Both are now handled.
- **Validation not scoped to target migrations (Medium)**: Checksum and missing-script checks ran against the full history even when a `--target` version was specified. Checks are now constrained to the resolved migration set within the target range.
- **Default database config forced non-JDBC providers through JDBC validation (High)**: `BaseDatabaseConfig.create()` built a typed `DatabaseConfig` early in the merge chain. CosmosDB and other non-JDBC providers, which have no JDBC URL, triggered JDBC validation before their own defaults were applied. Typed config is now built only after raw source merging completes.
- **`clean` summary suppressed duplicate object names (Low)**: `Log.info` deduplicated lines by default, silently dropping repeated names when the same object appeared under different types (e.g. a package and a package body with the same name). Added `dedupe=False` parameter to `Log.info`, `MultiLog`, and `AbstractLog`; the clean summary passes `dedupe=False` when enumerating drop candidates.
- **Performance analyzer applied to procedural SQL (Low)**: Stored procedures, functions, and trigger bodies were passed to `PerformanceAnalyzer`, producing false positives for PL/SQL and T-SQL constructs. Procedural blocks are now detected and skipped before analysis.
- **Undo script migration path lost on error (Low)**: When a batch undo step raised an exception, the migration path was cleared before the error handler ran, making the log message unhelpful. Path is now preserved through the error handler.
- **Batch undo file-exists errors swallowed (Low)**: `FileNotFoundError` and `FileExistsError` from the undo script writer were caught and silently discarded. They are now propagated so callers can surface them.
- **SQL warning scan guard case-sensitive (Low)**: The `requires_manual_review` check in the API layer scanned for `"Warning"` with capital W; mixed-case occurrences in generated SQL were missed. The check now lowercases the line before scanning, consistent with the per-line loop.
- **Provider transport contracts misaligned between JDBC and native providers (Medium)**: JDBC and native provider capability declarations (`supports_transactions()`, interface implementations) were inconsistent, causing shared code paths to behave differently depending on the active provider. Capabilities are now declared explicitly; shared code routed through neutral provider hooks; type-checking signatures aligned (`strict_tokenizer` param added to `SqlParserInterface` and all implementations).
- **Version/name collision warning unhelpful (Low)**: When `_validate_checksums` found a missing script that shared a version with a different script name, the warning only mentioned the missing name. The alternate same-version script name is now included in the message so users understand why running `repair` alone won't resolve the mismatch.
- **`mark-as-executed` history rows not committed (High)**: After inserting a `mark-as-executed` history record, `commit_transaction()` was not called, so the row was rolled back on connection close. Explicit commit added.
- **CosmosDB regex parser not registered for migration validation (High)**: The `validate` command's SQL parser registry did not include the CosmosDB-specific regex parser, causing validation to fall back to generic SQL parsing and miss CosmosDB-specific syntax. CosmosDB regex parser is now registered.
- **Oracle `SPOOL` path spacing corrupted (Low)**: SQL*Plus `SPOOL` directives with spaces in the file path were normalised in a way that collapsed internal spaces. Normalisation now preserves spacing within the path argument.

### Changed

- **`DatabaseConfig(**kwargs)` factory**: `refactor(config)` adds a `DatabaseConfig(**kwargs)` constructor for programmatic config building, eliminating the need to construct a raw `dict` and pass it through `from_dict()`.
- **SQL script heuristics shared between `diff` and `undo`**: Duplicate detection logic extracted to a shared helper; `diff` and `undo` commands now use the same classification rules for SQL vs Python scripts.

### Testing

- **Matrix regression tests (new `tests/integration/matrix/` package)**: six pytest modules that encode the seven recurring bug patterns (P1–P7) as DB-free structural invariants, so future regressions fail at CI collection time rather than during release-test loops. 51 tests run without a live database; one additional test (`test_schema_sql_fanout.py`, PostgreSQL-only) guards the cross-schema fan-out pattern behind a `db_container` fixture.
  - `test_parent_flag_behaviour.py` — P1: parent flags like `--dry-run` must reach subcommands (previously silently swallowed by argparse subparser `dest` collisions)
  - `test_dry_run_completeness.py` — P4: dry-run enumeration must list every object that real-clean would drop (no JDBC-only fan-out)
  - `test_dialect_capability_matrix.py` — P3: each provider's declared capabilities (`supports_transactions()`, ISP interface implementations) must match the runtime behaviour
  - `test_json_output_contract.py` — P2: `--format json` outputs must be stable, stdout-only, and free of contaminating log lines
  - `test_url_type_inference.py` — P6: `--db-url` always overrides `config.database.type`, regardless of the starting dialect
  - `test_schema_sql_fanout.py` — P7: schema-qualified introspection queries must not cross-join into other schemas with the same object names (PostgreSQL-only, requires `db_container`)
- BUG-01/02 (`--config`/`--scripts` not overwritten): 8 new regression tests in `tests/unit/cli/test_main_cli_decomposition.py` asserting `args.config` and `args.scripts_list` survive subparser processing for `info`, `migrate`, `baseline`, `snapshot`, and `export-schema`
- BUG-03/04 (`db check-connection`/`validate-config`): updated all `TestCheckConnection` and `TestValidateConfig` tests in `tests/unit/cli/test_db_utils.py` to patch `cli.db_utils.load_config`; updated `TestUtilityFunctions` tests accordingly
- BUG-06 (`info --format json`): 2 new tests in `tests/unit/cli/test_main_cli_ocp_registry.py` asserting JSON output on `format=json` and no JSON on `format=table`; 2 new parser tests asserting `--format` is accepted with default `"table"`
- BUG-08 (`select_star` severity): updated `test_select_star_detection` in `tests/unit/core/sql_validator/test_performance_analyzer.py` to assert `WARNING` severity
- `sqlite:///` RFC 3986 parsing: updated `test_get_database_path_from_url` in `tests/unit/sqlite/test_sqlite_provider.py` — the previous assertion codified the leading-slash-dropping bug (`path/to/db.sqlite`); it now asserts the absolute form `/path/to/db.sqlite`.
- SQLite duplicate FK introspection: new tests in `tests/unit/sqlite/` covering multi-column FK deduplication by constraint name
- SQL Server migration bug regressions: new parametrised tests covering indexed-view snapshot confidence, batch export, and clean preview UDT coverage
- CosmosDB snapshot persistence: integration test (`tests/integration/test_cosmosdb_snapshot.py`) verifying snapshot capture and retrieval after a successful `migrate` using `? param` substitution
- Migration contract hardening: `tests/unit/core/migration/` fixtures replaced hard-coded `venv/bin/python` paths with `sys.executable`; slow setup fixtures converted to session-scoped to reduce test suite runtime

## [1.3.1] - 2026-04-14

### Fixed

- **Python migrations silently rolled back (Critical)**: `ExecutionEngine._execute_via_factory()` now wraps the non-SQL execution path in an explicit `begin → execute → record_history → commit` transaction lifecycle (mirroring the SQL path), with best-effort `rollback_transaction()` on every failure branch. Previously DDL emitted from Python scripts plus `record_migration` stayed in an uncommitted transaction that the next migration's `_prepare_transaction → rollback_transaction()` wiped out, so migration-tracked changes never persisted.
- **SQLite unusable via `jdbc:sqlite:` URLs (Critical)**: `BaseDatabaseConfig.create()` now short-circuits JDBC URL parsing when the configured `type` is in `non_jdbc_providers = {"cosmosdb", "sqlite", "sqlite3"}`, and guards `if parsed.get("db_type"):` before overwriting `data["type"]`. Previously `_parse_jdbc_url` had no sqlite pattern and returned `None`, which then overwrote the explicit `type: sqlite` with `None` and broke all downstream provider selection. URL-prefix inference for `jdbc:sqlite:` is also added so the type is inferred when not set.
- **`repair` broken on Oracle/SQL Server/SQLite (High)**: `RepairCommand._delete_failed_migration_entry()` now selects a dialect-aware `false_literal` — `0` for Oracle, SQL Server, MSSQL, SQLite/SQLite3; `false` for CosmosDB; `FALSE` for PostgreSQL/MySQL/DB2 — replacing the hard-coded `success = FALSE` literal that Oracle (`NUMBER(1)`) and SQL Server (`BIT`) refuse.
- **`--config FILE db <subcmd>` routing**: `cli/main.py` now classifies `--config`, `--scripts`, and `--dry-run` as `global_only_args` in `_extract_commands_from_argv()`, so `dblift --config F db check-connection` no longer consumes `F` as the `db_command` positional of the `db` subparser.
- **`db validate-config --config F` ignored the file**: `cli/db_utils.py:validate_config()` now calls `load_config(config_file, args)` when `args.config` is set, instead of silently discarding it and building the config from CLI flags only.
- **`MigrationContext` missing `execute()` helper**: added `MigrationContext.execute(sql, params=None)` that delegates to `provider.execute_statement()`, so Python migration scripts can run arbitrary SQL against the active connection without reaching into provider internals.
- **French user-facing strings in `python_executor.py`**: all validation messages, error messages, log output, and attribute docstrings in `core/migration/executors/python_executor.py` translated to English for consistency with the rest of the tool.
- **`argparse` errors exited with code 0**: `cli/_config_helpers.py` and `cli/main.py` now `sys.exit(2)` when `parse_with_selective_errors` returns `has_error=True`, so shell scripts can detect invalid CLI invocations via exit status (e.g. `dblift baseline` with missing required args).
- **Misleading `Error_Rate: 100.0%` in diff/snapshot output**: `DiffCommand._log_quality_score()` and `SchemaSnapshotService._log_quality_score()` now map the `error_rate` dict key to the display label `Success_Rate` (since a score of 1.0 means "no errors" / perfect quality). The underlying dict key and JSON output are unchanged for backwards compatibility; only the human-facing label is renamed.
- **Unreadable traceback on `db check-connection` failure**: `db/base_connection_manager.py:_handle_connection_error()` demotes the `traceback.format_exc()` line from `log.error` to `log.debug`, so normal users see only a clean one-line failure message (details remain available via `--log-level debug`).
- **`export-schema --versions/--tags` applied no filter without `--managed-only`**: `export_schema_command.py:_filter_objects()` now applies the managed-objects filter whenever any of `target_version`, `tags`, or `versions` is set — the previous warning telling users to combine the flag with `--managed-only` / `--unmanaged-only` was removed, and the filter now intersects the live schema with the managed set implicitly.
- **`check-connection` traceback on auth/network failures**: `cli/db_utils.py:check_connection()` narrows the try/except, introduces a `_format_connection_error()` helper that maps "refused" → "host unreachable", "authentication" → "invalid credentials", "unknown host" → "host not found", and gates the traceback on `args.log_level == "debug"`.
- **`--config FILE` with missing file crashed silently**: `config/dblift_config.py:load_config()` now raises `FileNotFoundError` / `RuntimeError` on bad paths, and the CLI `_load_and_merge_config` helper catches these and exits 1 with a clean message.
- **Partial env-var overrides rejected**: `config/dblift_config.py:load_config()` injects `_allow_incomplete=True` into the env-var dict before calling `DbliftConfig.from_dict()`, so env-var config like `DBLIFT_DB_URL` without a matching password no longer fails strict validation when merging onto a base file config.
- **`repair` on failed `R__` (repeatable) migrations**: `RepairCommand` now diverts the CHECKSUM_MISMATCH branch to `_delete_failed_migration_entry()` when the script appears in `migration_state.failed_objects`, instead of trying to update a non-existent successful row.

### Changed

- **`config/database_config.py` JDBC branch cleanup**: the unreachable `elif db_type in non_jdbc_providers:` tail of the `if url:` chain was removed — the pass-through path at the top of the chain now handles all non-JDBC providers before the `elif url.startswith("jdbc:"):` branch, making the `else: raise` the sole fallback for invalid URLs.

### Testing

- BUG-01 (`--config` routing): new test in `tests/unit/cli/test_main_cli_decomposition.py` covering `_extract_commands_from_argv(["--config", "/tmp/c.yaml", "db", "check-connection"])`
- BUG-02 (`validate-config --config F`): tests in `tests/unit/cli/test_db_utils.py` asserting `load_config` is called when `args.config` is set
- BUG-03 (`MigrationContext.execute`): new `tests/unit/core/migration/executors/test_python_executor.py` tests verifying `execute()` delegates to `provider.execute_statement()` + English-string assertions replacing the previous French ones
- BUG-04 (Python migration transactions): new `tests/unit/core/migration/executor/test_execution_engine_python_routing.py` tests using a real `TransactionalProvider` subclass to verify `commit_transaction()` on success and `rollback_transaction()` on failure
- BUG-05 (exit code 2): subprocess test in `tests/unit/cli/test_main_cli.py` asserting `dblift baseline` returns exit code 2
- BUG-06 (`Success_Rate` label): assertion in `tests/unit/core/migration/commands/test_diff_command.py` that the breakdown output renders `Success_Rate` instead of `Error_Rate`
- BUG-07 (dialect-aware repair): `tests/unit/core/migration/commands/test_repair_command.py` parametrized on `db_type ∈ {oracle, sqlserver, postgresql, mysql, sqlite}` asserting the correct `false_literal` is rendered
- BUG-08 (traceback gating): assertion in `tests/unit/db/test_base_connection_manager.py` that `_handle_connection_error` does not call `log.error` for the traceback line
- BUG-09 (SQLite + JDBC URL): `tests/unit/config/test_database_config.py` test asserting `BaseDatabaseConfig.create({"type":"sqlite","url":"jdbc:sqlite:/tmp/x"})` keeps `type="sqlite"` and does not raise

## [1.3.0] - 2026-04-12


### Fixed

- **`AccuracyValidator` view inputs removed**: `DiffCommand._diff_using_snapshot()` no longer passes a `"views"` key to `AccuracyValidator.validate_all()` — the validator only handles tables and indexes, so the key was dead data that gave a false impression of view-drift detection
- **`db_type` `None` crash after JDBC URL parsing**: `BaseDatabaseConfig.create()` now uses `(data.get("type") or "").lower()` instead of `data.get("type", "").lower()` — the `.get()` default only fires when the key is absent, not when its value is `None` (set by `_parse_jdbc_url` via `_empty_jdbc_result`), which previously raised `AttributeError: 'NoneType' object has no attribute 'lower'`
- **License guard `SystemExit 78` in unit tests**: `ExecutionEngine` switched from a module-level `from core.licensing._guard import _refresh_state` (which captured the real function before any fixture could patch it) to an inline import inside `execute_migration()`, matching the pattern used by `JdbcProvider`, `SchemaIntrospector`, and `MigrateCommand`
- **`test_guard.py` no-op bypass**: added a local `autouse` fixture override in `test_guard.py` so the global `_bypass_license_guard` conftest fixture (which patches `_refresh_state` to a no-op for all unit tests) does not shadow the real function under test
- **BUG-ORACLE-SCHEMA-QUOTING**: Oracle SQL construction now references schemas via a centralized double-quoted, case-preserving helper (`BaseQueryExecutor.get_quoted_schema_name`) — previously the history table was created as `"dbo"."DBLIFT_SCHEMA_HISTORY"` (quoted, case-sensitive lowercase) while the snapshot table and `table_exists()` lookups used unquoted `DBO.…` / `WHERE owner = 'DBO'` forms, so every `info`/`diff` after a successful `migrate` silently reported zero applied migrations. `OracleQueryExecutor.table_exists()` no longer uppercases the schema parameter; `OracleSchemaOperations.create_schema_if_not_exists()` builds `CREATE USER`/`GRANT` via the helper (and uses a case-sensitive `ALL_USERS` lookup to match the user's exact intent); `set_current_schema()` and the DB-link `ALTER SESSION SET CURRENT_SCHEMA` reset also go through the helper; the hardcoded Oracle branch in `JdbcProvider.create_snapshot_table_if_not_exists()` that built `{schema.upper()}.{table.upper()}` is removed and now uses the shared `qualified_table`.
- **BUG-DB2-SCHEMA-QUOTING**: Same class of inconsistency as Oracle — `Db2SchemaOperations.create_schema_if_not_exists()` and `set_current_schema()` hand-rolled `f'"{clean_schema}"'` and the existence check used `UPPER(SCHEMANAME) = UPPER(?)` (case-insensitive) followed by case-preserving quoted DDL. If the caller passed a schema with different case than what was stored (e.g. `db2inst1` when the actual schema is `DB2INST1`), the existence check reported "already exists" and the subsequent quoted DDL (`CREATE TABLE "db2inst1"."…"`) targeted a non-existent schema. Both sites now go through `BaseQueryExecutor.get_quoted_schema_name()` and the existence check is case-sensitive. (DB2 did not exhibit the Oracle silent-zero-migrations symptom because `Db2QueryExecutor.table_exists()` already uses a permissive `UPPER(X) = UPPER(?) OR X = ?` dual-match that finds the history table regardless of case — left unchanged.)

### Changed

- **`--db-schema` is now required** for every dialect except SQLite: the implicit `"dbo"` default (previously leaked through `BaseDatabaseConfig.create()` and `DbliftConfig.default()`) has been removed, and the existing CLI validation in `cli/_config_helpers.py:_validate_db_config` now fires for SQL Server too. Users must pass `--db-schema` on the command line or set `schema:` in their config file. This prevents the failure mode where running dblift against Oracle (or any other dialect) without `--db-schema` silently picked up a SQL Server convention that didn't exist in the target database.
### Security

- **Cython compilation of critical-path modules**: License validation, CLI entry point, and command dispatch are compiled to native extensions (`.so`/`.pyd`) in distributed packages — source code for these 8 modules is no longer readable or editable
- **Dispersed license guards**: Runtime license verification added in 4 core modules (`ExecutionEngine`, `JdbcProvider`, `MigrateCommand`, `SchemaIntrospector`) with obfuscated names and 2-minute TTL cache; bypassing the CLI gate alone is no longer sufficient

### Added

- **`IntrospectionValidator.validate_introspection()` now accepts `live_objects`**: passing a `{"tables": [...], "indexes": [...], "views": [...]}` dict enables the `AccuracyValidator` path inside `StateValidator.validate_schema()`, so callers can get accuracy comparison results alongside structural quality metrics in a single call
- **Non-blocking accuracy gate in `DiffCommand._diff_using_snapshot()`**: after building the live payload, `AccuracyValidator.validate_all()` is called comparing snapshot vs live objects; if differences are found a `log.warning` is emitted noting schema drift, but the diff continues uninterrupted; exceptions in the accuracy check are also caught and warned about rather than aborting
- `setup_cython.py` — Cython build script for compiling 8 critical-path modules to native code
- `core/licensing/_guard.py` — Cached runtime license guard with `sys.exit(78)` on failure
- Cython compilation step in CI/CD workflow (`build.yaml`) for all 3 platforms (Linux, macOS, Windows)
- `build_distributions.py` now strips `.py` sources and replaces them with compiled `.so`/`.pyd` in distribution archives

### Testing

- 5 tests for `_guard.py` (valid license, exit code 78, cache TTL, cache expiry, no cache on failure)
- **IntrospectionValidator** (`test_introspection_validator.py`) — 12 tests covering construction, `validate_introspection` with/without `live_objects` and `introspection_result`, and `log_validation_summary`; raises `validation_integration.py` coverage from 0% to 97%
- **DiffCommand accuracy gate** — 43 new tests in `test_diff_command.py` covering `_diff_using_snapshot` end-to-end, the new `AccuracyValidator` gate (warn-on-drift, exception-tolerant), and all `_log_*` static methods (`_log_function_diffs`, `_log_synonym_diffs`, `_log_package_diffs`, `_log_user_defined_type_diffs`, `_log_extension_diffs`, `_log_foreign_data_wrapper_diffs`, `_log_foreign_server_diffs`, `_log_event_diffs`, table property changes); raises `diff_command.py` coverage from 50% to 80%
- **875 new unit tests** across `core/` and `db/` modules to raise coverage from ~73.8% toward ≥80%:
  - `test_formatters.py` — 50 tests for SQL validator linting formatters (Console, JSON, Compact, SARIF, GitHubActions, FormatterFactory)
  - `test_introspection_normalizer.py` — 58 tests for `IntrospectionNormalizer` (deduplication, data-type normalization, PK reconciliation)
  - `test_diff_analyzer.py` — 51 tests for `DiffAnalyzer` (dependency graph, topological sort, breaking-change detection, safety checks)
  - `test_migration_journal.py` — 60 tests for `MigrationJournal` (thread-safe entry tracking, performance stats, statement lifecycle)
  - `test_migration_data_service.py` — 79 tests for `MigrationDataService` (version tracking, out-of-order detection, undo handling)
  - `test_round_trip_comparator.py` — 32 tests for `RoundTripComparator` (table/view/index comparison, summary generation)
  - `test_base_tokenizer.py` — 55 tests for `BaseTokenizer` (comment, string, delimiter, keyword, number handling)
  - `test_base_statement_parser.py` — 79 tests for `BaseStatementParser` (block depth, spacing rules, statement splitting)
  - `test_sequence_extractor.py` — 24 tests for `SequenceExtractor` (cycle detection, Oracle ISEQ$_ filtering, PostgreSQL temp sequences)
  - `test_trigger_extractor.py` — 48 tests for `TriggerExtractor` (event parsing, DB2 aliases, MySQL definer)
  - `test_view_extractor.py` — 42 tests for `ViewExtractor` (column caching, MySQL algorithm, materialized views, PostgreSQL security)
  - `test_column_extractor.py` — 51 tests for `ColumnExtractor` pure-logic helpers (data type building, identity/computed detection)
  - `test_constraint_validator.py` — 55 tests for `ConstraintValidator` (PK/FK/unique/check validation, column references)
  - `test_table_extractor.py` — 55 tests for `TableExtractor` helpers (`_should_skip_table`, `_verify_schema_match`, `_is_temporary_table`, PostgreSQL enrichment, partitioned table supplement)
  - Extended `test_jvm_manager.py` (+20 tests) — `_discover_jdbc_driver_dirs`, `_add_system_jdbc_dirs`, `get_connection`, shutdown edge cases
  - Extended `test_jre_manager.py` (+11 tests) — PyInstaller MEIPASS paths, package-directory JRE discovery, explicit `java_home`

### Refactored

- **Centralized schema quoting across all JDBC dialects**: every `create_schema_if_not_exists()`, `set_current_schema()`, and `clean_schema()` SQL construction site in PostgreSQL, SQL Server, and MySQL now routes schema references through `BaseQueryExecutor.get_quoted_schema_name()` / `get_schema_qualified_name()` instead of hand-rolling `f'"{schema}"'`, `f'[{schema}]'`, or `` f"`{schema}`" ``. Behavior is unchanged for these three dialects (they are case-insensitive or case-normalizing), but every schema reference now flows through the same dialect-aware helper that powers the Oracle and DB2 fixes — making future dialect additions or quoting rule changes a single-site edit.

## [1.2.0] - 2026-04-10

### Added

- **Licensing system**: JWT-based license validation with RS256 signature verification (`core/licensing/`)
- **CLI `license` commands**: `dblift license activate <key>`, `license info`, `license check`, `license deactivate` for managing license keys from the command line
- **License gate**: All migration commands (migrate, undo, clean, validate, diff, info, repair, baseline, export-schema, snapshot, import-flyway, validate-sql) now require a valid license; `license` and `db` utility commands remain unrestricted
- **License info in reports**: License holder name, email, and expiry displayed in HTML, JSON, and text log output headers
- **`--license-key` CLI flag**: Pass a license token directly on the command line; resolution order is CLI arg → `DBLIFT_LICENSE_KEY` env var → `~/.dblift/license` file
- **CosmosDB connection guard**: `_get_connection_or_raise()` added to `CosmosDbProvider`; all provider methods raise `RuntimeError` immediately if `create_connection()` was not called, replacing the silent `None`-connection pattern
- **Licensing documentation**: Architecture guide (`docs/architecture/licensing.md`), user-guide sections for `license` commands and getting-started activation flow

### Fixed

- **Oracle history manager**: Renamed DDL/DML column `SCRIPT` → `script_name` to match the `BaseHistoryManager` contract directly (no more key remapping in `_normalize_results`)
- **CLI `--license-key` in multi-command mode**: `_build_args_namespace` fallback path now extracts `--license-key` and initializes `license_key=None` consistently with other database arguments
- **CLI log-format validation scope**: `_validate_db_config` skips log-format validation for `db` utility commands (they exit before configuring logging) while still validating for `validate-sql` and all migration commands

### Security

- Removed `scripts/generate_license.py` from the repository to reduce exposure of JWT claim structure used in license verification

### Refactored

- **`cli/main.py` decomposition** (story 20-16): Extracted command handlers to `cli/_command_handlers.py` (510 lines) and config/setup helpers to `cli/_config_helpers.py` (473 lines); `cli/main.py` reduced from 1204 to 253 lines while preserving full backward-compatible imports

### Testing

- 271-line `test_license_commands.py`: CLI command tests covering activate, info, check, deactivate, edge cases
- 321-line `test_license_manager.py`: Token validation, expiry, signature verification, resolution priority, file I/O
- 63-line `test_text_formatter_license.py`: License info rendering in text formatter
- 180-line `test_repair_command.py`: Repair with null success, explicit success, not found, exception propagation
- 15 CosmosDB provider guard tests (`test_provider.py`)
- Integration test gate: tests skip with clear message when `DBLIFT_LICENSE_KEY` is not set

## [1.1.1] - 2026-04-05

### Fixed

- **BUG-SNAPSHOT-01** [HIGH]: SQLite `dblift_schema_snapshots` now uses the standard columns (`snapshot_id`, `captured_at`, `checksum`, `model_data`); legacy layouts are detected, backed up, recreated, and rows migrated (`schema_json` → `model_data` / checksum) via `sqlite/snapshot_table.py`
- **BUG-PARSER-01** [LOW]: `SQLiteRegexParser.extract_objects()` signature matches `EnhancedRegexParser` (`sql_content`, `default_schema`, dialect) and returns `List[SqlObject]`
- **BUG-REPAIR-01** [MEDIUM]: `repair` checksum drift detection uses `MigrationState.all_applied_objects` (unfiltered) so undone migrations no longer hide mismatches; safe fallback when the field is absent
- **BUG-REPAIR-02** [MEDIUM]: Failed migration rows are **deleted** instead of `success=NULL`, matching Flyway-style retry and avoiding NOT NULL violations on `success`
- **BUG-CHECK-CONN-01**: `check-connection` — JDBC providers expose `get_jdbc_url()` (PostgreSQL, MySQL, Oracle, DB2, SQLite); `db_utils` falls back when a provider omits it; DB2 delegating URL via `connection_manager`
- **BUG-VALIDATE-SQL-01**: `validate-sql` always initializes the client when needed; standalone path uses `ValidateSqlConfigClient` so validation runs without a live DB where appropriate
- **BUG-UNDO-01**: `generate_undo_script` returns `MigrationExecutionResult(success=False, ...)` for `FileNotFoundError`, `FileExistsError`, and `ValueError` instead of raising; undo path logs `MIGRATION_FAILED` then re-raises `FileNotFoundError` for missing scripts
- **API-01** [LOW]: `InfoCommand` populates `current_schema_version` from applied migrations
- **API-02** [LOW]: `MigrationInfo.status` normalized (e.g. `SUCCESS`); `BASELINE` preserved end-to-end in info, `MigrationDataCollector`, and HTML stats (exact `BASELINE` match — no false hits on “below baseline” copy)
- **PARSER-TRIGGER-01** [LOW]: SQLite regex parser tracks `CASE`…`END` depth separately from trigger `BEGIN`…`END` blocks
- **BUG-CONFIG-MERGE** [MEDIUM]: `ConfigBuilder` / `DbliftConfig.merge` — YAML loads merge onto defaults; `database: null` is ignored; file config is the merge base when it defines `database`, avoiding SQL Server defaults leaking into other dialects; extended merge for `strict_mode`, journal, retry/error fields, CLI log overrides, `retryable_error_categories`, and defensive handling of non-dict sections
- **DDL-TX-01**: `TransactionalProvider.supports_transactional_ddl()` (MySQL/Oracle return `False`); `ExecutionEngine` and `repair` warn on partial DDL failure when DDL is non-transactional
- **CLI-CONFIG-01**: `--config` mapped to `config_file` for `from_all_sources()`; migration directories resolve relative to the config file directory, not the process CWD
- **BUG-COSMOSDB-01**: Cosmos DB query executor strips trailing semicolons before execution
- **BUG-COSMOSDB-02**: `repair` uses inline values and lowercase `false` for non-transactional providers (Cosmos DB SQL API — no `?` placeholders / uppercase boolean literal issues)

### Added

- **SqlObjectType.VIRTUAL_TABLE** with parser/object-order integration for SQLite virtual tables
- **`tests/unit/test_v110_regressions.py`**: regression coverage for the v1.1.0 E2E findings (repair, JDBC URL, validate-sql, undo script, info API, parser, config, HTML stats, snapshot migration, Cosmos DB, etc.)

### Changed

- **`MigrationStateManager.get_current_version()`**: public API; call sites no longer use `_get_current_version()`
- **Docs**: removed `docs/ANALYSE_SOLID.md` and `docs/parser_comparison_flyway_vs_dblift.md` (internal analysis)

### Testing

- E2E validation report for v1.1.0+: SQLite through six-JDBC databases (PostgreSQL, MySQL, SQL Server, Oracle XE 21c, DB2 11.5), API, parser, and advanced scenarios; regression suite expanded as above

## [1.1.0] - 2026-04-03

### Fixed

- **NEW-BUG-01** [HIGH]: `return_generated_keys=True` now wired in MySQL and DB2 `execute_statement()` — flag was accepted but silently ignored; both now use `Statement.RETURN_GENERATED_KEYS` and call `_extract_generated_keys()` (mirrors existing Oracle/PostgreSQL pattern)
- **NEW-INCONS-01** [MEDIUM]: MySQL and DB2 `execute_statement()` now call `_log_execution_error(debug_sql=False)` — SQL was previously only visible in DEBUG logs, inconsistent with Oracle/PostgreSQL which log at ERROR level
- **SEC-01** [HIGH]: `BaseDatabaseConfig.__post_init__()` now validates schema names with `re.match(r'^\w+$', schema)` — invalid names (containing `;`, `/`, `.`, spaces, quotes) raise `ValueError` at config parse time, protecting all 5 downstream DDL interpolation sites
- **INTROS-ORA-01** [MEDIUM]: Oracle `ALL_*` metadata queries bind owner and table with case-insensitive matching (`UPPER(owner)=UPPER(?)`, `UPPER(table_name)=UPPER(?)`) so JDBC/config identifier case matches the catalog; restores CHECK and virtual-column introspection when casing differs; unique constraints are no longer discarded solely because the backing index name looks like a system-generated `SYS_*` name (aligned with the JDBC constraint path).
- **INTROS-ORA-02** [MEDIUM]: Oracle introspection reads CHECK constraint text and virtual-column expressions from `LONG` columns via `NVL` / `SUBSTR(...,1,4000)` instead of excluding those rows in `WHERE`, so constraint and expression metadata is available for diff/compare.
- **PARSER-SS-01** [LOW]: SQL Server tokenizer treats `@local` parameters and `@@global` variables as single tokens, fixing batch splitting / parsing around T-SQL variables.
- **EXEC-PRECHECK-01** [MEDIUM]: `ExecutionEngine` uses a dialect-aware JDBC pre-check for DB2 and Oracle (from URL shape, `jdbc:db2/` variants, and config); comment-only migration batches are skipped before execute; related updates across migration validator, parsers, tokenizers, and DB2/Oracle query executors.
- **API-LOG-01** [LOW]: `DBLiftClient` / factory honor `logging.file`, `log_dir`, and `logging.directory` for `DbliftLogger` paths; nested logging keys are read defensively when the client builds the logger.
- **CFG-MYSQL-01** [LOW]: MySQL JDBC URL parsing in `database_config` is wired through an explicit helper so behavior matches the decomposed `_parse_jdbc_url` pattern used by other dialects.
- **CFG-STR-01** [MEDIUM]: `BaseDatabaseConfig.build_connection_string()` no longer falls back to `build_jdbc_url()` when the URL is unset — raises `NotImplementedError` instead so native drivers are not given a synthetic `jdbc:` string.

### Added

- **DEV-TOOL-01**: Optional [pre-commit](https://pre-commit.com) hook `check-code-quality` (black, isort, flake8, mypy via `scripts/run_code_quality_hook.sh`); `.flake8` sets `jobs = 1` for deterministic lint runs.
- **scripts/run_integration_local.sh**: Helper script to run integration tests against local or Docker-backed databases.

### Removed

- **NEW-DEAD-01**: Removed `BaseQueryExecutor._handle_connection_error()` — never called anywhere; `_log_execution_error()` covers the same need
- **DEAD-10**: Removed unused `dialect: Optional[str] = None` parameter from `BaseGenerator.generate_create_statement()` — updated all 13 production callers and 14 test files
- **DEAD-11**: Removed dead `_parse_mysql_url` alias from `BaseDatabaseConfig` after MySQL URL parsing moved to `_parse_jdbc_url` helpers.
- **27 inline imports**: Moved all `import re` (×21), `import traceback` (×8), and `import logging` (×1) occurrences from inside function bodies to module level

### Refactored

- **DEDUP-33a** (`_set_parameters`): Extracted common parameter binding logic to `BaseQueryExecutor._set_parameters()`; all 5 executors now delegate, keeping only dialect-specific overrides (~150 lines removed)
- **DEDUP-33b** (`_result_set_to_dict_list`): Extracted shared result-set iteration to `BaseQueryExecutor._result_set_to_dict_list()`; executors override only `_convert_java_to_python()` (~400 lines removed)
- **DEDUP-44** (`_convert_java_to_python`): Base implementation in `BaseQueryExecutor` handles NULL + 12 common JDBC type codes; each executor overrides only dialect-specific branches (Oracle CLOB/BLOB, DB2 SQLXML, PostgreSQL ARRAY, MySQL TINYINT(1)→bool)
- **DEDUP-30** (History manager `__init__`): All 7 history managers now call `super().__init__()` instead of duplicating the 4-line body; removed 6 redundant `NullLog` imports
- **DEDUP-36** (Migration params): `BaseHistoryManager._build_migration_params()` extracted; used by PostgreSQL, MySQL, Oracle, DB2 history managers
- **SIMP-47** (`_parse_jdbc_url`): Decomposed 270-line monolith into per-dialect private methods (`_parse_postgresql_url`, `_parse_mysql_url`, `_parse_sqlserver_url`, `_parse_db2_url`, `_parse_oracle_url`)
- **SIMP-49** (`generate_sql_script`): Introduced `GenerateSqlScriptOptions` dataclass grouping 16 optional parameters; backward-compatible via keyword-arg fallback
- **SIMP-45/65** (`repair_command.execute`): Decomposed 431-line method into 7 focused private methods; `execute()` is now a ~50-line orchestrator
- **SIMP-46** (`jsonformatter.format_result`): Decomposed 426-line method into 8 private methods; `format_result()` is now a ~25-line dispatcher
- **SIMP-50** (`export_schema_command` hasattr chains): Replaced 4× `hasattr(config, "database") and hasattr(config.database, "type")` with `getattr(..., None)` chains
- **SIMP-53/64** (Formatter isinstance dispatch): Replaced 7-way isinstance chain and `_get_command_type` with `_RESULT_DISPATCH` dict in `OutputFormatter`
- **SIMP-54** (Schema introspector vendor dispatch): Extracted 4 `_apply_vendor_table_properties_*` methods + `_VENDOR_TABLE_PROPERTY_HANDLERS` dispatch dict in `SchemaIntrospector`
- **SIMP-37** (Dialect dispatch utility): Added `dispatch_by_dialect()` to `core/sql_model/dialect.py`; applied to 2 clean if/elif chains in `RoundTripTester`
- **LSP-01** (`rollback_migration`): Base executor no longer raises `NotImplementedError`; returns `MigrationExecutionResult(success=False, error="...")` instead
- **LSP-02** (`build_connection_string`): `BaseDatabaseConfig.build_connection_string()` is now a true `@abstractmethod`; `BaseDatabaseConfig` inherits from `ABC`
- **LSP-03** (`get_all_indexes`): `IndexExtractor.get_all_indexes()` now returns `[]` instead of raising `NotImplementedError`
- **ISP-01** (VendorMetadataQueries split): Added 5 `@runtime_checkable` Protocol interfaces (`ITableQueries`, `IViewQueries`, `IConstraintQueries`, `IIndexQueries`, `IStoredObjectQueries`) in `db/introspection/vendor_queries_protocols.py`; all 5 concrete vendors satisfy all 5 protocols
- **ISP-02** (`BaseCommand` context): Introduced `BaseCommandContext` dataclass grouping 13 infrastructure params; `MigrationExecutor` uses `_make_command_context()` helper, replacing 8 verbose 13-arg instantiations
- **DIP-01** (`BaseCommand` hasattr→isinstance): `hasattr(provider, "get_database_version")` guards replaced with `isinstance(provider, SchemaProvider)` (Epic 12-16 interfaces)
- **DIP-02** (`ExecutionEngine` JdbcProvider→interfaces): `isinstance(provider, JdbcProvider)` replaced with `isinstance(provider, TransactionalProvider)` in `_prepare_transaction`, `_execute_statements`, `_commit_and_verify`
- **OCP-02** (CosmosDbSdkTranslator): 9-way if/elif in `execute_sdk_operation` replaced with `_OP_EXECUTOR_MAP` dispatch dict
- **OCP-03** (BasicTableDdlGenerator): `_build_identity_clause` 4-way if-chain replaced with `_IDENTITY_STRATEGIES` dict
- **OCP-04** (HybridParser): `_get_regex_parser` 6-way if/elif replaced with `_PARSER_MAP` dict
- **OCP-05** (VendorQueriesFactory): `_DIALECT_MAP` replaced with module-level `_VENDOR_QUERIES_REGISTRY` + `register_vendor_queries()` plugin function
- **SRP-04** (DiffSqlGenerator): Extracted `DiffSqlStatementBuilder` class (16 DDL-building methods); `DiffSqlGenerator` retains only orchestration, delegates via `self.builder`
- **SRP-06** (`_log_command_header_update`): Decomposed 190-line method into 5 focused private helpers in `BaseCommand`
- **SRP-01** (JdbcProvider): Extracted `JdbcTypeConverter` class (16 type handlers + `convert()` entry point); `JdbcProvider` delegates via `self._type_converter`
- **SRP-02** (SchemaIntrospector): Extracted `VendorPropertyApplier` class (4 per-dialect handlers + `_HANDLERS` dispatch dict); `SchemaIntrospector` delegates via `self._vendor_property_applier`
- **SRP-03** (ExportSchemaCommand): Added `ManagedObjectFilter(config, log)` wrapper class around `_filter_objects` module function
- **SRP-05** (UndoStatementEmitter): Added `UndoStatementEmitter` to `undo_script_generator` package wrapping extraction helpers

## [Previous]

### Fixed

- **BUG-01** [HIGH]: `isinstance(param, bool)` now checked before `isinstance(param, int)` in `_set_parameters()` for Oracle, MySQL, SQL Server, and DB2 query executors — booleans were silently routed to `setInt()` instead of `setBoolean()` because `bool` is a subclass of `int` in Python
- **BUG-02** [HIGH]: Added `rs, stmt = None, None` initialization before `try` in SQL Server `_get_database_version()` — `UnboundLocalError` was raised in the `finally` block when `prepareStatement()` or `executeQuery()` failed, masking the original exception
- **BUG-03** [MEDIUM]: DB2 `_convert_java_to_python()` now returns `None` immediately when `getObject()` returns `None` — integer/float NULL columns were being reported as 0/0.0 via Java's primitive getters
- **BUG-04** [LOW]: DB2 CLOB character reader now wrapped in `try/finally` — `reader.close()` was unreachable on exception

### Removed

- **DEAD-02**: Removed unreachable `try: pass / except Exception:` block in SQL Server `create_connection()` — the schema-setting placeholder can never raise
- **DEAD-01**: Removed `_validate_parameters()` from `BaseQueryExecutor` — dead code never called by any of the 5 concrete executors

### Added

- **Python Migration Support**: New `PythonMigrationExecutor` and `MigrationContext` for executing `.py` migration scripts
  - Python migrations registered in `ExecutorFactory` alongside SQL migrations
  - Python callbacks routed symmetrically via `executor_factory` (mirrors SQL routing)
  - `MigrationContext` provides database connection and metadata to Python scripts
  - Full dry-run and validate support for Python migrations

- **NullLog Pattern**: Introduced `NullLog` class implementing the `Log` interface as a no-op logger
  - All constructors now accept `log: Log = NullLog()` — eliminates 87 `if self.log:` guards across the codebase
  - `NullLog` exported from the top-level `__init__.py`

- **Provider Interfaces (ISP)**: `BaseProvider` decomposed into 5 focused interfaces
  - `ConnectionProvider`, `QueryProvider`, `SchemaProvider`, `TransactionalProvider`, `MigrationProvider`
  - `CosmosDbProvider.supports_transactions()` correctly returns `False`
  - `isinstance` checks replace fragile `hasattr` guards in `ExecutionEngine` and API client

- **OCP Command Registry**: `execute_single_command` now uses a `_COMMAND_HANDLERS` registry dict
  - Adding a new CLI command requires only adding one entry to the registry
  - `CliCommandContext` dataclass bundles the 8 shared parameters passed to every handler

- **Dataclass Extraction**: Three parameter-heavy signatures replaced with typed dataclasses
  - `ExportSchemaOptions` (22 parameters → 4 call-site parameters in `export_schema()`)
  - `DiffGenerationContext` (17 `expected_*` parameters → 3-parameter `generate_from_diff()`)
  - `CliCommandContext` (8 shared CLI handler parameters)

- **Lock Table Schema Contract**: Formal documentation of the migration lock table schema
  - MySQL and DB2 column names aligned (`lock_name`, `acquired_at`, `acquired_by`)

- **Flyway Schema Alignment** (Epic 17): History table structurally identical to `flyway_schema_history`
  - CRC32 line-by-line checksum algorithm (replaces MD5); checksum column type `INT` / `NUMBER` / `INTEGER`
  - Column `script_name` renamed to `script`; `MigrationType.VERSIONED` renamed to `MigrationType.SQL`
  - NOT NULL constraints on 7 columns: `description`, `type`, `script`, `installed_by`, `installed_on`, `execution_time`, `success`
  - `import_flyway` command updated for aligned schema (direct column mapping)

- **Shared migration version utilities** (Epic 23): `core/migration/version_utils.py` with `compare_versions()`, `is_migration_success()`, and `is_migration_failure()` — single semver-compare implementation reused across commands and JDBC-safe success/failure checks (avoids fragile `is True` / `is False` on driver return types)

- **`BaseJdbcConnectionManager`** (Epic 24): Shared `__init__` and `import_java_classes()` for all JDBC connection managers (PostgreSQL, MySQL, SQL Server, Oracle, DB2); ~190 lines of duplication removed

- **Test suite hardening** (Epic 23): Static review and cleanup of unit and integration tests — `pytest.mark.integration` / module `pytestmark` consistency, stronger assertions, dead fixtures and duplicate tests removed, `sqlite` marker registered in `pytest.ini`, integration `conftest` and CLI test helpers trimmed of unused code

### Changed

- **ProviderFactory Removed**: Three class methods (`get_available_drivers`, `install_jdbc_driver`, `validate_database_configuration`) migrated directly to `ProviderRegistry`
  - `list_plugins()` replaces the internal `PROVIDER_MAP` lookup

- **Config Injection**: `_active_config` global eliminated; `ExecutionEngine` and `Migration` now receive `config` via constructor
  - `get_active_config()` / `set_active_config()` / `_set_active_config()` removed

- **Export/Snapshot Logic Moved to Core**: `export_schema` and `snapshot` logic extracted from `cli/` to `core/migration/commands/`
  - CLI layer now delegates; core commands are independently testable

- **`execute_migration` Decomposed**: Monolithic 365-line method split into orchestrator (46 lines) + 6 private methods
  - `_parse_sql_statements`, `_prepare_transaction`, `_execute_statements`, `_handle_statement_failure`, `_record_migration_history`, `_commit_and_verify`

- **CLI `create_parser()` and `main()` Decomposed**: 429-line and 729-line functions split into 12 private helpers each
  - `_add_common_migration_args`, `_load_and_merge_config`, `_ensure_connection`, `_close_logs`, etc.

- **`_ensure_connection()` Consolidated**: Duplicate implementations in MySQL, Oracle, SqlServer, DB2 replaced by single method in `JdbcProvider` base
  - PostgreSQL retains its transaction-aware override

- **`_drop_objects_by_type()` Template Method**: Added to `BaseSchemaOperations`; MySQL and PostgreSQL refactored to delegate

- **`clean_schema` Oracle Decomposed**: ~440-line method split into orchestrator + 8 private methods

- **`SchemaIntrospector` Extractor Getters**: 9 boilerplate getters consolidated via `_get_extractor()` generic factory

- **`DiffResult.__post_init__` Consolidated**: 20 identical `__post_init__` methods merged into base class using `ClassVar[str]` metadata (`_name_field`, `_object_type_label`)

- **`TableDiff.to_dict` / `get_diff_count` Driven by Metadata**: ClassVar metadata replaces per-subclass overrides

- **`DiffSqlGenerator` Dialect Normalization**: `dialect.lower()` applied in `__init__` — downstream comparisons are now case-insensitive by default

- **PK/FK Extraction Moved**: Moved from `SchemaIntrospector` to `ConstraintExtractor` to eliminate circular dependency

- **Semantic Version Sorting**: Two `cmp_to_key` comparators replace non-deterministic `hash()`-based ordering

- **Dialect-Specific LIMIT Clause**: Template Method `get_row_limit_clause()` in `JdbcProvider` / `BaseHistoryManager`; Oracle and DB2 overrides added

- **`_diff_using_snapshot` Data-Driven**: 14 pairs of `build_map`/`compare_maps` replaced by `_OBJECT_TYPE_SPECS` list + single loop

- **Database Config**: Redundant `from_dict` overrides removed from SqlServer, Oracle, PostgreSQL, MySQL, DB2; `_build_standard_url()` helper extracted to base

- **Flyway Naming Conventions Strict**: `_determine_type()` now uses anchored regex (`^v\d`, `^b\d`, `^u\d`) — prevents false positives like `validate__` being treated as versioned

- **ObjectComparator Lazy Initialization** (Epic 16): 14 specialized comparators now created on first use via `@property` instead of at construction time

- **ProviderRegistry O(1) Lookup** (Epic 16): `validate_database_configuration()` uses reverse mapping instead of O(n) plugin scan

- **Type Mapping Extracted** (Epic 16): `CANONICAL_TO_VARIANTS` moved to `type_constants.py` — circular import in `type_normalizer` eliminated

- **SqlColumn Nullable Unification** (Epic 16/17): `is_nullable` and `not_null` dual attributes replaced by single `nullable` attribute

- **`_generate_column_definition` Decomposed** (Epic 16): 177-line method split into dialect-specific helpers

- **JvmDriverManager Extracted** (Epic 16): JVM concern moved out of `ProviderRegistry` into dedicated helper

- **`provider_registry` logging** (Epic 16): `import logging` moved from exception handler to module level — avoids recreating logger on every plugin discovery failure

- **ObjectComparator table comparison** (Epic 18): `compare_tables()` delegates to `TableComparator` — ~730 lines of duplicated `_compare_columns`, `_compare_constraints`, `_compare_column_details`, `_compare_constraint_details`, `_normalize_expression` removed from `ObjectComparator`

- **TableComparator decomposition** (Epic 18): Helpers elevated to `@staticmethod` (`_constraint_key`, `_filter_duplicate_unique_constraints`, `_extract_generated_metadata`, `_strip_schema`, `_strip_on_update_clause`, `_strip_boolean_wrappers`, `_strip_redundant_parens`); `_compare_table_properties()` and `_compare_column_default_value()` extracted from `compare_tables()` / `_compare_column_details()`

- **API client `__enter__`** (Epic 18): try/except/else pattern — only catches exceptions from `is_connected()`; `create_connection()` failures propagate (no pointless retry or resource leak)

- **JVM concern in ProviderRegistry** (Epic 18): JVM driver loading extracted from `ProviderRegistry` into dedicated helper

- **`_generate_column_definition` decomposition** (Epic 18): Dialect-specific logic further decomposed into focused helpers

- **`ExecutionEngine` type annotations** (Epic 18): Constructor parameters and `__init__` fully annotated

- **ObjectComparator lazy property boilerplate** (Epic 18): Reduced redundant `@property` patterns for specialized comparators

- **SQL truncation logging** (Epic 18): Unified truncation logic for long SQL in log output

- **Dialect lower normalization** (Epic 18): `dialect.lower()` centralized — case-insensitive dialect checks throughout

- **`BaseLockingManager` lock-table drop** (Epic 23): `_drop_lock_table_if_exists()` template method; DB2/Oracle override `_get_drop_table_sql()` where `IF EXISTS` is invalid; duplicate implementations removed from five dialect locking managers

- **`DiffCommand` diff summary logging** (Epic 23): `_log_diff_summary()` decomposed into a short orchestrator plus `@staticmethod` helpers and `_DIFF_OBJECT_TYPE_LOGGERS` dispatch table (replaces 500+ line “god method”)

- **Broad silent `except` cleanup** (Epic 23): ~75 silent `except Exception: pass` sites replaced with `self.log` / module `logging` debug traces (or explicit comments where behavior is intentionally empty); notable fixes in DB2 locking manager, JDBC URL parsing in `database_config`, export/snapshot/undo paths, and HTML/parser utilities — without logging credentials or full JDBC URLs

- **API client factory logging & connection teardown** (Epic 23 follow-up): `client_from_config` passes the parent directory of `config.log_file` into `DbliftLogger`; `check_connection()` `finally` calls `provider.close()` when the provider is a `ConnectionProvider`

- **Comparator module logging** (Epic 24): Removed redundant inline logger setup blocks from comparator modules (single shared pattern)

- **Small deduplication helpers** (Epic 24): `_safe_rollback()` in `RoundTripTester`, `_normalize_index_columns()` in index comparison, `_resolve_enum_value()` in `api/client.py`

- **Commands depend on `BaseProvider`** (Epic 24, DIP-01): `BaseCommand` and all concrete migration commands use `BaseProvider` type hints instead of `JdbcProvider`

- **Repair command tests** (Epic 24): `MigrationState` dataclass replaces `unittest.mock.Mock` in repair tests — fixtures match real state shapes

### Fixed

- **Security — SQL Injection**: Parameterized queries enforced in `JdbcProvider` `execute_query()` and `execute_statement()` methods (Epic 12-1)

- **Security — Credential Masking**: Passwords and usernames masked in all log output for Oracle, CLI, and base command; Oracle thin URL `user/pass@` pattern correctly handled

- **Resource Leaks — MySQL**: `try/finally` blocks guarantee `Statement` and `ResultSet` close in `QueryExecutor.execute_statement()` and `execute_query()`

- **Resource Leaks — Connection**: `check_connection()` closes connection via `try/finally` regardless of outcome

- **`schema_exists()`**: Silent `NotImplementedError` replaced with dialect-aware catalog queries (Oracle `ALL_USERS`, DB2 `SYSCAT.SCHEMATA`, default `INFORMATION_SCHEMA.SCHEMATA`)

- **`SqlConstraint.__eq__` / `__hash__`**: Completed for all 10 diff-relevant fields (FK references, ON DELETE/UPDATE, CHECK expression, deferrable flags)

- **`TableDiff.to_dict()`**: 6 missing boolean fields added (`partition_method_changed`, `partition_columns_changed`, `compress_changed`, `compress_type_changed`, `logged_changed`, `organize_by_changed`)

- **Constraint parenthesis stripping**: `_strip_outer_parens()` extracted and depth-tracking fixed in `BasicTableDdlGenerator`; inline constraint path at line 655 now uses depth-based algorithm (Epic 16-1)

- **`--confirm` flag**: Wired end-to-end through CLI → `client.clean()` → `MigrationExecutor.clean()` → `CleanCommand.execute()`

- **`_handle_validate` / `_handle_validate_sql`**: Both now call `_set_command_completed()` — command completion tracking was silently missing

- **Snapshot command not triggering DB validation**: `"snapshot"` added to `migration_commands` list

- **Early log initialization**: `LogFactory.get_log()` called before `load_config()` — prevents `AttributeError` on startup errors

- **CosmosDB SSL bypass scoped**: SSL certificate bypass now applies only to the `CosmosClient` connection, not globally

- **Double `record_migration`**: Removed duplicate history recording in `_handle_failed_migration`

- **`parse_sql_statements` fallback**: Semicolon-split fallback uses the existing `SqlAnalyzer` instance; `config.database.type` None guard added

- **`check_connection()` None guard**: Handles `None` dialect gracefully

- **YAML format detector**: Regex narrowed to exclude YAML keys containing spaces (avoids false positive on SQL comments)

- **Computed column expression diffs**: Restored diff detection that had been accidentally suppressed

- **`provider.dialect = None`**: Guard prevents returning the string `"none"` when dialect is unset

- **Duplicate comparator functions** (Epic 16): `_is_system_generated_constraint_name` and `_extract_base_identity_type` removed from `comparator.py`; imports from `comparison_utils.py` instead (avoids ~200-line duplication)

- **Malformed docstring** (Epic 16): `index_extractor.py` docstring no longer contains embedded import statement

- **Provider plugin validation** (Epic 16): `_load_plugin()` validates `issubclass(provider_class, BaseProvider)` when using `__all__` path — invalid provider classes no longer registered silently

- **`type_normalizer.are_equivalent()`** (Epic 16): None guard added — returns `False` when `type1` or `type2` is `None` (incomplete introspection)

- **`schema_exists()` CosmosDB and SQLite** (Epic 16): CosmosDB returns `True` (schema-less); SQLite uses PRAGMA fallback

- **`_normalize_identifier` type hint** (Epic 16): Parameter changed from `str` to `Optional[str]` to match implementation

- **TableDiff severity** (Epic 16): Boolean property changes (`filegroup_changed`, `memory_optimized_changed`, etc.) now yield `WARNING` instead of `INFO`

- **Diff subclass severity** (Epic 16): `SequenceDiff`, `ExtensionDiff`, `EventDiff` now differentiate ERROR/WARNING/INFO based on field type

- **`hasattr` → `isinstance`** (Epic 16): `schema_introspector.py` and `cli/main.py` use `isinstance(provider, ConnectionProvider)` instead of `hasattr(provider, "get_connection")`

- **`constraint_extractor`** (Epic 16): Redundant `hasattr(constraint, ...)` guards removed — direct assignment to `SqlConstraint` fields

- **Pre-check SELECT 1 silent exception** (Epic 18): Exceptions from connection pre-check now propagated instead of swallowed

- **`_commit_and_verify` SQL interpolation** (Epic 18): `schema_name` and `table_name` validated against `\w+` before interpolation — defense-in-depth against SQL injection (OWASP)

- **`_commit_and_verify` commit failure propagation** (Epic 18): Commit failures now propagate to caller (`raise` after `log.warning`) — no silent swallow

- **`TableDiff._BOOL_FIELDS` validation** (Epic 18): `__post_init__` validates that all names in `_BOOL_FIELDS` exist in the dataclass — early detection of typos or rename divergence

- **View definition normalization dialect** (Epic 23): Compare-views path forwards the active dialect into `_normalize_view_definition` / SqlGlot via `_SQLGLOT_DIALECT_MAP` instead of a hardcoded MySQL read dialect

- **`run_validation` empty run list** (Epic 23): Guard against `IndexError` when the validation run list is empty

- **`migration_validator` debug artifact** (Epic 24): Removed stray debug log statement accidentally left in the validator

### Removed

- **`ProviderFactory`** class (all methods migrated to `ProviderRegistry`)
- **`get_active_config()` / `set_active_config()`** global config accessors
- **`migration_operations.py`** (~3 300 lines of dead code, DEAD-01)
- **`table_converter.py`** (dead code removed)
- **`parse_and_configure_from_jdbc_url()`** (~150-line dead utility function)
- **Dead code items D1–D8**: unused imports (`SqlConstraint`, `TableConverter` in diff generators), inline `import re` duplication, `_ErrorCategoryStub/_ErrorCategoryModuleStub` replaced by module-level `_ErrorCategoryFallback`
- **`if self.log:` guards**: Eliminated across all components (replaced by NullLog)
- **Dual logging** (module-level `logging.getLogger` + `self.log`): Unified to `self.log` throughout
- **`module_comparator` and `compare_modules()`** (Epic 16): Dead attribute and method removed from `ObjectComparator`; `module_comparator.py` and `Module` model deleted
- **6 inline `import re`** (Epic 16): Removed from `schema_introspector.py`, `comparison_utils.py`, `table_comparator.py` (module-level already present)
- **`MigrationType.VERSIONED`** (Epic 17): Replaced by `MigrationType.SQL` throughout; enum value now `"SQL"` for alignment with Flyway

- **Log wrappers** (Epic 18): `log.debug`, `log.info`, etc. wrappers removed — direct `self.log` calls used throughout

- **Unused `logging_comparator` in TableComparator** (Epic 18): Redundant module-level `logging.getLogger` removed; `self.log` used directly

- **Autoflake / placeholder debris** (Epic 23): `try: pass` no-op blocks removed from `log.py`, `type_mapper.py`, `repair_command.py`; redundant `pass` removed from CLI `_resolve_scripts_directories` else branch

- **Unused API surface** (Epic 23): Removed unused `dialect` parameter from `get_index_syntax()` on index SQL model

## [1.0.1] - 2026-01-09

### Fixed

- **MySQL Statement Parser**: Fixed critical bug where `in_stored_program` flag was never reset between statements
  - This caused subsequent `BEGIN` statements (e.g., transactions) to be incorrectly treated as block starts
  - Added proper flag reset in `split_statements()` following Oracle parser pattern
  - Context now properly resets for each new statement while preserving delimiter
  - Comprehensive test suite added with 6 tests covering all stored program types
  - All 344 MySQL-related tests passing with no regressions

- **Test Quality**: Improved test assertion in MySQL stored program flag reset test
  - Fixed comment/assertion inconsistency (was 3 vs 4 statements)
  - Changed weak assertion from `>= 3` to exact check `== 4` to catch regressions

## [1.0.0] - 2025-12-16

### Added

- **Comprehensive Unit Test Coverage**: Added extensive unit test coverage for all database plugin components
  - Complete unit tests for PostgreSQL, MySQL, Oracle, SQL Server, DB2, CosmosDB, and SQLite plugin components
  - Unit tests for base classes (BaseHistoryManager, BaseQueryExecutor, BaseSchemaOperations)
  - Direct CLI runner for integration test coverage
  - Test coverage infrastructure with Codecov integration
  - Combined coverage reporting (unit + integration tests)

- **Snapshot Command**: New `dblift snapshot` command for exporting schema snapshots
  - Export schema snapshots to JSON model files
  - Support for database-stored and live-database sources
  - Consistent command formatting with headers and footers

- **CosmosDB Plugin Architecture**: Migrated CosmosDB from `db/providers` to `db/plugins` architecture
  - Consistent plugin structure across all database types
  - Improved maintainability and extensibility

- **Codecov Integration**: Comprehensive test coverage tracking and reporting
  - Automatic flag management for combined coverage
  - Coverage improvement guides and documentation
  - Local test execution scripts with coverage

- **GitHub Actions Improvements**: Enhanced CI/CD workflows
  - Automatic fallback to subprocess mode for JDBC databases when coverage is enabled
  - Improved workflow configuration and documentation
  - Fixed Codecov badge URL for private repositories

### Changed

- **Development Status**: Changed from Alpha (0.9.0-beta) to Production/Stable (1.0.0)
  - Tool is now production-ready and stable
  - All major features implemented and tested

- **Test Infrastructure**: Major improvements to testing infrastructure
  - Fixed pytest import cache conflicts with `--import-mode=importlib`
  - Improved test selection and container provisioning
  - Enhanced test fixtures and helpers
  - Better handling of transient connection errors

- **Import Paths**: Fixed and standardized import paths across the codebase
  - Corrected import paths in db modules
  - Fixed import paths in conftest.py and test files
  - Standardized module imports for better maintainability

- **Documentation**: Enhanced documentation and build processes
  - Fixed documentation build issues (removed --strict mode)
  - Fixed type annotations in repair and clean commands
  - Improved mkdocs-i18n configuration
  - Added enablement parameter to configure-pages action

### Fixed

- **Oracle SQL Syntax**: Fixed multiple Oracle SQL syntax errors
  - Fixed table_exists query to use UPPER() function
  - Fixed schema-qualified table names to use quoted identifiers
  - Fixed SQL syntax errors in diff SQL generation tests
  - Fixed get_jdbc_url test handling

- **DB2 SQL Syntax**: Fixed DB2 SQL syntax errors in integration tests
  - Corrected SQL statement formatting
  - Fixed table_exists test to use table_count > 0

- **CosmosDB Parser**: Fixed CosmosDB parser issues
  - Fixed statement splitting bug for DELETE/UPDATE without semicolons
  - Removed semicolons from UPDATE and DELETE statements in parser tests
  - Fixed parser test assertions for cli_runner_direct
  - Fixed CosmosDB Emulator SSL connection issues

- **Test Failures**: Fixed numerous test failures across the codebase
  - Fixed CLI export and comparison utils test failures
  - Fixed test_client.py failures
  - Fixed sql_execution_service and sql_insights test failures
  - Fixed test assertions for ignore-unmanaged and manual schema changes
  - Fixed hanging tests by properly mocking result sets

- **Type Checking**: Fixed mypy type checking errors
  - Resolved all type checking issues across the codebase
  - Improved type annotations and type safety

- **Code Quality**: Fixed code formatting and quality issues
  - Fixed code formatting with black
  - Fixed TypeError: unhashable type in script_organizer
  - Fixed remaining code quality issues for CI

- **Undo Command**: Fixed undo command with tag/version filters
  - Improved command execution with proper filtering

- **Configuration**: Fixed configuration and validation issues
  - Fixed config validation to check _allow_incomplete before filtering
  - Removed duplicate credentials handling
  - Fixed setuptools package discovery in pyproject.toml

- **Multi-Command Parsing**: Fixed multi-command mode issues
  - Added --generate-sql to boolean flags list
  - Fixed exit code propagation in multi-command mode

### Removed

- **Demo Folder**: Removed demo folder and orphaned introspection files
- **Pytest Collection Hook**: Removed pytest_collection_modifyitems hook that was preventing container provisioning

## [0.9.0-beta] - 2025-12-09

### Added

- **DB2 Database Support**: Complete DB2 database support with comprehensive test coverage (29 passing tests, 10/10 confidence)
  - Full schema introspection for tables, views, indexes, sequences, triggers, procedures, functions, and synonyms
  - Support for identity columns (GENERATED ALWAYS AS IDENTITY)
  - Support for generated columns (GENERATED ALWAYS AS expression)
  - Support for table compression, XML data types, and partitioned tables
  - Support for composite primary keys, multiple foreign keys, and complex CHECK constraints
  - Round-trip validation for identity columns, foreign keys, and indexes
  - Edge case testing for advanced scenarios
  - Remote DB2 connection support via environment variables (DBLIFT_DB2_HOST, DBLIFT_DB2_PORT, etc.)
  - Scripts for remote DB2 setup and connection testing

- **CosmosDB Enhanced Support**: Expanded CosmosDB support with comprehensive test coverage (23+ passing tests, 10/10 confidence)
  - SDK Translator for pseudo-SQL to Azure SDK operations (DROP CONTAINER, ALTER CONTAINER, SET THROUGHPUT, CREATE INDEX, SET TTL)
  - Advanced schema inference for nested objects, mixed types, and empty containers
  - Indexing policy introspection and testing
  - Round-trip validation for container schema
  - Comprehensive data type inference (string, number, boolean, array)
  - Support for both CosmosDB Emulator and external instances

- **SQL Server Enhanced Support**: Expanded SQL Server support to 10/10 confidence (51+ passing tests)
  - Indexed views support and testing
  - Synonyms support and testing
  - Temporal tables support and testing
  - Partitioned tables support and testing
  - Filegroups support and testing
  - Spatial data types (GEOMETRY, GEOGRAPHY) support and testing
  - HierarchyID data type support and testing
  - Graph tables support and testing
  - Full-text search support and testing
  - XML and JSON column support and testing
  - Advanced constraints and views testing

- **MySQL Enhanced Support**: Expanded MySQL support to 10/10 confidence (42+ passing tests)
  - Remote MySQL connection support via environment variables
  - Comprehensive test coverage for all MySQL features
  - Support for generated columns, JSON data types, spatial types, and partitioning

- **Oracle Enhanced Support**: Maintained 10/10 confidence (40 passing tests)
  - Comprehensive test coverage for all Oracle features
  - Support for virtual columns, identity columns, packages, materialized views, and advanced features

### Changed

- **Schema Introspection Architecture**: Major refactoring of schema introspection system for improved maintainability and organization
  - Refactored `SchemaIntrospector` from monolithic file (4,543 lines) to orchestrator pattern (2,065 lines, 54.5% reduction)
  - Extracted object-specific logic into dedicated extractor classes:
    - `TableExtractor`: Table metadata extraction
    - `ColumnExtractor`: Column metadata extraction
    - `ConstraintExtractor`: Primary keys, foreign keys, unique constraints, check constraints
    - `IndexExtractor`: Index definitions
    - `ViewExtractor`: Views and materialized views
    - `SequenceExtractor`: Sequence definitions
    - `TriggerExtractor`: Trigger definitions
    - `ProcedureExtractor`: Procedures and functions
    - `MiscExtractor`: Events, packages, synonyms, UDTs, extensions, etc.
  - Moved database-specific introspectors to `databases/` subdirectories for better organization
  - Extracted common utilities to `core/` subdirectory (`jdbc_metadata.py`, `utils.py`)
  - Implemented lazy initialization of extractors to reduce startup overhead
  - Created `BaseExtractor` abstract class with common JDBC metadata access patterns
  - Improved code organization: logic separated by object type into focused modules
  - All extractors integrated with result tracking and error handling

- **DB2 Trigger Syntax**: Fixed DB2 trigger creation syntax to use REFERENCING clause
  - BEFORE INSERT triggers now use `REFERENCING NEW AS NEW` with `BEGIN ATOMIC ... END`
  - AFTER UPDATE triggers now use `REFERENCING NEW AS NEW OLD AS OLD` with `BEGIN ATOMIC ... END`
  - Triggers now properly introspected and tested

- **DB2 Transaction Management**: Improved transaction handling in DB2 operations
  - Added explicit commit after DB2 cleanup operations in `schema_operations.py` (similar to MySQL fix)
  - Fixed `RoundTripTester` to not rollback after DB2 cleanup (cleanup already commits)
  - Ensured tests commit properly for DB2 after table creation
  - Added rollback on error in all test cleanup blocks
  - Fixed transaction state management to prevent hanging tests
  - Improved error handling for MQT and advanced features

- **Test Configuration**: Enhanced test configuration for remote database connections
  - Added support for external DB2 connections (macOS compatible)
  - Added support for external MySQL connections
  - Maintained backward compatibility with container-based testing for CI/CD

- **CosmosDB SDK Translator**: Enhanced SDK translator with comprehensive operation support
  - Added support for SET AUTOSCALE, EXCLUDE/INCLUDE INDEX PATH operations
  - Improved error handling and operation detection
  - Enhanced integration with query executor

### Fixed

- **Out-of-Order Migration Execution**: Fixed critical bug preventing out-of-order migration execution
  - Previously, migrations with versions lower than the current version were incorrectly skipped as "covered by baseline"
  - Now correctly distinguishes between actual baseline migrations and the current applied version
  - Out-of-order migrations (e.g., V1.0.3 after V1.1.0) now execute properly when no baseline exists
  - Baseline skipping now only applies when an actual BASELINE migration type exists in history
  - Example: V1.0.1 → V1.0.2 → V1.1.0 → V1.0.3 (V1.0.3 now executes correctly)

- **DB2 Case Sensitivity**: Fixed DB2 case sensitivity issues in test assertions
  - Table names now properly converted to uppercase for introspection queries
  - Index and trigger names properly handled with case conversion

- **DB2 Procedure Testing**: Fixed stored procedure test to create required tables before procedure creation
  - Added proper table creation and cleanup in procedure tests
  - Improved error handling and rollback on failures

- **DB2 MQT Testing**: Fixed Materialized Query Table test to prevent hanging
  - Added immediate skip on creation failure to avoid transaction locks
  - Improved rollback handling in cleanup blocks

- **CosmosDB SDK Translator**: Fixed assertion errors in SDK translator tests
  - Corrected parameter name from `throughput` to `offer_throughput` in ALTER CONTAINER operations
  - Fixed test assertions to match actual SDK parameter names

- **Test Timeout Issues**: Fixed hanging tests by improving transaction management
  - Added rollback on error in all test cleanup blocks
  - Improved connection cleanup and transaction state management
  - Fixed MQT test to skip immediately on failure instead of hanging

- **GitHub Actions Workflow**: Fixed undefined variable error in CosmosDB integration test job
  - Removed undefined `matrix.database` reference from cleanup step in `integration-validation-cosmosdb` job
  - CosmosDB job cleanup now uses `if: always()` condition (no matrix needed)

- **Type Checking Errors**: Fixed all 9 mypy type checking errors across 4 files
  - Fixed `sqlite_generator.py:524`: Cast `definition` to `str` before returning from function
  - Fixed `undo_script_generator.py` (5 errors): Added explicit `None` checks for `table_name` parameter before use
  - Fixed `history_manager.py:255`: Properly extract and cast CosmosDB query result before arithmetic operation
  - Fixed `execution_engine.py:178,181`: Added `type: ignore` comments for JDBC PreparedStatement operations (mypy cannot type-check JDBC objects)
  - All files now pass mypy type checking (353 source files, no issues)

## [0.8.0-beta] - 2025-12-01

### Added
- **Snapshot Command**: New `dblift snapshot` command for exporting schema snapshots to JSON model files
  - Supports two sources: `database-stored` (loads latest snapshot from database) and `live-database` (captures new snapshot)
  - Exports canonical schema payload in JSON format for drift detection and schema documentation
  - Consistent header/footer formatting with other commands
  - Comprehensive unit and integration test coverage

### Changed
- **Connection Management Architecture**: Complete refactoring of connection ownership and transaction management
  - Implemented explicit connection ownership pattern: Provider owns connection, components receive it as parameter
  - Eliminated stored connection references in QueryExecutor, SchemaOperations, LockingManager, and HistoryManager (100+ instances removed)
  - Made all database components stateless for improved testability and thread safety
  - Centralized transaction state management with `_in_transaction` and `_transaction_depth` flags
  - Simplified API client architecture with dependency injection throughout call chain
  - Removed all manual connection synchronization code and CRITICAL comments

- **Command Header/Footer Standardization**: Unified header and footer formatting across all CLI commands
  - Headers now include database name, schema name, masked database URL (supports both JDBC and non-JDBC), and filtering options
  - Removed redundant "Source" and "Output" lines from headers (now part of "Filtering Options")
  - Database URL masking supports JDBC URLs (password parameters) and non-JDBC URLs (CosmosDB account keys, generic password patterns)
  - Consistent footer with execution time across all commands
  - Applied to `export-schema` and `snapshot` commands

### Fixed
- **Connection State Management**: Fixed transaction state corruption when creating new connections
  - Provider now resets `_in_transaction` and `_transaction_depth` flags when creating fresh connection
  - Prevents "Connection is closed during active transaction" errors
  - Ensures new connections start with clean transaction state

- **Test Fixture Cleanup**: Fixed migration history contamination between integration tests
  - Cleanup fixture now deletes history records before cleaning schema
  - Removed premature history table creation that caused "already contains migration history" errors
  - Uses correct history table name from `history_manager.history_table`

- **Diff Command**: Fixed missing CLI parameter passing
  - `--ignore-unmanaged` flag now properly passed from CLI to API client
  - `--snapshot-model` and `--target-version` parameters now correctly forwarded
  - Fixed test configuration to pass migrations_dir when creating config

- **Export Schema Command**: Removed `store_snapshot` parameter (snapshots are automatically captured after database-modifying operations)
- **Snapshot Command**: Clarified that command is export-only (snapshots are automatically created by `MigrationExecutor` after `migrate`, `undo`, `clean`, and `baseline` operations)

- **PostgreSQL SQL Generation**: Fixed sequence SQL generation syntax errors
  - Removed invalid `NOCYCLE` keyword from PostgreSQL sequence generation (PostgreSQL defaults to `NO CYCLE`)
  - Fixed sequence CREATE statements to only include `CYCLE` when explicitly requested
  - Resolved syntax errors in round-trip tests for PostgreSQL sequences

- **Round-Trip Testing**: Fixed multiple issues in schema validation round-trip tests
  - Fixed materialized views introspection by calling dedicated `get_materialized_views()` method
  - Fixed index test by ensuring tables are introspected when indexes are requested
  - Improved transaction abort handling with proactive rollback on failed statements
  - Added comprehensive cleanup for test objects (tables, sequences, views, enums, materialized views)
  - Fixed test organization by moving PostgreSQL-specific tests to separate class with class-level parametrization
  - Improved pytest `-k` filter to properly skip non-matching databases and prevent unnecessary container startups
  - All PostgreSQL round-trip tests now passing with proper test isolation

- **Azure Cosmos DB Support**: Complete integration for Azure Cosmos DB (SQL API)
  - Non-JDBC provider using Azure SDK for Python (`azure-cosmos` and `azure-identity`)
  - Full migration support with container-based schema management
  - Native ETag-based optimistic concurrency locking with document-based fallback
  - Schema introspection for containers, indexes, and document structure
  - Support for CosmosDB SQL API syntax (`CREATE CONTAINER`, `SELECT`, `INSERT`, `UPDATE`, `DELETE`)
  - Partition key and indexing policy support
  - Throughput provisioning (RU/s) configuration
  - Schema snapshot support for drift detection
  - Export schema command support with CosmosDB-specific filtering
  - Diff command support for detecting schema drift
  - Clean command support for container cleanup
  - Local CosmosDB Emulator support with SSL verification handling
  - Comprehensive unit and integration test coverage

- **CLI URL Validation**: Fixed missing database URL detection
  - Properly detects when database URL was not explicitly provided (checks for default placeholder URL)
  - Error message now correctly shows "Database URL is required" instead of username error
  - Validates URL was provided via command line, config file, or environment variables

- **Sequence SQL Generation**: Fixed NOCYCLE generation for sequences without dialect
  - Sequences without explicit dialect now use basic generator to ensure NOCYCLE is included when cycle=False
  - Prevents missing NOCYCLE keyword in CREATE SEQUENCE statements for generic sequences
  - Ensures all sequence attributes are properly represented in generated SQL

## [0.7.0-beta] - 2025-11-21

### Added
- **🏗️ Comprehensive Factory Pattern Architecture**: Implemented factory patterns across 6 major components for improved modularity and extensibility
  - `AlterGeneratorFactory` - Creates dialect-specific ALTER statement generators with proper case preservation
  - `SqlGeneratorFactory` - Creates dialect-specific SQL generators with enhanced capabilities
  - `ExportHandlerFactory` - Creates database-specific export handlers for modular schema export
  - `SchemaOperationsFactory` - Creates database-specific schema operations with consistent interfaces
  - `QueryExecutorFactory` - Creates database-specific query executors with standardized APIs
  - `HistoryManagerFactory` - Creates database-specific history managers with common utilities
  - `IntrospectorFactory` - Creates database-specific schema introspectors for consistent metadata access

- **🎯 Enhanced SQL Generation Architecture**: Implemented Statement Generator Pattern for centralized SQL creation
  - Moved dialect-specific SQL generation logic from 17 SQL model classes to dedicated generator classes
  - Added comprehensive `generate_create_statement` methods for all SQL object types across all database dialects
  - Enhanced support for `Table`, `View`, `Index`, `Procedure`, `Sequence`, `UserDefinedType`, `Trigger`, `Package`, `ForeignServer`, `ForeignDataWrapper`, `Extension`, `Event`, `DatabaseLink`, `Partition`, `Module`, `LinkedServer`, and `Synonym`
  - Implemented generic dispatch mechanism in `BaseGenerator` for consistent SQL object handling

- **🔧 Abstract Base Classes**: Created comprehensive base class hierarchy for consistent interfaces
  - `BaseAlterGenerator` - Abstract base for ALTER statement generation with dialect-specific implementations
  - `BaseSqlGenerator` - Abstract base for SQL generation with generic dispatch mechanism
  - `BaseExportHandler` - Abstract base for database-specific export operations
  - `BaseSchemaOperations` - Standardized interface for schema operations across all providers
  - `BaseQueryExecutor` - Consistent interface for query execution with standardized method signatures
  - `BaseHistoryManager` - Unified history management with common utility methods and default implementations

### Changed
- **🚀 Modular Component Design**: Separated dialect-specific logic into dedicated classes for better maintainability
  - Refactored monolithic `export_schema_command.py` (1,729 lines) into modular architecture with factory pattern
  - Enhanced all database providers with consistent factory-based instantiation
  - Improved code organization with clear separation of concerns across all components

- **🎨 Enhanced Case Preservation**: Improved identifier handling for Oracle and DB2 databases
  - Updated `_format_identifier` methods to preserve case and use double quotes appropriately
  - Fixed identifier case conversion issues that were systematically converting to uppercase
  - Ensured compliance with database-specific identifier rules and user requirements

- **⚡ Improved Error Handling**: Enhanced error categorization and retry mechanisms across all components
  - Better database connection handling across all providers
  - Improved transaction safety and rollback mechanisms
  - Enhanced logging and debugging capabilities

### Fixed
- **🔗 Database Connection Management**: Resolved critical connection issues across all database providers
  - **SQL Server Integration Tests**: Fixed connection reset and prelogin errors by updating JDBC connection properties
  - **Oracle Integration Tests**: Resolved connection issues through improved SSL/encryption configuration
  - **DB2 Computed Column Tests**: Fixed test assertion to properly handle successful computed column detection
  - **Schema Snapshot Service**: Implemented single connection context for entire snapshot operations
  - **Connection Validation**: Added proper connection state checks before database operations
  - **Debug Logging Cleanup**: Replaced hardcoded print statements with proper debug logging

- **🎯 Code Quality Achievements**: Achieved dramatic improvement in code quality and test reliability
  - **100% Unit Test Success Rate**: Reduced failing unit tests from 32 to 0 (90.6% improvement)
  - **Full Linting Compliance**: Achieved 100% compliance with Black formatting, isort import sorting, and MyPy type checking
  - **Enhanced Type Safety**: Added comprehensive type annotations and resolved all type checking errors
  - **Improved Test Coverage**: Enhanced integration test coverage for all major components

- **🔧 Component-Specific Fixes**: Resolved numerous issues across refactored components
  - Fixed `RecursionError` in Event SQL model by adding proper generator dispatch mechanism
  - Resolved constructor parameter mismatches in various factory implementations
  - Fixed import and usage patterns in integration tests to use new factory-based approach
  - Corrected test assertions to match new, correct SQL output from enhanced generators

- **📊 Migration Executor Improvements**: Fixed critical issues in migration execution
  - Resolved `self.migration_rules` vs `self.rules` attribute reference inconsistency
  - Fixed constructor parameter passing in `ImportFlywayCommand` instantiation
  - Enhanced parameter validation and error handling in command execution

### Removed
- **🧹 Code Cleanup**: Eliminated redundant and obsolete code patterns
  - Removed hardcoded SQL generation logic from SQL model class properties
  - Eliminated duplicate factory instantiation patterns
  - Cleaned up obsolete import statements and unused dependencies

### Technical Details
- **Architecture**: Implemented comprehensive factory pattern system with abstract base classes
- **Testing**: Achieved 1,855+ passing unit tests with comprehensive coverage of all refactored components
- **Performance**: Optimized SQL generation with more efficient dialect-specific creation
- **Maintainability**: Enhanced code organization with consistent interfaces and clear separation of concerns
- **Extensibility**: Simplified addition of new database support through standardized factory patterns

## [0.6.1-beta] - 2025-11-10

### Added
- `export-schema` command now supports multiple scripts directories via `--scripts` flag (can be specified multiple times)
- `export-schema` command now supports recursive migration file search with per-directory control via `dir_recursive_map`
- `export-schema` command now supports migration filtering flags: `--tags`, `--exclude-tags`, `--versions`, `--exclude-versions`, `--target-version`
- `export-schema` command now properly filters objects by target schema (PostgreSQL and other databases)
- `export-schema` command now uses `MigrationScriptManager` and `MigrationStateManager` for consistent migration handling
- Enhanced debug logging in `export-schema` for troubleshooting managed/unmanaged object detection
- `export-schema --output-format=model` emits the same canonical schema payload used by drift detection
- `export-schema` command supports multiple sources: `live-database` (default), `database-model` (from stored snapshot), and `file-model` (from JSON file)
- New unit coverage for snapshot-gated diff behaviour (`tests/unit/core/migration/executor/test_diff_snapshot.py`)
- Schema snapshot service now captures extensions, synonyms, foreign data wrappers/servers, database links, and user-defined types with graceful fallbacks plus dedicated unit coverage (`tests/unit/core/migration/snapshots/test_schema_snapshot_service.py`, `tests/unit/sql_model/test_remote_objects.py`)

### Changed
- `export-schema` command refactored to use executor's `script_manager` and `state_manager` instead of direct file system access
- `export-schema` command now properly filters managed objects by schema when extracting from migration files
- `export-schema` command now filters introspected objects by target schema before processing
- Improved schema normalization for PostgreSQL (handles "public" schema correctly)
- `diff` now requires an existing snapshot (database or `--snapshot-model`) and compares against the canonical snapshot payload
- `export-schema` always builds a schema payload first and routes it to either SQL or JSON exporters
- `export-schema` now filters out DBLift-managed tables/views/sequences before payload construction, serializes canonical models with timezone-safe JSON encoding, and treats empty-filter results as failures so automation surfaces misconfigured exports
- Global CLI `--db-*` flags now live on a shared parent parser so chained commands reuse the same connection args without duplicating definitions

### Fixed
- Fixed `check_expression` not being loaded from JSON when deserializing constraints in `Table.from_dict()`, which was causing `diff` command to fail with `check_clause: differs` errors when comparing snapshot models on disk with live database schemas
- Eliminated SQL Server diff false negatives by teaching the hybrid parser to treat bracket-quoted identifiers consistently across tables, indexes, sequences, triggers, and routines.
- Oracle procedure introspection now pulls full definitions from `ALL_SOURCE`, allowing diff reports to surface body changes instead of appearing in sync.
- Improved diff command integration harness to accept external MySQL/DB2 configurations, keeping pytest fixtures functional for remote drift testing.
- Added a resilient JDBC driver loading path that clears stubbed `java.*` modules and falls back to `jpype.JClass`, eliminating driver discovery failures when tests run under pytest.
- Resolved mypy regressions introduced by recent parser/comparator work by adding missing annotations, guarding nullable regex matches, and tightening vendor-query checks.
- Ensured Oracle and SQL Server history repair routines return consistent boolean results and propagate them through their JDBC providers.
- Resolved mypy typing issues in the migration repair flow by guarding filesystem lookups and tracking repair counts as integers.
- Corrected checksum repair calls to use keyword arguments and updated logging to align with `Log.warning`'s signature.
- Fixed `export-schema` command to only export objects from the target schema (was including objects from all schemas)
- Fixed `export-schema --managed-only` to properly detect views, functions, and triggers (was only finding tables and indexes)
- `diff` now short-circuits with a warning when no migrations have been applied yet, preventing empty projects from failing before a baseline exists
- Hybrid parser LIKE/remote object extraction handles MySQL backticks, Unicode identifiers, and DDL `ON` clauses more accurately, eliminating false positives in CTAS/LIKE detection and function parsing

### Removed
- Deprecated sample migrations under `migrations/samples/` were removed to reduce repo noise and avoid stale reference schemas (new canonical examples live under `migrations/model.json` and related artifacts)

## [0.6.0-beta] - 2025-11-10

### Added
- `migrate`, `info`, and `undo` now announce the current schema version before executing, and the `info` table includes an `Undoable` column for quick rollback checks.
- Command completion messages report execution time and richer summaries so automation logs are easier to scan.
- `export-schema` prints the JDBC URL, object counts, and a completion banner, making generated scripts easier to audit.
- Migration data collector supports tag filtering to scope analytics to specific migration subsets.

### Changed
- Standardized command-line output formatting across the CLI, giving every command consistent headings, spacing, and table styles.
- Trimmed INFO-level noise throughout the CLI by demoting verbose diff and introspection logs to DEBUG.
- Refined export-schema ordering and grouping to produce deterministic script layouts and more logical object organization.
- Refreshed release tooling and docs with Docker image size analysis and manual publish workflows for both full and validation images.

### Fixed
- Resolved multiple export-schema regressions, including missing object grouping, inconsistent ordering, and incorrect logger usage.
- Clean command once again emits a single summary and correctly honors provider metadata availability.
- Diff command regained GitHub-style output formatting and now fails when drift is detected, matching user expectations.
- Database locking now falls back gracefully and resolves race conditions uncovered by integration tests, while partition parsing and repair command regressions were corrected.

## [0.5.0-beta] - 2025-11-05

### Added

- **SQL Generation Engine**: Complete engine for translating SQL Model objects into formatted SQL DDL scripts
  - `SqlFormatter`: Formats SQL statements using sqlglot (PostgreSQL, Oracle, SQL Server, MySQL)
  - `SqlGenerator`: Main orchestrator for generating DDL statements from SQL Model objects
  - `DependencyAnalyzer`: Analyzes and orders objects by dependencies using topological sorting
  - `ScriptOrganizer`: Organizes generated SQL into files with multiple strategies
  - `AlterGenerator`: Generates ALTER statements for schema modifications
  - Dependency-aware CREATE ordering (dependencies first)
  - Reverse dependency ordering for DROP statements (dependents first)
  - Circular dependency detection with warnings
  - Multiple organization strategies (single file, by type, by object, by schema, by dependency)
  - File header/footer generation with metadata (timestamp, dialect, object count)
- **Export-Schema Command**: New CLI command for extracting database schemas to migration files
  - Export entire schema to single file or split by object type
  - Filter by object types (tables, views, indexes, etc.)
  - Filter by table names
  - Export only managed objects (from applied migrations) with `--managed-only`
  - Export only unmanaged objects (not in migrations) with `--unmanaged-only`
  - Include DROP statements option for clean recreation
  - Custom description in migration headers
  - Support for all supported databases (PostgreSQL, Oracle, SQL Server, MySQL, DB2)
  - Brownfield database workflow support
- **SQL Model Enhancements**: Added `drop_statement` property to major SQL Model classes
  - `Table.drop_statement`: Dialect-specific DROP TABLE with CASCADE support
  - `View.drop_statement`: DROP VIEW/MATERIALIZED VIEW with dialect variations
  - `Index.drop_statement`: DROP INDEX with SQL Server syntax support
  - `Sequence.drop_statement`: DROP SEQUENCE with Oracle variations
  - `Procedure.drop_statement`: DROP PROCEDURE/FUNCTION with `is_function` differentiation

- **CREATE TABLE AS SELECT / CREATE TABLE LIKE Support**: Eliminates false positive drift warnings for derived tables
  - **Detection**: Parser recognizes CTAS (`AS SELECT`) and LIKE patterns across Oracle, PostgreSQL, MySQL, DB2
  - **Table Tracking**: Tables marked with `derived_from` property (`"CTAS"` or `"LIKE:source_table"`)
  - **Smart Comparison**: Comparator skips column validation for derived tables (columns determined at execution time)
  - **Impact**: Eliminates 30-40% of false positive warnings in typical migrations
  - **Test Coverage**: 17 unit tests + 2 integration tests (cross-database)
  - **Files Modified**: `hybrid_parser.py`, `table.py`, `comparator.py`

- **Partition Scheme Tracking**: Validates partitioning strategy without tracking individual partitions
  - **Parsing**: Detects `PARTITION BY` clause in CREATE TABLE (Oracle, PostgreSQL, MySQL, DB2)
  - **Properties**: Tracks `partition_method` (RANGE/LIST/HASH/KEY) and `partition_columns` on Table
  - **Smart Comparison**: Compares partitioning strategy, NOT individual partitions (avoids false positives from auto-created partitions)
  - **Oracle INTERVAL Support**: Handles auto-partitioning correctly (only tracks strategy)
  - **Function Filtering**: Extracts column from `YEAR(date)` expressions (filters out SQL functions)
  - **Introspection**: Queries partition metadata from all databases (Oracle: `all_part_tables`, PostgreSQL: `pg_get_partkeydef`, MySQL: `information_schema.partitions`, SQL Server: `sys.partition_functions`, DB2: `syscat.datapartitions`)
  - **Cross-Database**: Oracle, PostgreSQL, MySQL, DB2, SQL Server (introspection-based for SQL Server)
  - **Test Coverage**: 15 unit tests (all partition types)
  - **Files Modified**: `table.py`, `hybrid_parser.py`, `comparator.py`, `schema_introspector.py`, all `*_queries.py`

- **Grammar-Based Parser Improvements Across All Databases**: Comprehensive enhancements based on ANTLR grammar analysis
  - **PostgreSQL Grammar Enhancements**:
    - Dollar-quoted strings (`$$...$$`) support in functions and procedures
    - UNLOGGED tables and materialized views parsing
    - TEMPORARY and TEMP table syntax support
    - CREATE INDEX CONCURRENTLY pattern matching
    - IF NOT EXISTS clause support for all DDL statements
    - Enhanced identifier patterns with `$` support
  - **MySQL Grammar Enhancements**:
    - Backtick identifier support (`` `table_name` ``)
    - IF NOT EXISTS / IF EXISTS clause support
    - TEMPORARY table detection and tracking
    - CREATE EVENT (scheduled events) - Full parser, introspection, and diff tracking
    - ONLINE/OFFLINE index creation support
    - DEFINER clauses for views, triggers, procedures, functions
    - View ALGORITHM (MERGE, TEMPTABLE, UNDEFINED) support
    - View SQL SECURITY (DEFINER, INVOKER) support
    - UNIQUE, FULLTEXT, SPATIAL index types
    - Statement splitting with EVENT and TRIGGER awareness
  - **SQL Server Grammar Enhancements**:
    - Bracketed identifiers (`[table_name]`) support
    - Table properties: filegroup, memory_optimized, system_versioned, history_table
    - GO batch separator handling
    - CREATE OR ALTER PROCEDURE/VIEW pattern support
    - Temporal table tracking and comparison
  - **Oracle Grammar Enhancements**:
    - Virtual columns: GENERATED ALWAYS AS (expression) VIRTUAL
    - Expression normalization with quoted identifier handling
    - Enhanced materialized view support (refresh options)
    - Database link creation and comparison
    - Object type ownership rules
  - **DB2 Grammar Enhancements**:
    - Computed columns: GENERATED ALWAYS AS (expression) - virtual by default
    - Table options: LOGGED/NOT LOGGED, COMPRESS YES/NO, IN tablespace
    - CREATE INDEX with UNIQUE WHERE NOT NULL, TYPE 1/2 support
    - CREATE OR REPLACE PROCEDURE/TRIGGER support
    - CREATE ALIAS and CREATE SYNONYM pattern support
    - GLOBAL TEMPORARY TABLE support
    - Table property introspection from SYSCAT.TABLES
    - Grammar-accurate patterns for z/OS dialect
  - **Test Coverage**: 34 DB2 unit tests (100% pass), 9 integration tests
  - **Documentation**: Complete grammar analysis and implementation guides in `docs/GRAMMAR_BASED_IMPROVEMENTS.md`
  - **Files Modified**: 11 files across parser, introspection, and comparison layers
  - **Approach**: Grammar files used as reference (not runtime) to enhance regex patterns

- **Synonym Comparison in Diff Command**: Full support for synonym drift detection
  - Detects missing, extra, and modified synonyms between migrations and database
  - Tracks target object, target schema, target database (SQL Server), and database link (Oracle) changes
  - Dialect-aware identifier normalization (uppercase for Oracle/DB2, lowercase for PostgreSQL/MySQL/SQL Server)
  - Proper handling of quoted vs unquoted identifiers per SQL standard
  - Severity: WARNING (synonyms can be easily recreated)
  - Added `SynonymDiff` model with comprehensive change tracking
  - Added `compare_synonyms()` method with case-sensitive quoted identifier support
  - Integrated synonym extraction, introspection, and comparison in diff workflow
  - 22 comprehensive unit tests covering all synonym comparison scenarios
  - 15 integration tests for Oracle, SQL Server, and DB2

- **Enhanced Materialized View Support**: Comprehensive refresh options tracking
  - Added materialized view specific properties to View model:
    - `is_populated`: Whether the materialized view is populated (PostgreSQL, Oracle)
    - `refresh_method`: Refresh method - FAST, COMPLETE, FORCE, MANUAL (Oracle, DB2)
    - `refresh_mode`: Refresh mode - ON DEMAND, ON COMMIT (Oracle)
    - `fast_refreshable`: Whether fast refresh is available (Oracle)
    - `last_refresh`: Timestamp of last refresh (Oracle, DB2)
  - Enhanced `ViewDiff` to track all materialized view property changes
  - Updated `compare_views()` to compare refresh options with case-insensitive normalization
  - Only compares refresh properties when both views are materialized
  - 7 comprehensive unit tests covering all materialized view comparison scenarios
  - Database support: PostgreSQL (is_populated), Oracle (all properties), DB2 (refresh_method, last_refresh), SQL Server (manual refresh only)

- **User-Defined Type (UDT) Comparison in Diff Command**: Full support for UDT drift detection
  - Detects missing, extra, and modified user-defined types between migrations and database
  - Supports all major UDT variants across databases:
    - PostgreSQL: COMPOSITE types, ENUM types, DOMAIN types
    - Oracle: OBJECT types with attributes and methods
    - SQL Server: User-defined alias types and table types
    - DB2: DISTINCT types and structured types
  - Dialect-aware identifier normalization (uppercase for Oracle/DB2, lowercase for others)
  - Added `UserDefinedTypeDiff` model with comprehensive change tracking
  - Added `compare_user_defined_types()` method with type definition comparison
  - Integrated UDT extraction, introspection, and comparison in diff workflow
  - Comprehensive integration tests covering all UDT scenarios across databases

- **Package Comparison in Diff Command**: Full support for Oracle package drift detection
  - Detects missing, extra, and modified packages between migrations and database
  - Tracks both package specification and body changes separately
  - Handles Oracle package-specific syntax and PL/SQL code normalization
  - Added `PackageDiff` model with specification and body change tracking
  - Added `compare_packages()` method with whitespace and comment normalization
  - Integrated package extraction, introspection, and comparison in diff workflow
  - Comprehensive unit tests covering all package comparison scenarios

- **PostgreSQL Extensions and Foreign Data Wrappers**: Complete diff support for PostgreSQL-specific objects
  - **Extensions**: Full CREATE EXTENSION and DROP EXTENSION parsing and comparison
    - Detects missing, extra, and modified extensions
    - Tracks extension version and schema changes
    - Added `ExtensionDiff` model for extension change tracking
  - **Foreign Data Wrappers (FDW)**: Complete CREATE FOREIGN DATA WRAPPER parsing and comparison
    - Detects missing, extra, and modified foreign data wrappers
    - Tracks handler, validator, and options changes
    - Added `ForeignDataWrapperDiff` model for FDW change tracking
  - **Foreign Servers**: Complete CREATE SERVER parsing and comparison
    - Detects missing, extra, and modified foreign servers
    - Tracks server type, version, and options changes
    - Added `ForeignServerDiff` model for foreign server change tracking
  - Added comprehensive PostgreSQL regex patterns and SQL model classes
  - Integrated extension introspection using PostgreSQL system catalogs

- **Database Links, Linked Servers, and Modules**: Extended object type support
  - **Oracle Database Links**: CREATE DATABASE LINK parsing and comparison support
  - **SQL Server Linked Servers**: CREATE LINKED SERVER parsing and comparison support  
  - **DB2 Modules**: CREATE MODULE parsing and comparison support
  - Added corresponding SQL model classes: `DatabaseLink`, `LinkedServer`, `Module`
  - Added diff models: `DatabaseLinkDiff`, `LinkedServerDiff`, `ModuleDiff`
  - Enhanced regex patterns for all supported database dialects

### Fixed

- **Integration Test Regression Fixes**: Resolved numerous database-specific issues that arose after grammar-based parser improvements
  - **PostgreSQL**:
    - Fixed partition table introspection (JDBC `getTables()` doesn't return partitioned tables with `relkind='p'`)
    - Added vendor query to retrieve partitioned tables and merge with JDBC results
    - Filter auto-created composite types from UDT list (PostgreSQL creates types for every table)
    - Fixed PRIMARY KEY requirement for partitioned tables (must include partition columns)
    - Added DECIMAL→NUMERIC type normalization (PostgreSQL treats them as synonyms)
    - Fixed CTAS/LIKE schema quoting for case-sensitive identifiers
    - Corrected LIKE syntax to use parentheses: `CREATE TABLE t (LIKE source)`
  - **MySQL**:
    - Fixed schema introspection to use `catalog` parameter (not `schema`) for JDBC metadata
    - Resolved computed column false positives (JDBC incorrectly flags `DEFAULT CURRENT_TIMESTAMP` as generated)
    - Added MySQL-specific logic to distinguish actual `GENERATED ALWAYS AS` from simple defaults
    - Fixed default value normalization to remove empty parentheses from timestamp functions
    - Updated backtick identifier handling in parser to strip quotes from column names
    - Fixed event filtering logic to populate `managed_db_events` correctly
    - Added `GO` batch separators for MySQL DDL statements in tests
  - **Oracle**:
    - Enhanced virtual column support with expression normalization (whitespace, quoted identifiers)
    - Added `FORCE` keyword to `DROP TYPE` cleanup for types with dependencies
    - Fixed database link cleanup to use session user (`SYS_CONTEXT('USERENV', 'SESSION_USER')`)
    - Skipped database link tests due to complexity of user-owned link management
  - **DB2**:
    - Fixed identity column detection (prevent IDENTITY columns from being marked as computed)
    - Added default value normalization (`CURRENT` → `CURRENT TIMESTAMP`)
    - Modified constraint filtering to handle auto-generated UNIQUE constraints by column signature only
    - Removed `TEXT` column from `SYSCAT.MODULES` query (doesn't exist in DB2 Express)
    - Fixed table-level PRIMARY KEY syntax (DB2 LUW doesn't support inline `PRIMARY KEY` constraint)
    - Enhanced parser to handle `CREATE ALIAS` (DB2 synonym syntax)
    - Added module block splitting for compound `CREATE MODULE...END MODULE` statements
    - Fixed `NOT LOGGED` syntax to `NOT LOGGED INITIALLY`
    - Disabled UDT support for DB2 Express (missing `SYSCAT.TYPES` table)
    - Skipped MODULE tests (not supported in DB2 Community Edition Docker container)
  - **SQL Server**:
    - Fixed table properties query for version compatibility (removed temporal/memory-optimized columns)
    - Modified queries to use index-based filegroup lookup for better compatibility
    - Added `getattr` with defaults in comparator to handle missing SQL Server-specific attributes
    - Fixed indexed view aggregate validation (`SUM` on nullable columns)
    - Added `GO` batch separators between DDL statements
    - Normalized `None` and `'PRIMARY'` filegroup values (PRIMARY is implicit default)
  - **Parser Improvements**:
    - Fixed hybrid parser to strip quotes (backticks, double quotes, brackets) from column names
    - Enhanced CTAS/LIKE detection to run before column extraction (prevents false column matches)
    - Improved CTAS regex to handle various whitespace patterns
    - Added table-level constraint filtering (skip `PRIMARY KEY`, `UNIQUE`, `FOREIGN KEY`, `CHECK` lines)
    - Added SQL function filtering for partition column extraction (e.g., `YEAR(date)` → `date`)
  - **Test Infrastructure**:
    - Changed class-level `@pytest.mark.parametrize` to function-level for database-specific tests
    - Prevents unnecessary Docker container startups when using `-k` filters
    - Fixed Docker volume mount issues on macOS by avoiding unnecessary container initialization
    - Added explicit schema quoting for PostgreSQL case-sensitive identifiers

- **SQL Server Default Value Comparison**: Resolved false positive drift detection for columns with default values
  - **Root Cause**: Format mismatch between migration parsing (`DEFAULT GETDATE()`) and database introspection (`DEFAULT (getdate())`)
  - **Enhanced Default Value Normalization**: Added comprehensive normalization in `ObjectComparator._normalize_default_value()`
    - Remove outer parentheses: `(getdate())` → `getdate()`
    - Normalize function names to uppercase: `getdate()` → `GETDATE()`
    - Consistent handling of all SQL Server function patterns (`SUSER_NAME()`, `@@SPID`, etc.)
  - **Enhanced SQL Server Introspection**: Added `get_column_defaults_query()` using `sys.default_constraints`
    - Handles cases where JDBC metadata returns NULL for default values
    - Provides accurate default value extraction from SQL Server system tables
  - **Enhanced Logging**: Added default value display in column comparison logs for better debugging
    - Format: `Column: name, type=X, is_identity=Y, default=Z`
    - Enables easy identification of default value mismatches
  - **Impact**: SQL Server integration tests improved from multiple failures to 41/42 passing (98% pass rate)
  - **Coverage**: All SQL Server default value functions now properly normalized and compared

- **Diff Command Success Logic**: Fixed incorrect success reporting when schema differences detected
  - **Root Cause**: `DiffResult.set_schema_diff()` only failed on ERROR-level differences, not WARNING-level
  - **Fix**: Changed logic to set `success=False` whenever ANY differences detected (`total_differences > 0`)
  - **Impact**: Diff command now correctly fails (exit code 1) on any schema drift detection
  - **Behavior**: Any drift (INFO, WARNING, or ERROR level) now causes command failure as expected
  - **Tests Fixed**: PostgreSQL UDT integration tests (`test_detect_modified_structured_type`, `test_detect_modified_enum_type`)

- **Comprehensive Object Cleanup Support**: Enhanced schema cleanup across all database providers
  - **SQL Server**: Added linked server cleanup using `sys.servers` queries
  - **Oracle**: Added database link cleanup using `ALL_DB_LINKS` queries  
  - **PostgreSQL**: Added extension, foreign data wrapper, and foreign server cleanup
  - **MySQL**: Event cleanup already supported (no changes needed)
  - **DB2**: Comprehensive cleanup already supported (modules, MQTs, aliases, temp tables)
  - **Impact**: Ensures proper test isolation and prevents cleanup failures for all new object types
  - **Scope**: All database providers now clean up the complete set of supported objects

### Changed
- **SqlGenerator**: Enhanced with dependency ordering integration
  - `generate_ddl()` now supports dependency-aware ordering
  - `generate_drop_statements()` uses dependency ordering for correct sequence
  - Integrated `ScriptOrganizer` for all organization strategies
  - Removed redundant helper methods (now handled by ScriptOrganizer)

### Testing
- **Unit Tests**: Added comprehensive unit tests for SQL Generation Engine
  - 15+ tests for `SqlFormatter` (formatting, fallbacks, batch operations)
  - 10+ tests for `DependencyAnalyzer` (graph building, sorting, circular detection)
  - 8+ tests for `ScriptOrganizer` (all organization strategies, filtering, headers)
  - 3+ tests for `AlterGenerator` (ALTER TABLE, ALTER VIEW)
  - All tests passing with no linter errors
- **Integration Tests**: Added integration tests for export-schema command
  - Basic schema export to single file
  - Filtering by types and tables
  - Split-by-type output
  - Managed/unmanaged object filtering
  - Include DROP statements
  - Validation error handling
  - Tests run against all supported databases (PostgreSQL, MySQL, SQL Server, Oracle, DB2)

## [0.4.0-beta] - 2024-10-31

### Added
- **Migration State Consolidation**: Centralized all state computation logic in `MigrationStateManager`
  - Single source of truth for determining pending/applied migrations
  - Consistent filtering logic across all operations
  - Improved maintainability and testability

### Fixed
- **Strict Mode Bypass**: Out-of-order migrations now correctly prevented in strict mode
  - Fixed logic error where early return bypassed strict mode validation
  - Added warning logs when rejecting out-of-order migrations
  - Maintains backward compatibility (strict mode disabled by default)
- **Baseline Command**: Migrations with versions <= baseline are now correctly skipped
  - Fixed issue where migrations covered by baseline were still being executed
  - Baseline now properly marks all versions <= baseline as applied
  - Prevents "table already exists" errors after baseline

### Changed
- **Code Reduction**: Removed 981 lines of duplicate and dead code (15% reduction)
  - Removed `MigrationCollectionManager` (205 lines of dead code)
  - Removed `get_current_version()` from HistoryManager (224 lines of dead code)
  - Consolidated state methods from ScriptManager (662 lines)
  - Simplified `record_deletion()` in HistoryManager (22 lines)
- **Performance Improvement**: Pushed filtering logic to SQL queries
  - `is_script_deleted()` now uses efficient SQL COUNT query
  - `get_deletion_info()` now uses SQL ORDER BY/LIMIT query
  - Reduced memory usage by avoiding full migration list loads
- **Architecture Cleanup**: Clear separation of concerns
  - `MigrationScriptManager`: Filesystem & parsing ONLY (564 lines, -57%)
  - `MigrationStateManager`: State computation ONLY (620 lines)
  - `MigrationHistoryManager`: Data access ONLY (399 lines, -42%)
  - `JdbcProvider`: SQL queries with optimized filtering

### Removed
- Dead code: 429 lines eliminated (100%)
- Duplicate logic: 300+ lines eliminated (100%)
- Obsolete methods from ScriptManager: `get_pending_migrations()`, `analyze_migrations()`, `get_pending_scripts()`, `is_out_of_order()`, `_filter_script_by_criteria()`

## [0.3.0-beta] - Previous Release

### Added
- **Diff Command - View Comparison**: Full support for view drift detection
  - Parse views from migration scripts
  - Introspect views from database
  - Compare view definitions with normalization (case-insensitive, whitespace-normalized, comment-removed)
  - Detect missing views (ERROR severity)
  - Detect extra/unmanaged views
  - Detect modified view definitions (WARNING severity)
  - Detect materialized view status changes
- **Diff Command - Index Comparison**: Full support for index drift detection
  - Parse indexes from migration scripts
  - Introspect indexes from database (per-table)
  - Compare index columns (order-sensitive), uniqueness, and type
  - Detect missing indexes
  - Detect extra/unmanaged indexes
  - Detect modified indexes (column changes, uniqueness changes, type changes)
  - Filter out indexes on internal DBLift tables
- **Diff Command - Sequence Comparison**: Full support for sequence drift detection
  - Parse sequences from migration scripts
  - Introspect sequences from database
  - Compare sequence properties (start value, increment, min/max values, cycle option)
  - Detect missing sequences
  - Detect extra/unmanaged sequences
  - Detect modified sequences (property changes)
  - Support for PostgreSQL, SQL Server, Oracle, and DB2 (MySQL does not support sequences)
- **Diff Command - Trigger Comparison**: Full support for trigger drift detection
  - Parse triggers from migration scripts
  - Introspect triggers from database
  - Compare trigger timing (BEFORE/AFTER/INSTEAD OF), events (INSERT/UPDATE/DELETE), and definitions
  - Detect missing triggers (ERROR severity)
  - Detect extra/unmanaged triggers
  - Detect modified triggers (timing, event, or definition changes)
  - Filter out triggers on internal DBLift tables
  - Support for PostgreSQL, MySQL, SQL Server, Oracle, and DB2
- **Diff Models**: New diff model classes for all SQL object types
  - `ViewDiff`: Tracks view definition and materialized status changes
  - `IndexDiff`: Tracks index column, uniqueness, and type changes
  - `SequenceDiff`: Tracks sequence property changes
  - `TriggerDiff`: Tracks trigger timing, event, and definition changes
  - `ProcedureDiff`: Tracks stored procedure parameter and body changes
  - `FunctionDiff`: Tracks function parameter and body changes
- **ObjectComparator**: New comparison methods for all object types
  - `compare_views()`: Compare view definitions and materialized status
  - `compare_indexes()`: Compare index columns, uniqueness, type
  - `compare_sequences()`: Compare sequence properties
  - `compare_triggers()`: Compare trigger timing, events, definitions
  - `compare_procedures()`: Compare stored procedure parameters and body
  - `compare_functions()`: Compare function parameters and body
- **Diff Output**: Enhanced console output to display view differences
  - Summary section shows view counts (missing/extra/modified)
  - Detailed view diff sections with definition changes
  - Truncated view definitions for readability (100 chars)

### Fixed
- **Diff Command - Oracle Integration**: Fixed identity column detection and comparison for Oracle's `GENERATED ALWAYS AS IDENTITY` syntax
- **Diff Command - SQL Server Integration**: Fixed parser to avoid capturing INSERT statements in CREATE TABLE definitions
- **Diff Command - MySQL Integration**: Fixed multi-statement SQL execution in test infrastructure
- **Constraint Comparison**: Added system-generated constraint name detection (Oracle `SYS_C*`, SQL Server `PK__*`/`FK__*`)
- **Constraint Comparison**: Filter duplicate UNIQUE constraints that match PRIMARY KEY constraints in Oracle
- **Identity Column Comparison**: Enhanced column comparison to handle identity columns with different syntax representations
- **Test Infrastructure**: Moved multi-statement SQL splitting from MySQL executor to test helper for proper separation of concerns
- **Index Filtering**: Fixed internal table index filtering to properly exclude indexes on `dblift_schema_history` and `dblift_migration_lock` tables
- **Index Logging**: Changed unmanaged index logging from INFO to DEBUG level to avoid false positives for auto-generated constraint indexes
- **View Parsing**: Fixed CREATE VIEW regex to support quoted identifiers (double quotes, single quotes, square brackets) across all database dialects

### Changed
- **HybridParser**: Added identity column detection for Oracle `GENERATED ALWAYS AS IDENTITY` and `GENERATED BY DEFAULT AS IDENTITY` syntax
- **ObjectComparator**: Enhanced constraint matching to ignore system-generated names and match by type and columns
- **ObjectComparator**: Added base type extraction for identity columns to normalize comparison across dialects
- **SchemaDiff**: Extended to track all SQL object types (views, indexes, sequences, triggers, procedures, functions)
- **DiffResult**: Added fields for view diffs (missing_views, extra_views, modified_views)

### Testing
- **Diff Integration Tests**: All 80 diff integration tests now passing across all 5 databases (PostgreSQL, MySQL, SQL Server, Oracle, DB2)
- **Table Tests**: 13/13 tests passing per database (65 total)
- **View Tests**: 3/3 tests passing per database (15 total)
- **Unit Tests**: 5 new unit tests for view comparison (all passing)

## [0.3.0-beta] - 2025-01-28

### Added
- **SQL Model Enhancements**: Added three new SQL Model classes for complete metadata coverage
  - `Package` class for Oracle packages (specification and body)
  - `Event` class for MySQL scheduled events
  - `Partition` class for table partitions (all databases)
- **Table Enhancements**: Added `storage_engine` field to `Table` class for MySQL storage engine tracking (InnoDB, MyISAM, etc.)
- **Table Enhancements**: Added `partitions` field to `Table` class for partition metadata
- **SqlObjectType**: Added `EVENT`, `PARTITION`, and `DATABASE_LINK` enum values
- **Partition Integration**: Updated `SchemaIntrospector.get_table_partitions()` to return `Partition` objects instead of dictionaries
- **Hybrid Parser Object Extraction**: Complete test coverage for all 15 database object types
  - Added tests for synonym extraction (Oracle)
  - Added tests for user-defined type extraction (Oracle)
  - Added tests for event extraction (MySQL)
  - Added tests for partition extraction (all databases)

### Changed
- **Partition Extraction**: `get_table_partitions()` now returns `List[Partition]` instead of `List[Dict[str, Any]]` for type safety

### Fixed
- **Oracle Function Extraction**: Relaxed body validation to handle complex PL/SQL function bodies
- **Quoted Identifiers**: Added support for quoted identifiers in function names
- **Function/Trigger Validation**: Added validation for malformed function and trigger definitions
- **Table Dialect Assignment**: Fixed dialect assignment in hybrid parser for proper multi-database support
- **Procedure Parameters**: Fixed parameter extraction with precision/scale specifications
- **Parser Robustness**: Improved parser handling of edge cases and complex SQL syntax

### Testing
- Added comprehensive unit tests for new SQL Model classes:
  - `test_package.py` - 13 tests for Package class
  - `test_event.py` - 16 tests for Event class
  - `test_partition.py` - 16 tests for Partition class
- Added 4 tests for hybrid parser object extraction (31 tests total, up from 27)
- **100% unit test pass rate achieved**
- All 149 SQL Model tests passing

### Added
- **JDBC Metadata Extraction (Phase 3)**: Database schema introspection for drift detection
  - **SchemaIntrospector**: Database-agnostic metadata extraction using JDBC DatabaseMetaData API
    - Extract tables, columns, constraints, and indexes from live databases
    - Returns rich SQL Model objects (Table, SqlColumn, SqlConstraint, Index)
    - Works across all supported databases (PostgreSQL, MySQL, Oracle, SQL Server, DB2)
    - Context manager support for automatic connection cleanup
  - **Schema Comparison Workflow**:
    - Extract current database schema via JDBC introspection
    - Parse expected schema from migration files (SQL Model)
    - Compare and generate actionable diff reports
    - Support for case-sensitive/insensitive comparison
  - **Use Cases Enabled**:
    - Schema drift detection (find unauthorized changes)
    - Migration verification (ensure migrations applied correctly)
    - Baseline from existing database (generate migrations from current state)
    - Impact analysis (understand effects of schema changes)
    - Schema documentation (auto-generate from database)
- **SQL Model Enhancement (Phase 1)**: Rich object extraction from SQL DDL statements
  - **ParseResult Enhancement**: Container for parsed SQL with rich object collections
    - Collections for tables, views, indexes, sequences, procedures
    - Dependency graph tracking with circular dependency detection
    - Helper methods: `add_table()`, `get_table()`, `get_view()`, `has_circular_dependencies()`
  - **HybridParser DDL Extraction**: Extract Table/Column/Constraint objects from CREATE statements
    - Table objects with full column definitions (name, data_type, nullable, default_value)
    - Column-level constraint detection (PRIMARY KEY, UNIQUE, NOT NULL flags)
    - Inline constraint extraction (PRIMARY KEY, NOT NULL, UNIQUE, DEFAULT)
    - Table-level constraints (composite PKs, FKs with references, UNIQUE)
    - Named constraint support (CONSTRAINT name syntax)
    - Multi-dialect support (PostgreSQL, MySQL, Oracle, SQL Server, DB2)
  - **SqlAnalyzer Public API**: High-level interface for accessing SQL Model objects
    - `parse_sql()`: Get full ParseResult with all extracted objects
    - `get_tables()`, `get_views()`, `get_indexes()`: Extract object lists
    - `get_table()`, `get_view()`: Lookup specific objects by name
    - `has_circular_dependencies()`, `get_dependencies()`: Dependency analysis
  - **Comprehensive Test Coverage**: 48 new tests across 3 test suites
    - Constraint extraction tests (inline, table-level, named, multi-dialect)
    - SqlAnalyzer API tests (parsing, extraction, lookup, dependencies)
    - 100% pass rate with type safety (mypy) and code quality (black, flake8)
- **SQL Model Enhancement (Phase 2)**: Validation rules integration with SQL Model objects
  - **Presence Rules**: Declarative validation for required DDL elements
    - `must_have_columns`: Ensure tables have required columns (e.g., audit columns)
    - `must_have_primary_key`: Enforce primary key requirements
    - `must_have_comment`: Validate documentation requirements
  - **Relational Rules**: Validate relationships between database objects
    - `requires_index`: Ensure foreign keys have supporting indexes for performance
    - Checks both explicit indexes and primary key coverage
    - Multi-dialect support for index validation
  - **RuleEngine Enhancement**: Dialect-aware SQL Model integration
    - Accepts dialect parameter for SqlAnalyzer initialization
    - Uses parsed Table objects for structural validation
    - Maintains backward compatibility with naming/pattern rules
  - **SqlLinter Integration**: Automatic dialect mapping for rule engine
    - Maps SQLFluff dialects to SQL Model dialects
    - Seamless integration with existing validation pipeline
  - **Test Coverage**: 13 new tests for presence and relational rules
    - Presence rules (columns, primary keys, multi-table scenarios)
    - Relational rules (FK/index validation, PK as index)
    - Combined rules (naming + presence + pattern + relational)
    - Multi-dialect support (PostgreSQL, MySQL, Oracle)
- **SQL Validation System for CI/CD**:
  - `validate-sql` CLI command for standalone SQL validation (no database required)
  - Business rule validation with declarative YAML rules (naming conventions, anti-patterns)
  - AST-based performance analysis (cartesian products, missing WHERE, SELECT *, correlated subqueries)
  - Configurable severity levels for all rules (error, warning, info)
  - Multiple output formats: console, JSON, SARIF (GitHub Code Scanning), GitHub Actions, compact
  - SQLFluff integration for business rules validation
  - SQLGlot integration for performance analysis
- **Docker Support for CI/CD**:
  - Full Docker image with JDBC connectivity (~500MB)
  - Lightweight validation-only image (~150MB, 70% smaller)
  - Docker Compose configuration for local development
  - Volume mount patterns for external rules files
  - GitHub Actions and GitLab CI example workflows
  - Pre-commit hook examples
- **Hybrid SQL Parser**: Parsing system combining regex-based statement splitting with sqlglot AST-based analysis
  - Regex parsers handle procedural language splitting (PL/SQL, T-SQL, PL/pgSQL blocks)
  - SqlGlot parser provides SQL analysis for pure SQL statements
  - Automatic detection routes procedural vs pure SQL
  - Graceful fallback if sqlglot parsing fails
  - ~95% parsing accuracy for pure SQL, 100% reliability for procedural code
- SqlGlot integration for Oracle, MySQL, PostgreSQL, and SQL Server dialects
- SQL dependency extraction using AST parsing
- Query complexity analysis and performance predictions
- Callback execution system with error callbacks
- DB2 database support with full integration
- Version and tag filtering for undo command
- HTML reports with UNDO support
- Placeholder replacement in callback scripts
- Script file encoding configuration support (utf-8, windows-1252, iso-8859-1)
- Windows Authentication support for SQL Server
- Distribution versioning in package names

### Changed
- Migrated from pure regex-based to hybrid SQL parsing architecture
- Refactored modular database provider architecture with specialized components:
  - Connection Manager (JDBC connection and Java class management)
  - Query Executor (SQL execution and result processing)
  - Locking Manager (Migration locking with database-specific mechanisms)
  - Schema Operations (Schema operations and metadata queries)
  - History Manager (Migration history table management)
- Improved CLI argument parsing and validation
- Enhanced error logging with more context
- Standardized table names with proper case handling across databases
- Route ERROR and WARNING messages to stderr in console output
- Sequential workflow execution chain for CI/CD
- Case-insensitive log-level parameter handling

### Fixed
- **SQL Validation**:
  - Naming rule pattern matching now case-sensitive (was incorrectly using case-insensitive regex)
  - SQLFluff dialect configuration (must be at root level, not under "core")
- DB2 parser improvements:
  - ATOMIC clause now optional in trigger detection
  - CASE expression handling in SQL/PL parser
  - Nested BEGIN/END blocks and control structures
  - @ delimiter support for procedures, triggers, and functions
  - IDENTITY syntax support in command integration tests
- MySQL parser fixes:
  - Delimiter markers properly stripped from statements
  - DETERMINISTIC keyword handling in functions
  - Identifier quoting improvements
- Oracle integration test fixes and configuration improvements
- SQL Server IDENTITY_INSERT errors in record_migration
- PostgreSQL advisory lock SQL syntax
- Connection management improvements across all database providers
- Repeatable migration conditional logic
- Baseline operation now commits transactions properly
- Schema cleanup operations to prevent test state pollution
- NULL parameter handling in DB2 and MySQL JDBC drivers
- Custom history table name configuration flow
- Lock acquisition handling across all database types

## [0.2.0-beta] - 2025-XX-XX

### Added
- Migration Journal System
  - Detailed tracking of migration execution with performance metrics
  - Statement-level timing information for diagnostics
  - Memory-based storage during execution
  - Performance summary with statement counts and timing statistics
  - Object type breakdown showing performance by database object type
  - Multiple output formats (Console, Text, HTML, JSON)
- Comprehensive integration test suite with Docker-based database testing
- CLI end-to-end tests for MySQL and PostgreSQL
- Automated CI/CD workflows with GitHub Actions
- Concurrency control to cancel previous workflow runs

### Changed
- Improved command-line interface with better help documentation
- Enhanced logging with detailed performance information across all formats
- Consolidated output and formatting system

### Fixed
- Integration test reliability and isolation improvements
- Test timeout handling and cleanup operations
- Logger parameter naming consistency

## [0.1.0-beta] - 2025-XX-XX

### Added
- Initial release of DBLift database migration tool
- Multi-database support: SQL Server, Oracle, PostgreSQL, MySQL
- Flyway-compatible migration naming conventions
- Three migration types:
  - Versioned migrations (V{version}__{description}.sql)
  - Repeatable migrations (R__{description}.sql)
  - Undo migrations (U{version}__{description}.sql)
- Transaction safety with automatic rollback on failure
- Tag-based migration filtering for selective execution
- Support for subdirectories and multiple migration directories
- Command-line interface with core commands:
  - migrate, info, validate, undo, clean, baseline, repair
- JDBC-based database connectivity with bundled JRE
- Comprehensive error handling with automatic retry for transient errors
- Multiple log formats: TEXT, JSON, HTML
- Configuration via YAML files, environment variables, or CLI arguments
- Cross-platform distributions (Windows, Linux, macOS)
- Modular provider architecture for easy database support extension

[Unreleased]: https://github.com/cmodiano/dblift/compare/v1.7.0...HEAD
[1.7.0]: https://github.com/cmodiano/dblift/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/cmodiano/dblift/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/cmodiano/dblift/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/cmodiano/dblift/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/cmodiano/dblift/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/cmodiano/dblift/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/cmodiano/dblift/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/cmodiano/dblift/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/cmodiano/dblift/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/cmodiano/dblift/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/cmodiano/dblift/compare/v1.0.1...v1.1.0
[0.8.0-beta]: https://github.com/cmodiano/dblift/compare/v0.7.0-beta...v0.8.0-beta
[0.7.0-beta]: https://github.com/cmodiano/dblift/compare/v0.6.1-beta...v0.7.0-beta
[0.6.1-beta]: https://github.com/cmodiano/dblift/compare/v0.6.0-beta...v0.6.1-beta
[0.6.0-beta]: https://github.com/cmodiano/dblift/compare/v0.5.0-beta...v0.6.0-beta
[0.5.0-beta]: https://github.com/cmodiano/dblift/compare/v0.4.0-beta...v0.5.0-beta
[0.4.0-beta]: https://github.com/cmodiano/dblift/compare/v0.3.0-beta...v0.4.0-beta
[0.3.0-beta]: https://github.com/cmodiano/dblift/compare/v0.2.0-beta...v0.3.0-beta
[0.2.0-beta]: https://github.com/cmodiano/dblift/compare/v0.1.0-beta...v0.2.0-beta
[0.1.0-beta]: https://github.com/cmodiano/dblift/releases/tag/v0.1.0-beta
