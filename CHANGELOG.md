# Changelog

All notable changes to DBLift will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

### Removed

## [3.3.2] - 2026-07-29

Release-qualification follow-ups after 3.3.1: multi-dialect CLI/API
edge cases from the OSS functional suite, MariaDB snapshot and
UPDATE-subquery capability alignment, YugabyteDB transactional-DDL
truthfulness, and a fourth instance of the same one-shot registry latch
pattern.

### Fixed

- **YugabyteDB no longer claims transactional DDL.** YSQL auto-commits
  `CREATE`/`ALTER`/`DROP` (objects survive `ROLLBACK`), so inheriting
  PostgreSQL's `supports_transactional_ddl=True` over-claimed the engine
  and misled migration recovery. The PG-wire plugin factory accepts
  `quirks_overrides` and installs matching provider capability methods;
  YugabyteDB sets the flag to `False` on both quirks and the provider
  API so the dialect-capabilities matrix stays consistent.

- **MariaDB can create database-stored snapshot tables again.** The
  dialect had opted out of both managed and provider-compat snapshot
  DDL, so any path that needs a live `dblift_schema_snapshots` table on
  MariaDB failed at create time. MariaDB now inherits the MySQL-family
  compat path (`CREATE TABLE IF NOT EXISTS … ENGINE=InnoDB` with a
  `LONGTEXT` model payload and the matching existence-check skip) so
  `BaseSnapshotManager` can open the table the same way MySQL does.

- **MariaDB no longer forces a derived-table wrap on self-referencing
  `UPDATE … WHERE id IN (SELECT … FROM same table)`.** Only MySQL
  needs that reshape (error 1093). The capability flag
  `update_subquery_requires_derived_table` is now `False` for MariaDB
  so generated SQL and the live capability probe match the engine.

- **`attach_registered_sql_generators()` no longer latches “bootstrapped”
  when nothing registered.** The one-shot `_bootstrapped` flag was set
  unconditionally before `load_feature_extensions()` ran, even when
  `_registrars` stayed empty. A later successful extension discovery
  never retried, so SQL generators that register through that path
  never attached for the rest of the process. The latch now closes only
  when `_registrars` is non-empty after discovery (same shape as the
  `AlterGeneratorFactory`, feature-loading, and
  `ProviderRegistry.discover_plugins` fixes in 3.3.0 / 3.3.1).

- **Release-qualification fixes across Oracle, DB2, CosmosDB, SQL Server,
  and PostgreSQL** (OSS functional suite against a clean 3.3.1 wheel):
  - **CosmosDB** `import-flyway` queried the wrong container because the
    client cache was keyed by a single attribute instead of table name.
  - **CosmosDB** `--db-password` → `account_key` fallback was unreachable
    because validation ran before the fallback assignment.
  - **`migrate` / `validate` with `--tags` / `--exclude-tags`** falsely
    warned that applied migrations were missing from disk when they
    were only filtered out of scope (escalates under `--strict`).
    Checksum validation now receives the full on-disk script list so
    filtered-out applied rows are not treated as missing files.
  - **`info --tags` / `--versions` / `--exclude-tags` /
    `--exclude-versions`** were silent no-ops; filters now reach the UI.
  - **Oracle `clean`** reported failure on schemas with triggers whose
    owning table was already cascade-dropped (`ORA-04080`), even when
    cleanup fully succeeded.
  - **Oracle `import-flyway`** failed against a real Flyway history table
    due to identifier case-folding on the default source table name.
  - **`import-flyway --dry-run`** created the history table and, for some
    providers, never opened a connection at all. Dry-run now connects
    without writing history DDL.
  - **`baseline --dry-run`** no longer creates the history table as a
    side effect of its precondition check, and no longer reports success
    for a baseline that would fail the real precondition on PostgreSQL.
  - **DB2 `clean`** left SQL-bodied user-defined functions behind (wrong
    `ORIGIN` filter) and showed internal specific-names instead of real
    names in preview output.
  - **DB2 `validate --validate-only`** reported success after silently
    swallowing a schema-history bootstrap failure (and dumping a raw
    traceback). Bootstrap failure now fails the command.
  - **SQL Server `db check-connection`** printed the database password in
    plaintext; successful connection output now masks credentials in the
    URL.
  - **Connection and statement errors** no longer leak raw SQLAlchemy
    wrapper class names and doc-link trailers into user-facing messages
    (Oracle, SQL Server, DuckDB, and shared `format_connection_error`
    paths).
  - **Oracle** no longer logs a misleading “applying anyway” warning for
    migrations excluded by a tag/version filter.
  - **Docs:** Python undo scripts document the `migrate()` entry point,
    not a non-existent `undo()`.

## [3.3.1] - 2026-07-28

A CosmosDB write-path follow-up, and a third instance of the same
lazily-populated-registry latch bug fixed twice already in 3.3.0.

