# Changelog

All notable changes to DBLift will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CockroachDB (`dblift[cockroachdb]`) and Redshift (`dblift[redshift]`)
  PostgreSQL-compatible provider plugins. They follow the existing
  PostgreSQL-derived plugin pattern: same provider/config/SQLAlchemy URL builder
  and `psycopg` driver, with distinct `type: cockroachdb` / `type: redshift`
  identities.

### Changed

### Fixed

### Removed

## [2.4.2] - 2026-07-06

### Fixed

- `View` now carries plugin-owned `dialect_options` through serialization and
  equality, matching `Table`. Previously `View.to_dict`/`from_dict` dropped them
  and `__eq__` ignored them, so options a plugin stored on a view under its
  dialect namespace were lost across a schema-snapshot round-trip — a reloaded
  snapshot compared against a live introspection could then falsely report a
  change (or miss one).

## [2.4.1] - 2026-07-06

### Fixed

- **Paid-tier CLI commands were rejected for every license.** The CLI dispatch
  built the command context without resolving the license tier, so every
  feature gate saw `NONE` and Pro/Enterprise commands (`diff`, `export-schema`,
  `plan`, `snapshot`, ...) failed with "requires a … license (current: NONE)"
  regardless of a valid license file, environment variable, or `--license-key`.
  The tier is now resolved through the tier-resolver seam when the command
  context is built. Pure-OSS installs (no resolver registered) are unaffected.
- **`--license-key` was rejected as "unrecognized arguments".** This root-only
  flag was not classified as global, so the argv preprocessor relocated it past
  the subcommand token and the subparser rejected it. It is now classified
  alongside the other root-only value flags.

## [2.4.0] - 2026-07-05

### Added

- Seven PostgreSQL-compatible distribution plugins: Neon (`dblift[neon]`),
  Supabase (`dblift[supabase]`), Amazon Aurora PostgreSQL
  (`dblift[aurora-postgresql]`), Google AlloyDB (`dblift[alloydb]`), YugabyteDB
  (`dblift[yugabytedb]`), TimescaleDB (`dblift[timescaledb]`), and Citus
  (`dblift[citus]`). Each speaks the PostgreSQL wire protocol and reuses the
  PostgreSQL provider, config, SQLAlchemy URL builder, and `psycopg` driver;
  users keep their `postgresql://` connection string and select the engine via
  `type: <name>`. Registered through the standard `dblift.providers` entry
  point — no core changes required.
- `dblift --version` now prints the product headline plus a component manifest
  (core / pro / enterprise) reflecting which packages are installed.

### Changed

### Fixed

### Removed

## [2.3.0] - 2026-07-05

### Added

- DuckDB provider plugin (`dblift[duckdb]`): a first-class embedded/file-based
  dialect supporting migrate, schema history, migration locking, and clean.
  Backed by SQLAlchemy via `duckdb_engine`; PostgreSQL-like SQL (real schemas,
  sequences, native `BOOLEAN`, transactional DDL). Registered through the
  standard `dblift.providers` entry point — no core changes required.

### Fixed

- SQLAlchemy provider: bind the `numeric_dollar` paramstyle on the raw
  `exec_driver_sql` metadata-query path. `duckdb_engine`'s dialect reports
  `numeric_dollar` while its DBAPI accepts qmark, so vendor metadata queries
  previously failed with an unbindable `:p0` placeholder.

## [2.2.2] - 2026-07-04

### Fixed

- **HTML reports failed with "template not found" on wheel installs.** The
  packaged wheel did not include `core/logger/templates/*.html` — the
  `[tool.setuptools.package-data]` table only shipped `api/py.typed`. Any
  `pip install dblift` user generating an HTML report hit
  `report.html not found in search path`. Editable installs masked it (the
  templates were visible on disk). The wheel now ships the templates.

## [2.2.1] - 2026-07-03

### Changed

- Internal refactor: introduced a plugin-registration seam
  (`core/seams/{tier_resolver,license_info,capabilities,feature_loading,runtime_checks}.py`)
  that higher tiers register against, replacing the old `core/features.py`.
  `core/sql_generator` remains the OSS-owned base DDL-generation engine that
  paid tiers subclass. No user-facing behavior change.

## [2.2.0] - 2026-07-01

### Added

- **`dblift config --list`** — prints every persistent configuration property
  alongside its config key, environment variable, and CLI flag, so the full
  property surface is discoverable from the command line instead of the docs.
- New [How to Write and Apply Your First Migration](docs/how-to/first-migration.md)
  quickstart guide.

### Changed

- **Python migration undo now requires a separate `U<ver>__*.py` file** —
  matching the existing SQL convention (`U<ver>__*.sql` undoes `V<ver>__*.sql`).
  Previously a versioned `.py` migration could define both `migrate()` and an
  inline `undo()` in the same file; that inline `undo()` is no longer honored.
  If no `U<ver>__*.py` companion exists for an applied `V<ver>__*.py`, `undo`
  fails with "No undo script found", same as SQL migrations.
- Documented that `integrations.django` ships `dblift_migrate` / `dblift_info`
  / `dblift_validate` management commands plus a pending-migrations system
  check, as an alternative to wiring `DBLiftClient.from_sqlalchemy()` by hand.