### Added

- **CosmosDB has a native document-delete primitive:**
  `CosmosDbQueryExecutor.delete_native_item(container_name, item_id,
  partition_key)`, plus a thin `CosmosDbProvider.delete_native_item` forward.
  The delete-side counterpart to 3.3.0's `upsert_native_item`: the sibling
  monorepo's schema-snapshot repository prunes old snapshots by rendering a
  SQL `DELETE` and routing it through `execute_statement`, which raises
  `NoSqlWriteNotSupportedError` for CosmosDB just like the `INSERT`
  `upsert_native_item` was added to replace — Cosmos's SQL API rejects any
  DML verb, not only writes. This closes the gap so the monorepo's pruning
  path can be wired the same way the single-document write already was.

### Fixed

- **`ProviderRegistry.discover_plugins()` had the identical
  unconditional-latch bug already fixed twice in 3.3.0**
  (`AlterGeneratorFactory._ensure_populated`,
  `core.seams.feature_loading.load_feature_extensions`), one layer over
  third-party `dblift.providers` plugins. `discover_plugins()` runs an
  entry-point pass and a filesystem fallback that always finds OSS's own 19
  shipped dialects (they live as directories inside this wheel), which
  masked the bug: a third-party entry-point package — unreachable by the
  filesystem scan — whose entry point isn't yet visible via
  `importlib.metadata` on the first call would never get a second chance,
  since the latch still closed on the strength of the filesystem-found
  first-party dialects. The entry-point pass now reports whether it found
  anything, and the latch is keyed on that instead of closing
  unconditionally; the common case (entry-points find all first-party
  dialects) is unaffected.

## [3.3.0] - 2026-07-28

A capability-probe catch, a driver-quirk decoding bug across two related
fixes, a native write path for CosmosDB, and two lazily-populated registries
that cached an empty result forever.

### Added

- **CosmosDB has a native, non-SQL document-write primitive:**
  `CosmosDbQueryExecutor.upsert_native_item(container_name, document)`, plus a
  thin `CosmosDbProvider.upsert_native_item` forward. A prior removal of
  CosmosDB's pseudo-SQL DML translation (the Cosmos SQL API is read-only, and
  the emulator that used to fake `INSERT`/`UPDATE`/`DELETE` support was
  actively wrong) correctly ported container *creation* to a native Azure SDK
  call, but there was no equivalent native path for writing a single
  document — an internal caller that needs one had to build a plain SQL
  `INSERT` and route it through `execute_statement`, which is SELECT-only and
  raises `NoSqlWriteNotSupportedError` for anything else. This adds the
  missing primitive (`azure.cosmos.ContainerProxy.upsert_item`, called
  directly).

### Fixed

- **SQL Server `IDENTITY` seed, increment, and last-value can now be
  introspected without corrupting generated DDL.** `sys.identity_columns`'
  `seed_value`/`increment_value`/`last_value` columns are typed
  `sql_variant`, and pymssql/FreeTDS can return a `sql_variant` int as raw
  on-wire bytes rather than a Python `int` (e.g. the int `1` as
  `b'\x01\x00\x00\x00'`). Those bytes were passed straight through onto the
  column model, and the SQL Server DDL quirk then formatted them into
  generated `CREATE TABLE` statements as-is —
  `IDENTITY(b'\x01\x00\x00\x00',b'\x01\x00\x00\x00')` — which SQL Server
  rejects outright with `Incorrect syntax near 'b'.`, breaking every
  round-trip test (and, for real users, every round-trip operation) against
  a table with an `IDENTITY` column. All three fields are now decoded to a
  signed integer at the point they're first captured (SQL Server genuinely
  supports negative `IDENTITY` seed/increment — `IDENTITY(-1,-1)` counts
  down — so the decode has to be signed, not just any decode). SQL Server
  also permits `IDENTITY` on `decimal`/`numeric` columns, whose `sql_variant`
  wire shape is a sign byte plus an *unsigned* magnitude rather than a plain
  two's-complement integer; decoding that shape the same way would silently
  produce a wrong value, so a byte width that doesn't match a standard
  integer size (1, 2, 4, or 8 bytes) is now rejected with a clear error
  instead of guessed at — full decimal/numeric `IDENTITY` support needs
  live-server verification this fix doesn't have yet.

- **DB2's declared row-limit capability matched only part of what a live
  server actually does.** `select_supports_limit = False` claimed DB2
  rejects a bare trailing `SELECT ... LIMIT n` clause; a live DB2 12.01.0500
  server accepted it, caught by the capability-probe suite that exists
  specifically to catch a declared dialect capability contradicted by the
  real engine. DB2 still renders `FETCH FIRST n ROWS ONLY` as its preferred
  form (unchanged), but it also tolerates a bare `LIMIT`, so the coarser
  "may an optional probe append `LIMIT` at all" question now answers `True`
  for DB2. Oracle and SQL Server are untouched — there is no equivalent
  live-probe evidence for either.