## [2.1.1] - 2026-06-30

### Added

- `dblift.yaml` / `dblift.yml` are now auto-discovered from the current
  working directory when no `--config` or `--db-url` is given.

### Fixed

- **Every CLI command crashed on startup** with a `NameError` during license
  tier resolution.

## [2.1.0] - 2026-06-30

### Changed

- Rewrote the README opening for developer-first positioning: problem-first
  tagline, a 3-command quickstart (`validate`, `migrate --dry-run --show-sql`,
  `migrate`), and an explicit OSS/Pro tier callout.
- Rewrote the Getting Started guide (pip-first, OSS-only, tier-aware) and
  clarified configuration discovery: the `DBLIFT_DB_URL` environment variable
  is the primary workflow; `--config` is required to use a `dblift.yaml` file
  (dblift does not auto-discover it from the working directory as of this
  release — see 2.1.1 above, which added that auto-discovery).
- Fixed the CI/CD guide: corrected `actions/checkout@v6` references to `@v4`,
  added a `migrate --dry-run --show-sql` step to the GitHub Actions and
  GitLab CI examples, and updated the documented pre-commit `rev` to `v2.0.5`.
- Switched the README test-status badge from a static shields.io label to the
  live GitHub Actions workflow badge, and restored the codecov badge now that
  the repository is public.
- CI now gates PyPI publishing on the unit-test suite passing, so a release
  can no longer publish to PyPI while the unit suite is red.

### Fixed

- Fixed broken badge links and assorted documentation wording issues.

## [2.0.5] - 2026-06-25

### Fixed

- **`info` Description column rendered empty on narrow terminals** — the
  migration table printed to stdout with no explicit width, so on a narrow or
  piped terminal Rich collapsed the only flexible column (Description) to zero
  width, blanking it while the other (fixed-width) columns kept their space.
  The render width is now floored to the table's natural width, so every column
  stays visible; narrow terminals soft-wrap a complete table instead.

## [2.0.4] - 2026-06-25

### Removed

- Stripped non-functional placeholder surface for Pro/Enterprise-only commands
  (`validate-sql`, `diff`, `plan`, `export-schema`, `snapshot`) that shipped as
  dead code: their result types, output formatters, config schema, and CLI
  stubs. These commands have never been available in the open-source package;
  the dead code is now removed from the build. No user-facing behavior change.

## [2.0.3] - 2026-06-23

### Fixed

- **`--strict` CLI flag silently did nothing** on `migrate`/`validate` — argparse
  stored it on `args.strict`, but config merging looked for `strict_mode`, so the
  value was never read; out-of-order migrations applied with exit 0 even with
  `--strict` passed. Fixed by giving the flag `dest="strict_mode"`. Only the YAML
  `strict_mode: true` path worked before this fix.
- **Stale `repair` documentation** — docs claimed `repair` does not fix checksum
  drift on modified scripts; it does, and now the docs say so.

## [2.0.2] - 2026-06-22

### Fixed

- **Missing `packaging` dependency** — `migrate`/`validate` failed on a clean
  install with `No module named 'packaging'`; it's now a declared dependency.

## [2.0.1] - 2026-06-22

### Added

- **CLI extension opt-out** — set `DBLIFT_DISABLE_CLI_EXTENSIONS=1` to skip
  loading any installed CLI extensions, handlers, or terminal commands.

## [2.0.0] - 2026-06-18

### Fixed

- **Cross-provider clean consistency** — DB2 clean, clean preview, and
  `list_droppable_objects()` now share the same schema-operations path and keep
  DB2 explicit commits, while DB2 and SQLite rely on table drops to remove
  table-owned indexes instead of dropping those indexes independently.
- **Oracle quoted identifier lookups** — Oracle table existence checks now
  preserve quoted identifier case while continuing to normalize unquoted names.
- **Undo filter correctness** — `undo` now applies tag and version filters when
  selecting applied migrations and matching undo scripts, including histories
  that need tags recovered from source migration files.
- **SQLAlchemy integration config overlays** — `DBLiftClient.from_sqlalchemy()`
  now keeps engine-derived database connection identity authoritative when a
  caller also passes a config overlay, preventing metadata from reporting a URL
  different from the injected engine.

## [1.8.0] - 2026-06-12

**Python-native epic complete**. dblift 1.8.0 + pytest-dblift 0.1.0.

### Added

- **Full Python-native release**:
  - `DBLiftClient.from_sqlalchemy(engine, ...)` + `config_from_engine` (external engine ownership, no dblift lifecycle assume).
  - Public `MigrationContext` (from `api import MigrationContext`; enriched for Python migration scripts with client/config/placeholders/undo helpers).
  - `pytest-dblift` 0.1.0 (separate package: pytest11 entrypoint, `migrated_db`/`empty_db`/`validate_sql` fixtures, xdist-safe SQLite paths, undo script generation support).
  - Thin framework integrations: `dblift.integrations.fastapi` and `dblift.integrations.flask`.
  - Pip-first README, python-migrations guide, sqlalchemy-integration examples, FastAPI/Flask lifespan docs.
  - Django positioning (second DATABASES + from_sqlalchemy pattern; explicit non-goals).
  - Provider cookiecutter + plugin entry points / install extras docs (`docs/developer-guide/`).