- **Two lazily-populated registries no longer cache an empty result as
  "done" for the rest of the process.** `AlterGeneratorFactory
  ._ensure_populated()` and `core.seams.feature_loading
  .load_feature_extensions()` both set their one-shot "populated" flag
  unconditionally, even on a call that found nothing to register. In a
  process where plugin/entry-point discovery hasn't finished wiring up yet —
  the paid-tier packages' `dblift.features` entry points not yet reachable
  from this process's view of installed metadata is the documented case —
  the empty result got latched permanently, and a later call that *would*
  have found the real registrations short-circuited on the stale flag and
  never retried. Both now latch only when discovery actually found
  something to register; a discovery pass that completes and genuinely
  finds nothing (every OSS-shipped dialect's real, permanent default for
  `alter_generator_class()`) is unaffected and still latches as before.

## [3.2.1] - 2026-07-27

Two silent-failure fixes in schema drift detection, and the repair of the
pre-push quality gate that could not have caught either of them.

### Fixed

- **Schema snapshots no longer record zero indexes on every dialect but SQL
  Server.** Bulk index retrieval is an optional capability: a dialect that does
  not implement it was supposed to signal "ask me table by table" so the caller
  would fall back to per-table introspection. That signal was flattened into an
  empty list, which reads as "this schema has no indexes" — indistinguishable
  from the truthful answer. Every dialect without a bulk index query, and every
  dialect shipping no vendor queries at all (Cosmos DB), therefore captured
  snapshots containing no indexes, and the per-table fallback never ran.

  The user-visible consequence was silent, confident wrong answers: dropping an
  index outside of migrations and running `diff` reported a clean comparison at
  completeness 1.0 and HIGH confidence, because the snapshot on both sides
  agreed there were no indexes to compare. Index drift is now detected on every
  dialect. An index-free schema still reports as index-free — "I could not
  answer" and "the answer is none" are now distinct.

- **SQLite schema snapshot capture is enabled again.** The SQLite provider was
  the only one of the 18 providers to override `supports_snapshots()` to
  `False` and to raise `NotImplementedError` from
  `create_snapshot_table_if_not_exists`, so snapshot capture silently did
  nothing on SQLite. `ProviderInterface` reserves that override for providers
  whose snapshot repository queries *cannot be executed*; SQLite's execute
  fine. Both overrides were removed, so SQLite now inherits the shared
  `BaseSnapshotManager` path and the `BaseQuirks` snapshot DDL that already
  named SQLite among its intended users. The snapshot table is created in
  `main`, as `docs/user-guide/configuration.md` already documented. Sibling
  plugins (MariaDB, MySQL, Oracle, SQL Server, DB2) express snapshot
  ownership through their quirks and leave the capability alone; SQLite now
  matches that convention.

### Changed

- **The pre-push quality gate passes again.** `scripts/check_code_quality.sh`
  exited non-zero on a clean checkout, because four of the config files it
  reads had never accompanied it from the monorepo it was copied from. flake8
  in particular was failing on ~15,800 line-length violations — invisibly,
  since that stage sets its exit code without printing a failure marker. A
  gate that cannot pass on an unmodified tree cannot tell a contributor's
  breakage from its own, so it stops being run. No packaged behaviour changes.

## [3.2.0] - 2026-07-26

### Fixed

- **SQLite `sqlite://` URLs now resolve exactly as SQLAlchemy resolves them.**
  dblift used to strip the `sqlite://` prefix and parse what remained per RFC
  3986 (empty authority, so the following slash is part of the path), which
  resolved `sqlite:///release.db` to the **filesystem root** (`/release.db`).
  SQLAlchemy resolves the same string to `release.db`, relative to the
  current working directory — and dblift fed the identical URL string to both
  its own native `sqlite3` connection (RFC-3986 reading) and to SQLAlchemy
  (relative reading) for anyone using `from_sqlalchemy` or the SQLAlchemy
  engine path, so the two connections silently addressed **different files**
  for one config. dblift now adopts SQLAlchemy's convention everywhere:
  three slashes is relative to cwd, four slashes is absolute,
  `sqlite:///:memory:` is unchanged. The parsing lives in one place,
  `db.plugins.sqlite.config.sqlite_path_from_url`, used by both the native
  connection manager and the config loader, so the two can no longer drift
  apart.

  **This is a behavior change if you wrote `sqlite:///abs/path.db` meaning an
  absolute path.** That URL now resolves to `abs/path.db` relative to the
  working directory, not `/abs/path.db`. If you meant an absolute path, add a
  fourth slash: `sqlite:////abs/path.db`.

- **Filesystem plugin discovery no longer overwrites a plugin's declared
  metadata.** The fallback scan decided whether a plugin was already
  registered by comparing its *directory name* against the registry, which is
  keyed by declared name and dialects instead. Python package names cannot
  contain hyphens, so any plugin whose dialect key has one necessarily lives
  in a differently-spelled directory (`aurora_postgresql/` declaring
  `aurora-postgresql`) — the check missed, the plugin was reloaded, and the
  richer entry-point declaration was replaced by a reconstruction. The check
  now uses the loaded plugin's own identity, and the reconstruction copies
  every `PluginInfo` field it did not derive itself rather than naming them
  one by one, so a field added later cannot be silently dropped.

- **`dblift list-drivers` no longer reports Cosmos DB as available without its
  SDK.** A plugin declaring no native driver module was treated as always
  satisfied, which was true by accident while the Azure SDK shipped
  unconditionally. Cosmos DB now declares `azure.cosmos` and its extra, so
  `list-drivers` and `db diagnose` tell the truth on a bare install, and the
  Cosmos DB connection error names `pip install "dblift[cosmosdb]"` instead of
  the raw PyPI package names. Note that `dblift db validate-config` for a
  Cosmos DB configuration now **fails** when the SDK is absent, where it
  previously passed — that command reports whether the configuration *and its
  driver* are usable.

### Added