- **Custom secrets provider registration** — third-party integrations can register
  any secrets backend at startup via `register_provider(scheme, cls)` without
  forking or patching dblift. The provider class must subclass
  `AbstractSecretsProvider` and implement `resolve(uri) -> str` and
  `is_available() -> bool`. Registered providers are immediately detectable by
  `is_secret_uri()` and participate in the same resolution and caching pipeline
  as any other registered provider.
  See [Custom Providers](user-guide/configuration.md#custom-provider-registration).

- **User-controlled SQL visibility** — `migrate` and `undo` now support
  `--show-sql` so users can see the SQL statements that will be executed without
  enabling debug logging. The flag works with dry-run and real execution and is
  independent from the selected log/report format.

### Removed

- **JVM/JDBC runtime layer** — DBLift now uses plugin-owned native SQLAlchemy
  drivers, SQLAlchemy URL handling, and vendor catalog queries for supported
  database providers. The bundled JRE/JDBC driver artifacts, JDBC provider
  infrastructure, and JDBC metadata fallback tests have been removed as part of
  the v2 breaking-change native-driver transition.
- **JDBC URL compatibility** — `jdbc:` URLs are no longer accepted or translated.
  Configuration, examples, tests, Docker assets, CI jobs, and recovery docs now
  use native SQLAlchemy URLs and native driver names only.

## [1.6.0] - 2026-05-15

### Fixed

- **CosmosDB `CREATE CONTAINER` emission now propagates partition key from
  table metadata** — generated CosmosDB container DDL was emitting an empty
  body (`CREATE CONTAINER container1 ()`) instead of the partition key clause,
  because the NoSQL-dialect check was bound too early to see the registered
  CosmosDB plugin. The dialect check now happens at call time, fixing both
  `CREATE CONTAINER` and `DROP CONTAINER` emission for CosmosDB.
- **`--target-version` may now be combined with `--exclude-versions`** to
  migrate up to a specific version while skipping intermediate ones; an
  unintended restriction from an earlier refactor was removed.

## [1.5.1] - 2026-05-07

### Fixed

- **Oracle schema quoting and history visibility**: SQL mixed quoted lowercase
  (`"dbo"."…"`) with unquoted uppercase (`DBO.…`) schema references. After
  `migrate`, `table_exists()` could probe the wrong casing so `info` reported
  **zero** applied migrations even though migrations had succeeded. All schema
  references now go through dialect-aware quoting, fixing the false "zero
  migrations applied" report.
- **DB2 schema existence check was case-insensitive while DDL was
  case-preserving**: a schema existence check could report "already exists"
  while the quoted `CREATE SCHEMA` statement targeted a different casing than
  what was actually stored, causing later DDL to fail. The lookup is now
  case-sensitive to match caller intent.

## [1.5.0] - 2026-05-06

### Fixed

- **CosmosDB `AttributeError` on container replacement**: fixed calls that invoked `replace_container` on the wrong client object, which raised an `AttributeError` whenever a CosmosDB migration replaced a container.
- **Crash when a dialect plugin set an unrecognized syntax-highlighting lexer name**: the CLI now validates the lexer alias and falls back to generic SQL highlighting instead of crashing.

## [1.4.1] - 2026-05-03

### Fixed

- **Baseline error message truncated**: when `baseline` was called on a schema that already had migration history, the informative "Schema X already contains N migration(s)" error was swallowed and replaced with a generic, less helpful message. The real message now reaches the terminal.
- **Repeatable migration (`R__`) permanently blocked after `repair`**: the validator looked up the *oldest* history entry for a repeatable script instead of the most recent one. If an old failure preceded a later success, `migrate` kept reporting "previously failed" and blocked all subsequent runs even after running `repair`. Fixed to evaluate the most recent application attempt, matching Flyway's per-entry state model.

## [1.4.0] - 2026-04-26

### Added

- **Migration script encoding detection**: optional Flyway-style `encoding:` config key (also settable via the `DBLIFT_ENCODING` env var). Before tokenisation, the script manager now detects the actual file encoding and decodes accordingly, preserving accented and non-ASCII SQL content instead of silently replacing invalid bytes with replacement characters.
- **Modern CLI console output via Rich**:
  - Severity styling on stderr: debug=dim, warn=yellow, error=bold red, success=bold green.
  - Migration history and migration-list tables now render with Unicode box-drawing instead of plain ASCII.
  - `dblift migrate` shows a progress bar with spinner, description, completed/total counter, and elapsed time. Failed migrations break the loop without bumping the completed count.
  - SQL previews render with syntax highlighting (PostgreSQL / MySQL / MariaDB / SQL Server / TSQL-specific lexers; other dialects fall back to generic SQL highlighting). File/JSON/HTML logs continue to receive raw SQL with no markup.
  - The command completion footer (success/failure status, execution time, applied scripts, schema version) renders in a styled panel.
  - Uncaught exceptions now render with rich tracebacks.
  - All styled rendering goes to stderr only; `--format json` and other machine-readable output on stdout is unaffected.
- **`--quiet` / `-q`** raises the *console* output threshold so only success/warn/error are shown (info/debug suppressed); file/JSON/HTML logs are unaffected and keep the full audit trail.
- **`--no-progress`** disables the progress bar in `migrate`. The `DBLIFT_NO_PROGRESS` env var is also honored for CI configs that pre-set the environment.

### Removed

- **`prettytable` dependency** dropped — fully replaced by the new table rendering.

### Changed (BREAKING)

- **Minimum Python raised to 3.11** (was 3.8). The codebase already required Python 3.10+ features and 3.11's `typing.Self`; the prior `requires-python = ">=3.8"` declaration was factually incorrect since the code did not import on 3.9 or 3.10. This release aligns the declared minimum with the versions actually tested (3.11, 3.12).

### Security

- **Bumped vulnerable dependency floors** addressing 17 known CVEs in `cryptography` and `PyJWT`, and in the build toolchain (`setuptools`, `wheel`).
- Removed an obsolete `dataclasses` backport dependency, unused since Python 3.7 added `dataclasses` to the standard library.

### Fixed

- **`migrate --dry-run` created the history table on real databases (Critical)**: a dry-run "preview" invocation could silently create the `dblift_schema_history` table on the target database before the dry-run check short-circuited. The history-table creation is now properly gated behind the dry-run check.
- **SQLite `clean --dry-run` crashed** with an `AttributeError` because the dry-run path used a JDBC-only introspection method. SQLite now has its own preview/enumeration path, so dry-run and real-clean can no longer drift apart.
- **Misleading "Could not enable autoCommit" warning on non-JDBC connections**: SQLite connections don't support the JDBC autocommit API, which triggered a confusing warning on every run. The warning is now properly guarded so it only applies to JDBC connections.
- **Double placeholder substitution in SQL migrations (Medium)**: `${...}` placeholders were substituted twice — once on the full migration content, and again per-statement. Usually a no-op, but if a placeholder's value itself contained a `${...}` fragment, the second pass could re-interpret and corrupt the SQL. The redundant per-statement substitution pass was removed.
- **`sqlite:///` URL dropped the leading slash from absolute paths (High)**: `sqlite:///tmp/x.db` was incorrectly turned into the relative path `tmp/x.db` instead of the RFC 3986–correct absolute `/tmp/x.db`. Fixed so absolute SQLite paths resolve correctly.
- **`--config` flag silently ignored for all migration commands (Critical)**: a duplicate `--config` declaration on subcommands overwrote the value already captured by the top-level parser, so the config file was never actually loaded. Removed the duplicate declarations across all subcommands.
- **`--scripts` flag silently ignored for all migration commands (Critical)**: same root cause as `--config` above — users who passed `--scripts /path/to/migrations` always saw a "directory not found" error because the subcommand default overwrote the specified path.
- **`--config /nonexistent` produced a misleading error (High)**: now correctly reports "Config file not found" instead of an unrelated "Database URL is required" error.
- **`db check-connection --db-url` always failed (High)** due to a config-loading path that didn't recognize how that subcommand stores its `--db-url` argument. Fixed.
- **`db validate-config --db-url` always failed (High)**: same class of fix as `check-connection` above.
- **`info` command had no `--format json` option (Medium)**: added `--format table|json` so migration status can be consumed by scripts/automation.
- **Oracle JDBC diagnostic logs polluted stdout (Medium)**: suppressed Oracle JDBC's internal diagnostic logging that was writing lines directly to stdout.
- **`SELECT *` was not consistently flagged during SQL validation (Low)**: the default severity for this rule was too low to surface by default; raised to `warning` so it shows up without extra flags.
- **`info --format json` leaked the human-readable migration table to stderr (Medium)**: the human-readable table was always rendered, even in JSON mode. Now suppressed when `--format json` is requested.
- **Repeatable migrations showed an empty string instead of `null` for version in `info --format json` (Low)**: fixed for cleaner downstream consumption.
- **Checksum lookup could match an `UNDO_SQL` row as "last applied" (High)**: after an undo, the undo record (with a zero checksum) could be returned as the authoritative checksum, triggering a false mismatch on the next `migrate` or `validate`. Both lookups now exclude `UNDO_SQL` rows.
- **`repair` checksum-drift detection silently skipped legitimately-zero checksums (Medium)**: a truthiness check treated a stored checksum of `0` the same as "missing," so drift was never flagged for those scripts. Fixed to check for `None` explicitly.
- **SQLite duplicate foreign keys not deduplicated (Low)**: multi-column foreign keys were emitted once per column rather than once per constraint during introspection. Deduplication now groups by constraint name.
- **CosmosDB DDL generated `CREATE TABLE` instead of `CREATE CONTAINER` (High)**: fixed; `CREATE INDEX` is now suppressed in favor of CosmosDB's indexing-policy model, with an explanatory comment in generated output.
- **CosmosDB delete operations queried a non-queryable field and always received `None` for the partition key (High)**, causing `repair` to fail with a 404. Fixed by reading the actual partition key path from the container's properties.
- **CosmosDB `extract_container_name` returned a quoted name (Medium)**: surrounding quote characters are now stripped.
- **CosmosDB 404s on a missing history container were logged at ERROR level (Cosmetic)**: this is expected on first run and after `clean`; demoted to DEBUG.
- **CosmosDB 404s during a repair-driven delete were logged at WARNING level (Cosmetic)**: expected when a previous repair sweep already removed the document; demoted to DEBUG.
- **CosmosDB `IF EXISTS` guard phrases leaked into extracted container names (Medium)**: fixed by stripping the guard phrase before name extraction.
- **CosmosDB snapshot capture was unreliable (High)**: a combination of placeholder handling, clean semantics, and index validation issues could cause snapshot capture to fail silently or produce incomplete results; all three are now aligned.
- **Oracle `%ROWTYPE` / `%FOUND` constructs silently dropped by the tokenizer (Medium)**: the tokenizer did not recognize `%` as a symbol character, so PL/SQL constructs like `cursor%ROWTYPE` were silently discarded. Fixed.
- **PostgreSQL Python-script undo history not committed atomically (High)**: after recording undo history, the transaction was not committed, so the record appeared rolled back on the next connection. Fixed.
- **PostgreSQL performance analysis false positives on partial indexes (Low)**: partial-index `WHERE` predicates triggered spurious lint warnings; predicates are now normalised before linting.
- **MySQL `autocommit` not restored after `validate` (Medium)**: `validate` disabled `autocommit` for transactional checks but didn't restore it before returning the connection to the pool, leaking the setting into subsequent commands. Fixed.
- **SQLite script names not preserved in undo history (Medium)**: the undo record stored the full file path instead of the canonical script name, breaking `info` and `repair` lookups. Fixed.
- **SQLite SQL generation and validation were not fully supported (Medium)**: several code paths short-circuited for SQLite before reaching the shared generation/validation pipeline; SQLite now participates fully.
- **SQLite `sqlite:///` URL variants and FTS virtual-table statements were dropped during schema export (Medium)**: both are now handled.
- **Validation was not scoped to the target migration range (Medium)**: checksum and missing-script checks ran against the full history even when a `--target` version was specified; checks are now constrained to the resolved range.
- **Default config setup forced non-JDBC providers (e.g. CosmosDB) through JDBC validation (High)**: typed config is now built only after raw source merging completes, so non-JDBC providers no longer fail validation meant for JDBC connection strings.
- **`clean` summary suppressed duplicate object names (Low)**: identical names under different object types (e.g. a package and its package body) were deduplicated away in the summary; a `dedupe=False` option preserves them in the clean summary specifically.
- **Performance analyzer applied to procedural SQL (Low)**: stored procedures, functions, and trigger bodies were passed through the SQL performance analyzer, producing false positives for PL/SQL and T-SQL constructs. Procedural blocks are now detected and skipped.
- **Undo script error messages lost the migration path on failure (Low)**: the path was cleared before the error handler ran, making the log message unhelpful. Fixed.
- **Batch undo file-exists errors were silently swallowed (Low)**: now propagated so callers can surface them.
- **SQL warning scan was case-sensitive (Low)**: a check for `"Warning"` missed mixed-case occurrences in generated SQL; now lowercased before scanning.
- **`mark-as-executed` history rows not committed (High)**: the row was rolled back on connection close because the transaction was never explicitly committed. Fixed.
- **CosmosDB regex parser not registered for migration validation (High)**: `validate` fell back to generic SQL parsing and missed CosmosDB-specific syntax. The CosmosDB-specific parser is now registered.
- **Oracle `SPOOL` path spacing corrupted (Low)**: paths containing spaces had their internal spacing collapsed during normalisation; fixed to preserve spacing within the path argument.

## [1.3.1] - 2026-04-14

### Fixed

- **Python migrations silently rolled back (Critical)**: Python migration scripts now run inside an explicit begin/execute/record/commit transaction lifecycle, mirroring the SQL execution path, with rollback on failure. Previously, DDL emitted from a Python script could be wiped out by the next migration's transaction setup before it was ever committed.
- **SQLite unusable via `jdbc:sqlite:` URLs (Critical)**: SQLite (and other non-JDBC providers) is now correctly recognized when configured via a `jdbc:`-prefixed URL; previously the type could be silently overwritten with `None`, breaking provider selection entirely.
- **`repair` broken on Oracle, SQL Server, and SQLite (High)**: fixed by using the correct dialect-specific boolean literal (Oracle/SQL Server/SQLite don't accept the same `FALSE` literal as PostgreSQL/MySQL/DB2).
- **`--config FILE db <subcmd>` routing**: fixed argument routing so that `dblift --config F db check-connection` no longer mistakenly consumes `F` as a positional argument of the `db` subcommand.
- **`db validate-config --config F` ignored the file**: now actually loads and uses the specified config file instead of building config from CLI flags only.
- **`MigrationContext` missing an `execute()` helper**: added `MigrationContext.execute(sql, params=None)` so Python migration scripts can run arbitrary SQL against the active connection without reaching into provider internals.
- **`argparse` errors exited with code 0**: invalid CLI invocations (e.g. `dblift baseline` with missing required args) now correctly exit with status 2, so shell scripts can detect them.
- **Misleading `Error_Rate: 100.0%` in output**: a quality score of 1.0 (no errors) was displayed under a confusingly-named label; relabeled to `Success_Rate` for clarity (the underlying data is unchanged).
- **Unreadable traceback on `db check-connection` failure**: full tracebacks are now only shown at `--log-level debug`; normal runs show a clean one-line failure message.
- **`check-connection` raised raw tracebacks on auth/network failures**: common failure modes (connection refused, bad credentials, unknown host) are now mapped to clear, specific messages.
- **`--config FILE` with a missing file failed silently**: now raises a clear error and exits with status 1.
- **Partial environment-variable config overrides were rejected**: env-var config like `DBLIFT_DB_URL` without a matching password no longer fails strict validation when merging onto a base file config.
- **`repair` on failed repeatable (`R__`) migrations**: now correctly routes to delete-and-retry instead of trying to update a non-existent successful row.

## [1.2.0] - 2026-04-10

### Fixed

- **CosmosDB provider methods could silently operate on a `None` connection**: a guard now raises a clear error immediately if a provider method is called before `create_connection()`.
- **Oracle history manager column naming**: renamed an internal column to match the shared history-manager contract directly, removing a key-remapping step.

## [1.1.1] - 2026-04-05

### Fixed

- **SQLite schema-snapshot table used a legacy column layout**: legacy layouts are now detected, backed up, recreated, and migrated to the standard columns automatically.
- **SQLite regex parser signature mismatch**: brought in line with the shared parser interface.
- **`repair` checksum-drift detection used a filtered (undone-migrations-excluded) view of history**, which could hide real mismatches; now uses the unfiltered view, with a safe fallback when unavailable.
- **Failed migration rows are now deleted instead of marked with a null success flag**, matching Flyway-style retry semantics and avoiding constraint violations.
- **`check-connection` JDBC URL resolution**: PostgreSQL, MySQL, Oracle, DB2, and SQLite providers now expose their JDBC URL consistently; `check-connection` falls back gracefully when a provider doesn't.
- **`generate_undo_script` raised instead of returning a failure result** for missing/existing files and invalid values; now returns a proper failure result, with the undo path still logging the failure before re-raising for missing scripts.
- **`info` did not always populate `current_schema_version` from applied migrations**: fixed.
- **Migration status normalization**: `BASELINE` status is now preserved exactly end-to-end (no accidental matches on unrelated text).
- **SQLite regex parser incorrectly conflated `CASE...END` blocks with trigger `BEGIN...END` blocks**: depth tracking is now separate for each.
- **Config merge edge cases**: YAML config now merges correctly onto defaults — an explicit `database: null` in YAML is ignored rather than wiping out defaults, file config takes precedence as the merge base when it defines a `database` section (avoiding default-dialect settings leaking into other dialects), and merging was extended to cover `strict_mode`, journal settings, retry/error fields, CLI log overrides, and non-dict sections defensively.
- **Non-transactional DDL handling**: MySQL and Oracle, which don't support transactional DDL, now get an explicit warning on partial DDL failure during execution and repair instead of silently assuming transactional safety.
- **`--config` migration directory resolution**: migration directories specified via `--config` now resolve relative to the config file's directory, not the process's current working directory.
- **CosmosDB query executor did not strip trailing semicolons**, which could break execution; fixed.
- **CosmosDB `repair` now uses inline values and a lowercase `false` literal** to match the Cosmos SQL API's lack of parameter placeholders and its boolean literal conventions.

### Added

- **SQLite virtual table support**: added a dedicated object type with parser and ordering integration for SQLite virtual tables.

## [1.1.0] - 2026-04-03

### Fixed

- **`return_generated_keys=True` silently ignored on MySQL and DB2 (High)**: the flag is now correctly wired to retrieve generated keys on both dialects, matching existing Oracle/PostgreSQL behavior.
- **MySQL and DB2 execution errors were only visible at DEBUG log level (Medium)**: now logged at ERROR level, consistent with Oracle/PostgreSQL.
- **Schema names were not validated, allowing SQL injection via config (High)**: schema names are now validated against a safe identifier pattern at config-parse time, protecting all downstream DDL interpolation sites.
- **Oracle metadata queries used case-sensitive matching against catalog views (Medium)**: queries now bind owner/table names case-insensitively, restoring CHECK-constraint and virtual-column introspection when casing differs from the catalog, and no longer discarding unique constraints solely because the backing index name looks system-generated.
- **Oracle CHECK constraint text and virtual-column expressions were excluded when long (Medium)**: now read correctly via `LONG` column handling, restoring that metadata for diff/compare.
- **SQL Server tokenizer mishandled `@local` and `@@global` T-SQL variables (Low)**: now treated as single tokens, fixing batch splitting around them.
- **Execution engine lacked a reliable JDBC pre-check for DB2 and Oracle (Medium)**: added a dialect-aware pre-check; comment-only migration batches are now skipped before execution.
- **`DBLiftClient` did not honor nested logging config keys (Low)**: `logging.file`, `log_dir`, and `logging.directory` are now read correctly and defensively.
- **`build_connection_string()` silently fell back to building a synthetic `jdbc:` URL for non-JDBC providers (Medium)**: now raises a clear error instead, since native drivers should never receive a fabricated JDBC string.

### Changed

- **Flyway-compatible history table**: history table is now structurally identical to `flyway_schema_history` — checksum algorithm changed to CRC32 (from MD5), the `script_name` column renamed to `script`, `MigrationType.VERSIONED` renamed to `MigrationType.SQL`, and NOT NULL constraints added on the core tracking columns. `import-flyway` was updated for the aligned schema.

## [Previous]

### Added

- **Python Migration Support**: new Python (`.py`) migration script support alongside SQL migrations, with `MigrationContext` providing database connection and metadata access, full dry-run and validate support, and Python callbacks routed symmetrically with SQL callbacks.
- **Provider capability interfaces**: providers now declare connection/query/schema/transaction/migration capabilities explicitly (e.g. `CosmosDbProvider.supports_transactions()` correctly returns `False`), replacing fragile `hasattr`-based capability checks.

### Fixed

- **SQL injection hardening**: parameterized queries enforced across query execution and statement execution paths.
- **Credential masking**: passwords and usernames are now masked in all log output, including the Oracle thin-driver `user/pass@` URL pattern.
- **Resource leaks (MySQL)**: statements and result sets are now reliably closed via `try/finally`.
- **Resource leaks (connections)**: `check_connection()` now closes the connection via `try/finally` regardless of outcome.
- **`schema_exists()` raised `NotImplementedError` instead of checking (various dialects)**: replaced with real dialect-aware catalog queries (Oracle, DB2, and a default `INFORMATION_SCHEMA`-based check); CosmosDB and SQLite now have correct schema-less/PRAGMA-based handling respectively.
- **`--confirm` flag for `clean`** was not actually wired through to the underlying clean execution; fixed end-to-end.
- **Early log initialization**: the logger is now created before config loading, preventing a crash on startup config errors.
- **CosmosDB SSL bypass was applied globally instead of scoped to the CosmosDB connection**: fixed.
- **Duplicate migration-history recording on failure**: a duplicate history write in the failure-handling path was removed.
- **YAML config-format auto-detection false-positived on SQL comments containing a colon**: detection regex narrowed to exclude keys containing spaces.
- **Computed-column expression diffs were accidentally suppressed**: restored.
- **Unset dialect could be reported as the literal string `"none"`**: guarded.

## [1.0.1] - 2026-01-09

### Fixed

- **MySQL statement parser**: fixed a critical bug where an internal "in stored program" flag was never reset between statements, causing subsequent `BEGIN` blocks (e.g. transactions) to be incorrectly treated as stored-program block starts. Context now properly resets for each new statement while preserving the active delimiter.

## [1.0.0] - 2025-12-16

### Changed

- Promoted from beta to stable 1.0.0 release; all major features implemented and tested across PostgreSQL, MySQL, Oracle, SQL Server, DB2, CosmosDB, and SQLite.

### Fixed

- **Oracle SQL syntax fixes**: corrected `table_exists` query casing and schema-qualified identifier quoting.
- **DB2 SQL syntax fixes** in schema/table-existence handling.
- **CosmosDB parser fix**: corrected statement splitting for `DELETE`/`UPDATE` statements without a trailing semicolon; fixed CosmosDB Emulator SSL connection issues.
- **`undo` with tag/version filters**: fixed filtering during undo command execution.
- **Multi-command parsing**: `--generate-sql` was missing from the boolean-flag list, and exit codes from multi-command mode were not propagated correctly; both fixed.

## [0.9.0-beta] - 2025-12-09

### Added

- **DB2 database support**: full schema introspection (tables, views, indexes, sequences, triggers, procedures, functions, synonyms), identity and generated columns, table compression, XML data types, partitioned tables, composite primary keys, multiple foreign keys, and complex CHECK constraints. Remote DB2 connections supported via environment variables.
- **CosmosDB enhanced support**: pseudo-SQL to Azure SDK translation (DROP/ALTER CONTAINER, SET THROUGHPUT, CREATE INDEX, SET TTL), schema inference for nested objects and mixed types, indexing-policy introspection, and support for both the CosmosDB Emulator and external instances.
- **SQL Server enhanced support**: indexed views, synonyms, temporal tables, partitioned tables, filegroups, spatial data types (GEOMETRY, GEOGRAPHY), HierarchyID, graph tables, full-text search, and XML/JSON columns.
- **MySQL enhanced support**: remote connection support via environment variables; generated columns, JSON data types, spatial types, and partitioning.
- **Oracle enhanced support**: virtual columns, identity columns, packages, materialized views, and other advanced features.

### Changed

- **DB2 trigger syntax**: corrected to use the `REFERENCING` clause with `BEGIN ATOMIC ... END` for `BEFORE INSERT` / `AFTER UPDATE` triggers, fixing trigger creation and introspection.
- **DB2 transaction handling**: cleanup operations now commit explicitly, fixing hangs and inconsistent state after DB2 cleanup.
- **CosmosDB SDK translator**: added support for `SET AUTOSCALE` and `EXCLUDE/INCLUDE INDEX PATH` operations.

### Fixed

- **Out-of-order migration execution incorrectly skipped (Critical)**: migrations with versions lower than the current version were being treated as "covered by baseline" even when no actual baseline existed. Baseline-skipping now only applies when an actual `BASELINE` history entry is present, so legitimate out-of-order migrations (e.g. V1.0.3 applied after V1.1.0) execute correctly.
- **DB2 case-sensitivity issues**: table, index, and trigger names are now correctly case-normalized for introspection.
- **CosmosDB SDK translator parameter mismatch**: `throughput` corrected to `offer_throughput` for `ALTER CONTAINER` operations.

## [0.8.0-beta] - 2025-12-01

### Changed

- **Connection management architecture**: providers now own their connection explicitly and pass it to components as a parameter, rather than components each holding their own stored reference. This makes database components stateless and removes a class of connection-synchronization bugs.
- **Command header/footer formatting unified** across all CLI commands: headers now show database name, schema name, and a masked database URL (supporting both JDBC and non-JDBC connection strings, including CosmosDB account keys).

### Fixed

- **Transaction state corruption when creating new connections**: internal transaction-state flags are now reset whenever a fresh connection is created, preventing spurious "Connection is closed during active transaction" errors.
- **Integration test history contamination between runs**: cleanup now deletes history records before cleaning the schema, fixing a class of "already contains migration history" failures.
- **PostgreSQL sequence generation syntax error**: removed an invalid `NOCYCLE` keyword (PostgreSQL uses `NO CYCLE`); `CYCLE` is now only emitted when explicitly requested.
- **Azure Cosmos DB support completed**: full migration support via the Azure SDK for Python, including ETag-based optimistic concurrency locking with a document-based fallback, schema introspection for containers/indexes/documents, partition key and indexing-policy support, throughput (RU/s) configuration, and local CosmosDB Emulator support with SSL handling.
- **CLI failed to detect a missing database URL**: previously surfaced an unrelated "username" error instead of "Database URL is required"; fixed to check CLI args, config file, and environment variables consistently.
- **Sequence SQL generation dropped `NOCYCLE` when no dialect was specified**: fixed so generic (dialect-less) sequence generation correctly includes `NOCYCLE` when `cycle=False`.

## [0.4.0-beta] - 2024-10-31

### Fixed

- **Strict-mode bypass**: an early return was bypassing strict-mode validation, allowing out-of-order migrations through even when strict mode was enabled. Fixed; strict mode remains disabled by default for backward compatibility.
- **`baseline` command**: migrations with versions at or below the baseline are now correctly skipped going forward — previously they could still be executed, or could cause "table already exists" errors after baselining.

## [0.3.0-beta] - 2025-01-28

### Added

- **DB2 database support** with full integration.
- **Version and tag filtering for the `undo` command.**
- **HTML reports with undo support.**
- **Placeholder replacement in callback scripts.**
- **Script file encoding configuration** (utf-8, windows-1252, iso-8859-1).
- **Windows Authentication support for SQL Server.**

### Changed

- Migrated from a pure regex-based SQL parser to a hybrid parser combining regex-based statement splitting with AST-based analysis, improving parsing reliability for procedural SQL (PL/SQL, T-SQL, PL/pgSQL) and pure SQL alike.
- Route ERROR and WARNING log messages to stderr in console output.
- Case-insensitive handling of the log-level configuration parameter.

### Fixed

- **DB2 parser fixes**: optional `ATOMIC` clause in trigger detection, `CASE` expression handling, nested `BEGIN`/`END` blocks, and `@` delimiter support for procedures/triggers/functions.
- **MySQL parser fixes**: delimiter markers properly stripped from statements; `DETERMINISTIC` keyword handling in function definitions; identifier quoting improvements.
- **SQL Server `IDENTITY_INSERT` errors** during migration history recording.
- **PostgreSQL advisory lock SQL syntax** corrected.
- **Repeatable migration conditional logic** fixed.
- **`baseline` now commits its transaction properly.**
- **NULL parameter handling** fixed in DB2 and MySQL JDBC drivers.
- **Custom history table name configuration** flow fixed.
- **Lock acquisition handling** fixed across all database types.

## [0.2.0-beta] - 2025-XX-XX

### Added

- **Migration Journal System**: detailed tracking of migration execution with statement-level timing, performance summaries, and an object-type breakdown, available across Console, Text, HTML, and JSON output formats.

### Fixed

- Logger parameter naming consistency.

## [0.1.0-beta] - 2025-XX-XX

### Added

- Initial release of DBLift database migration tool.
- Multi-database support: SQL Server, Oracle, PostgreSQL, MySQL.
- Flyway-compatible migration naming conventions.
- Three migration types: versioned (`V{version}__{description}.sql`), repeatable (`R__{description}.sql`), and undo (`U{version}__{description}.sql`).
- Transaction safety with automatic rollback on failure.
- Tag-based migration filtering for selective execution.
- Support for subdirectories and multiple migration directories.
- Command-line interface with core commands: `migrate`, `info`, `validate`, `undo`, `clean`, `baseline`, `repair`.
- JDBC-based database connectivity with bundled JRE.
- Comprehensive error handling with automatic retry for transient errors.
- Multiple log formats: TEXT, JSON, HTML.
- Configuration via YAML files, environment variables, or CLI arguments.
- Cross-platform distributions (Windows, Linux, macOS).
- Modular provider architecture for easy database support extension.