- **A missing optional database driver now names the `pip install` command
  that fixes it.** `pip install dblift` intentionally installs no database
  drivers, so the first real command against, e.g., PostgreSQL failed with
  SQLAlchemy's raw `No module named 'psycopg'` — accurate, but silent about
  the fix. Every plugin with a native driver now declares the
  `pyproject.toml` extra that installs it (`PluginInfo.install_extra`), and
  the error raised from engine creation is rewritten to
  `Native driver module 'psycopg' is not installed for postgresql. Install
  it with: pip install "dblift[postgresql]"` whenever the failure is
  provably the declared driver's absence — an unrelated `ModuleNotFoundError`
  (e.g. a typo'd YAML import) is left untouched. SQLite declares no extra,
  since it needs nothing installed.

- **A missing SQLAlchemy *dialect* package now names its extra too.** Four
  extras ship a SQLAlchemy dialect rather than only a DBAPI —
  `dblift[snowflake]` (`snowflake-sqlalchemy`), `dblift[redshift]`
  (`sqlalchemy-redshift`), `dblift[db2]` (`ibm_db_sa`), `dblift[duckdb]`
  (`duckdb_engine`). With one of those absent, engine creation failed earlier
  than the driver import above and with a different exception:
  `sqlalchemy.exc.NoSuchModuleError: Can't load plugin:
  sqlalchemy.dialects:snowflake`, which subclasses `ArgumentError` rather than
  `ModuleNotFoundError` and so reached the user raw. It is now rewritten to
  `SQLAlchemy has no dialect registered for 'snowflake', which dblift's
  snowflake connection URL requires: no installed package provides that
  dialect. Install it with: pip install "dblift[snowflake]"`. The rewrite is
  deliberately narrow — it applies only when the plugin SQLAlchemy failed to
  load is exactly the one dblift's own URL named, so a `NoSuchModuleError`
  about any other plugin, and any dialect whose plugin declares no extra,
  still surfaces unchanged. The exception type and its `__cause__` are
  preserved, so code catching `NoSuchModuleError` or `ArgumentError` keeps
  working and the original traceback is still attached.

- **`dblift[all]` now installs every engine's driver.** It named seven extras
  out of eighteen, so `pip install dblift[all]` followed by a Snowflake or
  Redshift connection installed nothing for it. All eighteen engine extras are
  named, including the PostgreSQL-compatible aliases — they resolve to the
  same driver today, but that is a fact about the current dependency table
  rather than a property of the aliases, and Redshift and Snowflake already
  show the shape can diverge. A test derives the engine-extra set from
  `pyproject.toml`, so an extra that `all` forgets now fails the build.

- **New `dblift[cosmosdb]` extra**, installing `azure-cosmos` and
  `azure-identity`.

### Changed

- **The Azure Cosmos DB SDK is no longer installed by `pip install dblift`.**
  `azure-cosmos` and `azure-identity` were mandatory dependencies, so every
  install carried one engine's driver while the other seventeen stayed
  optional. They now live in the `cosmosdb` extra like every other driver.

  **If you use Cosmos DB, install `dblift[cosmosdb]` when upgrading** —
  otherwise the first Cosmos DB command fails. It fails with a message naming
  that exact command, not a bare import error. Everyone else gets a smaller
  install. `dblift[all]` includes it, and the published Docker image is
  unaffected because it installs `.[all]`.

## [3.1.0] - 2026-07-25

### Added

- **Four capability quirks that replace dialect-name branching in callers.**
  Each one existed as a hand-maintained set of dialect strings in the paid
  tiers; a set nobody updates when a dialect is added is a latent bug, so the
  capability moves next to the dialect that owns it.
  - **`row_limit_style`** (`"limit"` / `"top"` / `"fetch_first"`) with
    **`quirks.row_limit_clauses(n, server_info=None, ordered=False)`**, which
    returns a `RowLimitClauses` triple — `select_prefix`, `where_predicate`,
    `query_suffix` — plus a `compose_where(predicate)` method that ANDs the
    caller's own `WHERE` condition with `where_predicate`, so no call site
    re-derives the syntax or the join glue from a dialect name. SQL Server
    declares `"top"`, Oracle and DB2 `"fetch_first"`, everyone else the
    default `"limit"`. The third field exists because Oracle's pre-12.1
    fallback, `WHERE ROWNUM <= n`, is a `WHERE` predicate rather than a
    select-list prefix or trailing suffix: `row_limit_clauses` is
    version-aware, and a captured `server_info` not proven to be 12.1+ (or
    absent entirely) downgrades Oracle's declared `"fetch_first"` to
    `ROWNUM` at render time, since `FETCH FIRST n ROWS ONLY` is invalid SQL
    on an unproven-old server. `ROWNUM` is a validity fallback only, not a
    drop-in substitute — it is assigned before `ORDER BY` runs, so it cannot
    express an ordered top-N. Passing `ordered=True` tells the callee the
    caller's query also needs its `ORDER BY` honoured by the cap; when the
    resolved style is `"rownum"`, that raises `ValueError` instead of
    silently returning rows in the wrong order. Distinct from the existing
    `select_supports_limit`, which answers the coarser "may I append `LIMIT`
    at all" question for optional probes.
  - **`upsert_style`** (`"none"` / `"on_conflict"` / `"on_duplicate_key"`).
    PostgreSQL, SQLite and DuckDB declare `ON CONFLICT`; MySQL and MariaDB
    `ON DUPLICATE KEY UPDATE`. Oracle, DB2 and SQL Server express upsert as
    `MERGE`, which needs a different statement shape, so they keep `"none"` and
    take the portable UPDATE-then-INSERT fallback rather than claiming a syntax
    they cannot use. **Redshift overrides back to `"none"`** despite
    subclassing `PostgresqlQuirks`: it has no `ON CONFLICT` clause, and
    inheriting one would emit SQL the server rejects.
  - **`json_bind_cast_type`** (`"JSONB"` / `"JSON"` / `None`) — the SQL type a
    serialized JSON parameter must be CAST to when bound to a JSON column, or
    `None` where `text → json` coerces implicitly. Read through
    `quirks.json_bind_cast(server_info=None)`, which is version-aware on
    MySQL: the cast requires 5.7.8+, but since the declared cast is valid on
    every MySQL release except one long past EOL, an unresolved gate keeps
    today's behaviour rather than guessing, and only a server *proven* older
    downgrades to `None`. **Not uniform across the PostgreSQL and MySQL
    families** — **Redshift** (subclasses `PostgresqlQuirks`; has no `JSONB`
    type, only `SUPER`, and `CAST(? AS JSONB)` fails with *type "jsonb" does
    not exist*) and **MariaDB** (subclasses `MysqlQuirks`; does not
    implement `CAST(expr AS JSON)` per MDEV-26448) both override back to
    `None` rather than inheriting their parent's cast.
  - **`update_subquery_requires_derived_table`** (bool) — an `UPDATE` whose
    subquery reads the table being updated must have that subquery wrapped in a
    derived table. MySQL and MariaDB reject the direct form with error 1093;
    everyone else takes it, and the extra nesting would only cost a
    materialisation.

  Because the PostgreSQL-wire engines (Citus, TimescaleDB, YugabyteDB, AlloyDB,
  Aurora, Neon, Supabase) subclass `PostgresqlQuirks`, they inherit
  `"on_conflict"` and `"JSONB"` automatically — closing an omission the
  hand-maintained sets carried: those engines were absent from the JSON-cast
  set, so a captured JSON value bound without its cast and the restore failed
  with *"column is of type jsonb but expression is of type text"*.

  Purely additive for the core: nothing in `api/`, `cli/`, `config/`, `core/`
  or `db/` consumes the new capabilities yet, so behaviour is unchanged for a
  core-only consumer. `docs/semver-policy.md` §2 puts "add a new public symbol"
  at MINOR.

- **Tests for the `pseudo-sql-translator` lint rule** (27 cases). The rule
  shipped in 3.0.0 with no test of its own: every banned translator name and
  pseudo-DDL verb, the `# lint: allow-pseudo-sql` marker, the negative cases
  (a native Cosmos `SELECT`, a relational `DROP TABLE`), and — the one that
  matters — that the rule is actually wired into `_lint_file`, plus that
  `DEFAULT_ROOTS` resolves to directories that exist. A root that does not
  resolve makes the whole gate pass vacuously, because `Path.rglob` on a
  missing directory yields nothing rather than raising.

### Fixed

- **Stale `mypy` per-module overrides** in `pyproject.toml` naming
  `db.plugins.cosmosdb.sdk_translator.*` and `db.plugins.cosmosdb.parser.*` —
  eight modules 3.0.0 deleted. Harmless to type checking, but they described a
  subsystem that no longer exists.

## [3.0.0] - 2026-07-25

### Changed

- **BREAKING — CosmosDB migrations are Python only.** The CosmosDB pseudo-SQL
  layer and its Azure SDK translator were removed outright; there is no
  deprecation window, no compatibility flag, and no conversion tool. A `.sql`
  migration targeting CosmosDB now fails with `DBLIFT-NOSQL-001`
  (`core.exceptions.UnsupportedMigrationFormatError`) — the same verdict
  applies to `.sql` callbacks — and a write statement reaching the query
  executor raises `core.exceptions.NoSqlWriteNotSupportedError`; only native
  Cosmos `SELECT` still executes (available to migrations via
  `context.execute()`). Write CosmosDB migrations as `.py` files exposing
  `def migrate(context)` and drive the Azure SDK directly. Migration history
  rows for previously applied `.sql` migrations remain valid: checksums are
  untouched, and neither `repair` nor a re-baseline is required. See
  [`docs/user-guide/nosql-python-migrations.md`](docs/user-guide/nosql-python-migrations.md)
  for the statement-by-statement conversion table.
- **BREAKING — `MigrationContext` CosmosDB attributes renamed**:
  `context.database` → `context.db` (`azure.cosmos.DatabaseProxy`) and
  `context.client` → `context.raw_client` (`azure.cosmos.CosmosClient`). No
  aliases are kept; existing CosmosDB `.py` migrations using the old names
  raise `AttributeError`. The names are provider-neutral so a future document
  store fills the same slots.
- `diff` against a NoSQL dialect emits explanatory comments only. It no longer
  produces pseudo-SQL or an appended "Python SDK operations" script block.

> **Deprecation-policy deviation.** [`docs/semver-policy.md`](docs/semver-policy.md)
> §3 requires a public symbol to be deprecated in a MINOR release and kept
> working for at least one further minor before removal in a MAJOR. The
> CosmosDB pseudo-SQL surface and the `MigrationContext` attributes above were
> removed without that overlap, as a deliberate decision: the pseudo-SQL
> dialect had no specification, and shipping a compatibility path would have
> preserved the regex translator this release exists to delete. Recorded here
> in lieu of the deprecation window.

### Added

- **NoSQL foundation for document stores** (`db/plugins/nosql_base`):
  `DocumentHistoryManager`, `DocumentLockingManager` and `SamplingIntrospector`
  name what a document-store plugin must provide. CosmosDB implements them, so
  a second such plugin inherits a known surface instead of inventing one.
- **`supports_sql_migrations` quirks capability** (default `True`). Dialects
  that set it `False` reject `.sql` migrations with `DBLIFT-NOSQL-001` instead
  of handing them to a translator.
- **`provider.drop_object()`** — `clean` asks the provider to drop each
  enumerated object rather than executing `drop_sql` itself, so a backend whose
  objects are not SQL-droppable can use its SDK.
- A `pseudo-sql-translator` lint rule in `scripts/lint_patterns.py`, banning
  the SQL-shaped-front-end-over-an-SDK pattern for future NoSQL plugins.

### Fixed

- **`repair` could not clear a failed history row.** The delete moved behind
  `provider.delete_failed_migration_entry`, which initially required a
  `history_manager` component that only SQLite and CosmosDB own; every other
  plugin raised `NotImplementedError`. Relational plugins now get the
  parameterised `DELETE` by default, and a structural conformance test covers
  every concrete provider.
- **CosmosDB schema snapshots** are created through the SDK. They previously
  relied on the pseudo-SQL emulator turning `CREATE TABLE` into a container
  create.
- **CosmosDB history deletes addressed the wrong partition key** (the document
  `id` rather than `/version`), so Cosmos returned 404, the handler read it as
  "already deleted", and the row survived while `repair` reported nothing
  removed.

### Removed

- **CosmosDB pseudo-SQL statements**: `DROP CONTAINER`,
  `ALTER CONTAINER ... SET (...)`, `SET THROUGHPUT ON CONTAINER ... TO n`,
  `SET AUTOSCALE ON CONTAINER ... MAX n [MIN m]`,
  `SHOW THROUGHPUT ON CONTAINER`, `CREATE INDEX ... ON <container> (...)`,
  `DROP INDEX ... ON <container>`, `EXCLUDE INDEX PATH '<p>' ON CONTAINER`,
  `INCLUDE INDEX PATH '<p>' ON CONTAINER`, `SET TTL ON CONTAINER ... TO n|OFF`,
  plus plain SQL `CREATE TABLE` / `CREATE CONTAINER` / `INSERT` / `UPDATE` /
  `DELETE` against Cosmos. The SDK translator that executed them and the
  CosmosDB pseudo-SQL parser are gone with them.
- The SDK-script quirks hooks (`requires_sdk_for_drop`,
  `sdk_operation_hint_prefix`, `build_sdk_drop_operation`,
  `generate_sdk_script`) and the `SqlStatement.sdk_operation` /
  `SqlStatement.requires_sdk` fields.

## [2.11.0] - 2026-07-25

### Added

- **`dblift.client` entry-point seam** (`core.seams.client_factory`): the CLI
  now resolves the client class it constructs through the new entry-point
  group, so distribution add-ons can substitute a `DBLiftClient` subclass
  carrying their commands. Without a registration the OSS client is used —
  behavior is unchanged for OSS-only installs. A broken registration logs a
  warning and falls back to the OSS client.

### Fixed

- **The `_dblift_config_only_client` handler marker is honored again**: a
  single marked command receives a `ConfigOnlyClient` (no provider, no
  database connection) instead of a fully constructed client. The dispatch
  logic existed before the repository split and was lost in the export;
  add-on commands that declare themselves config-only (offline analysis)
  no longer trigger a database client construction.

## [2.10.0] - 2026-07-24

### Added

- **Multi-environment configuration.** One `dblift.yaml` can now describe every
  environment: root-level sections are the shared base, and each
  `environments.<name>` block deep-merges over them (mappings merge
  recursively; scalars and lists replace) — for any section, `database` and
  `migrations` included. Selection precedence: `--env <name>` (new top-level
  CLI flag on every command) > the `DBLIFT_ENV` environment variable
  (renameable via `resolve.env_var`) > `resolve.branch_map` fnmatch patterns
  matched against the branch name read from `resolve.branch_var` > none (root
  sections only — a file without `environments:` behaves exactly as before).
  The merge happens before environment variables, CLI flags, secrets
  resolution, and the paid raw-config passthrough, so the effective precedence
  is: defaults → root sections → active environment → env vars → CLI flags.
  Unknown environment names fail fast listing the configured ones.
- `DBLiftClient.from_config_file(..., environment="prod")` and
  `ConfigBuilder.build(..., environment=...)` — programmatic environment
  selection (MINOR API addition); the same selection chain applies when the
  keyword is omitted.
- `snapshot` added to the paid raw-config allowlist (preserved verbatim into
  `_paid_config_data`, per-environment mergeable like the other paid
  sections).

All additions are backward compatible (MINOR): configs without
`environments:` produce byte-identical effective configuration.

## [2.9.0] - 2026-07-23

### Added

- New feature gate `set_not_null_reuses_validated_check` on
  `PostgresqlQuirks` (`min_version="12.0+"`): whether `SET NOT NULL` can
  reuse a validated `CHECK (col IS NOT NULL)` constraint to skip the
  full-table re-scan. Inherited by the true-PostgreSQL compatible family
  (Aurora, AlloyDB, Neon, Supabase, TimescaleDB, Citus); Redshift and
  CockroachDB redeclare `feature_gates = {}` to opt out — CockroachDB
  versions its own engine (v23.x would wrongly read as ">= 12") and
  Redshift's banner reports PostgreSQL 8.0.x. `KNOWN_FEATURES` gains the
  new name (MINOR).

## [2.8.0] - 2026-07-23

### Added

- `zero_downtime` added to the paid raw-config allowlist
  (`_PAID_RAW_CONFIG_KEYS`): a `zero_downtime:` section in the YAML config
  is now preserved verbatim into `_paid_config_data` for the paid tier,
  instead of being dropped during parsing — mirroring the existing
  `data_sets` / `validation` passthrough.
- Version/edition-gated feature support. Plugins can declare `FeatureGate`
  entries (`db/feature_gate.py`) on their quirks classes via the new
  `BaseQuirks.feature_gates` ClassVar; the tri-state resolver
  `core.sql_model.feature_gates.supports_feature(dialect, feature,
  server_info)` answers True (server provably supports the feature), False
  (provably not), or None (unknown — callers keep their conservative
  fallback). First gates: `online_index_build` (SQL Server, Oracle —
  edition-gated) and `rename_column` (MySQL 8.0+, MariaDB 10.5.2+).
- `core.sql_model.server_info.ServerInfo` — typed parse of the captured
  `{"edition", "version"}` server-identity mapping, producing a comparable
  `DatabaseVersion` through the new overridable
  `BaseQuirks.parse_server_version` hook (Oracle overrides it to handle
  `"23ai"`-style banners without a `Release` clause).
- Shared version-string helpers `parse_version` and `version_matches_spec`
  in `core.introspection.version_detector`, extracted from
  `CanonicalTypeMapper` (which now delegates). Banner-tolerant: parses the
  first dotted numeric run of vendor strings such as
  `"PostgreSQL 16.2 on x86_64..."`.

All additions are backward compatible (MINOR): two new modules, two new
`BaseQuirks` members with inert defaults, no changed signatures.

## [2.7.0] - 2026-07-20

### Added

- New `EventType.SCRIPT_RISK_DETECTED` (`"script.risk.detected"`) event. It
  signals that a generated or pending SQL script contains a high-risk statement
  (lock/duration/data-loss) and is emitted by the paid impact-analysis layer.
  Additive and backward compatible — existing consumers of other event types
  are unaffected.
- New `SqlStatement.impact` field (`Optional[Any]`, defaults to `None`). This is
  a declared, supported extension point for per-statement annotations set by the
  paid impact-analysis layer; the core neither populates nor interprets it.
  Declaring it as a real dataclass field (rather than relying on attribute
  injection on the unslotted dataclass) makes it a stable boundary so a future
  `__slots__` cannot silently break downstream consumers. Positional
  construction of `SqlStatement` is unaffected — the field is appended last.

## [2.6.1] - 2026-07-17

### Added

- Paid commands (`diff`, `export-schema`, `validate-sql`, `data`, `snapshot`,
  `plan`, `preflight`) now appear in the OSS CLI as discoverable stubs. They
  are listed in `--help` with an edition label (e.g. `diff … [Pro]`) and, when
  invoked, print an upgrade message and exit with the dedicated code `4`
  (`EXIT_LICENSE_REQUIRED`). When the paid runtime is installed its real
  commands take precedence and no stub is created. Advertised commands are
  declared in `cli/premium_manifest.py`.

### Changed

- Collapsed the seven PostgreSQL-wire-compatible provider plugins (`neon`,
  `supabase`, `alloydb`, `aurora-postgresql`, `citus`, `timescaledb`,
  `yugabytedb`) onto a shared factory (`db/plugins/_pg_compatible.py`),
  removing 14 near-identical `provider.py`/`quirks.py` files that differed only
  by a name string. Each engine is now a single `make_pg_compatible_plugin(...)`
  declaration in its `plugin.py`. Plugin discovery now falls back to the
  provider/quirks classes declared on `plugin.py:PLUGIN` when a package ships no
  `provider.py`/`quirks.py`, so the entry-point and filesystem discovery paths
  behave identically. No behavior change: dialect identities, the single ANSI
  reference-dialect owner (PostgreSQL), and all connection/config reuse are
  preserved. Engines with real per-dialect logic (`cockroachdb`, `redshift`)
  are unchanged. The per-engine provider/quirks classes are now built by the
  factory and exposed as `db.plugins._pg_compatible.<Engine>Provider` /
  `<Engine>Quirks` (picklable); the previous direct-import paths
  (`from db.plugins.neon import NeonProvider`, etc.) are removed — use the
  engine's `PLUGIN` or the factory module instead.

### Fixed

### Removed

### Security

- Floored `setuptools` at `>=83.0.0` (build-system requirement, `dev` extra, and
  `requirements-dev.txt`) to clear PYSEC-2026-3447, which the `pip-audit`
  dependency gate flagged against the previously resolved `setuptools 79.0.1`.

## [2.6.0] - 2026-07-11

### Added

- Snowflake (`dblift[snowflake]`) first-party provider plugin with
  Snowflake-specific configuration, SQLAlchemy URL construction, native schema
  cleanup, migration history storage, and migration locking support.

### Changed

### Fixed

- Native driver diagnostics now treat missing dotted parent modules as an
  uninstalled driver instead of raising `ModuleNotFoundError`, so connection
  diagnosis still works when optional drivers such as `snowflake.connector` are
  not installed.
- Snowflake migration locking seeds its singleton lock row with `MERGE`, limits
  lock-timeout detection to lock-specific failures, and releases a held lock
  when the provider is closed.

### Removed

## [2.5.2] - 2026-07-10

### Added

### Changed

### Fixed

- Redshift schema cleanup now uses Redshift-safe `information_schema` queries
  instead of PostgreSQL-only catalogs, so clean migrations and integration
  setup do not fail on missing catalog relations such as `pg_extension`.

### Removed

## [2.5.1] - 2026-07-10

### Added

### Changed

### Fixed

- Redshift now uses the native `redshift+redshift_connector` SQLAlchemy
  dialect/driver and stores schema snapshot payloads in `VARCHAR(MAX)`, so
  fresh migrations and snapshot capture work on Redshift Serverless targets.

### Removed

## [2.5.0] - 2026-07-08

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
