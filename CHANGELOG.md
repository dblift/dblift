# Changelog

All notable changes to DBLift will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

- **`migrate()`'s result listed a Python migration's version twice.** The
  execution engine's non-SQL success path recorded the migration into the
  result, and the command layer recorded it again unconditionally — SQL
  migrations only hit the second, so only Python migrations doubled.
  Execution itself was always correct; this was a result-payload
  construction bug only. (#835)

- **`--version` could report a stale, unrelated version on an archive/frozen
  distribution.** The version resolvers went straight to
  `importlib.metadata`, which scans the *host's* installed package metadata
  rather than verifying it belongs to the code actually executing — so an
  extracted distribution running under a Python whose site-packages held an
  older `dblift` install reported that older version instead of its own. When
  a `DISTRIBUTION-MANIFEST.json` is present next to the running entry point —
  stamped at build time with the version of the bundled code, and immune to
  whatever happens to be installed on the host — `--version`'s headline now
  prefers it. A plain `pip install` never ships this file, so that path is
  unaffected. (#745)
- **Two racing first-time `migrate()` calls against a genuinely nonexistent
  PostgreSQL schema could leave one process with a poisoned connection.**
  `create_schema_if_not_exists` did a non-atomic check-then-create; both
  processes could pass the exists-check before either created the schema,
  and the loser hit an uncaught `UniqueViolation`. Same class of bug as the
  migration-lock-table create race (#815), now closed for schema creation
  too, across the whole PostgreSQL-compatible family. (#846)
- **Concurrent calls into one shared `DBLiftClient` (e.g. multiple threads
  calling `.info()`) could race on `SqlAlchemyProvider`'s single cached
  connection**, intermittently raising errors or leaking a "transaction
  already deassociated from connection" warning. The provider now
  serializes access to its connection/transaction state with an
  instance-level lock. (#819)
- **`baseline()` failed with "CosmosDB provider has no active connection" when
  it was the first operation called on a fresh client.** Unlike
  `info()`/`migrate()`/`undo()`, `baseline_command.py` never called the
  shared `_ensure_connected()` helper before touching the provider — most
  dialects lazily reconnect on demand, but CosmosDB doesn't, so it surfaced
  immediately. `baseline()` now establishes its connection up front, the
  same way `undo()` already does. (#821)
- **`undo()`, `clean()`, `baseline()`, and `repair()` never emitted their
  dedicated `EventType` members.** `UNDO_STARTED`/`UNDO_COMPLETED`/
  `UNDO_FAILED` and the equivalent `CLEAN_*`/`BASELINE_*`/`REPAIR_*` members
  have been part of the public `EventType` enum, but `DBLiftClient` emitted
  the generic `MIGRATION_STARTED`/`MIGRATION_COMPLETED`/`MIGRATION_FAILED`
  events (with an `operation` field) for all four commands instead. A
  listener subscribed to e.g. `EventType.CLEAN_STARTED` received nothing
  when `clean()` ran, even though the command completed successfully. Each
  command now emits its own dedicated started/completed/failed events,
  matching how `migrate()` already emits `MIGRATION_*`. (#823)
- **`clean()`, `baseline()`, and `repair()` emitted their `*_COMPLETED` event
  even when the underlying operation failed without raising** — e.g. `clean()`
  refusing to run because destructive clean is disabled by configuration, or
  `baseline()`/`repair()` hitting a safety check. Each command called its
  executor and emitted `*_COMPLETED` unconditionally, only reaching
  `*_FAILED` via a Python exception. Any listener (webhooks, OpenTelemetry
  spans, custom integrations) watching for `*_FAILED` to detect a failed
  clean/baseline/repair missed it. These three commands now check the
  result's success flag before emitting, the same way `undo()` already does.
  (#848)
- **A typo'd top-level config key (e.g. `migratoins_dir`) was silently
  ignored instead of surfacing an error.** Config loading is deliberately
  permissive — unrecognized keys are dropped rather than rejected — so a
  typo produced no error at all, just silently-wrong behavior from
  unintended defaults. `db validate-config` now warns when it finds
  unrecognized top-level keys. (#820)
- **`migrate --dry-run`, `migrate --validate-only`, and `validate` accepted
  `.sql` migrations against CosmosDB instead of rejecting them.** CosmosDB
  only supports Python migrations, and real `migrate` already enforced that
  via the `DBLIFT-NOSQL-001` guard — but that guard only ran on the
  execution path, so the three validation-only paths reported success on a
  migration that would fail the moment it actually ran. The check is now
  shared between both paths, so all four commands agree. (#816)
- **`DBLiftClient.from_config`/`from_config_file`/`from_sqlalchemy`, called on
  the documented base client class, never picked up a tier-provided
  subclass even when one was installed and registered.** The CLI already
  resolved the correct client class through the `dblift.client` seam before
  constructing it; the public factory methods always constructed the exact
  class they were called on instead of consulting the same seam, so a
  caller following the documented `DBLiftClient.from_config(...)` pattern
  silently got the base client's stubbed-out paid-tier methods regardless
  of what was installed. The factory methods now resolve through the seam
  when called on the base class itself; calling them on an already-specific
  subclass is unaffected. (#753)

- **A repeatable migration could fail or silently double-apply when two
  `migrate()` processes raced for the migration lock.** The losing process
  already re-checks and skips versioned migrations another process applied
  while it waited for the lock, but never re-checked repeatable (`R__`)
  migrations the same way — it unconditionally re-executed them. Against a
  non-idempotent repeatable script this produced a genuine failed migration
  even though the schema was already fully and correctly migrated by the
  winner; against an idempotent one it wrote a duplicate history row.
  `_filter_already_applied` now re-verifies pending repeatables against the
  post-lock history snapshot by script name and checksum, mirroring the
  existing versioned-migration re-check. (#811)

- **SQL Server: unqualified DDL (dblift's own documented `CREATE TABLE`
  style) silently landed in the connecting login's own default schema
  instead of `--db-schema`.** SQL Server's `set_current_schema` was an
  explicit no-op, and the provider never called it at all outside
  callbacks. It now aligns the connecting login's `DEFAULT_SCHEMA` via
  `ALTER USER ... WITH DEFAULT_SCHEMA`, the only mechanism SQL Server
  offers — unlike every other supported dialect, this is catalog-level
  state on the login rather than scoped to the connection, so it's visible
  to and overwritable by any other connection using the same login. The
  login's actual `DEFAULT_SCHEMA` is now read back and compared against
  what dblift last set on every call (not only when `--db-schema` itself
  changes), logging a warning the moment it disagrees; only the redundant
  `ALTER USER` write is skipped once the connection already holds the
  requested schema. This makes a shared login getting clobbered by a
  concurrent dblift run visible in the logs — it does not, and cannot,
  retroactively fix DDL that already ran against the wrong schema in that
  window. See the troubleshooting guide for the resulting recommendation:
  don't share one SQL Server login across concurrent dblift runs targeting
  different schemas. (#806)

### Removed

## [3.4.0] - 2026-08-02

### Added

- **`DBLiftClient` now exposes paid-tier stub methods for `diff`,
  `export_schema`, `snapshot`, `plan`, and `preflight`.** Previously these
  didn't exist on the OSS class at all, so calling them raised a bare
  `AttributeError` with no indication the feature exists in a paid edition.
  They now exist as callables (accepting arbitrary arguments) and raise
  `core.seams.capabilities.CapabilityDeniedError` with a message naming the
  command, its edition, and the upgrade URL — mirroring the upsell the CLI
  already shows for the equivalent commands (`cli/premium_manifest.py`).
  The shared catalog backing both surfaces now lives in
  `core/premium_manifest.py` (`cli/premium_manifest.py` re-exports it
  unchanged for backward compatibility). (#753)

### Changed

### Fixed

- **A handler can now opt a command out of project-config loading
  entirely.** Routing any command through the standard CLI pipeline forced
  a full project config (`dblift.yaml`/`--db-url`/`DBLIFT_DB_URL`) to load
  before the handler ever ran, even for a command that has nothing to do
  with a database — e.g. a paid-tier `license` command checking
  `~/.dblift/license.key`. The OSS-native `config`/`db` commands already
  skip this by hardcoded literal name in
  `cli/main.py::_parse_argv_and_load_config`, but OSS code may not name a
  paid-edition command anywhere outside `core/premium_manifest.py`, so
  that route wasn't available to a paid command. A registered handler
  marked `_dblift_zero_config_command = True` is now dispatched directly
  with a minimal context, bypassing config/db-url loading and the full
  logging-and-client-build pipeline — the same handler-attribute pattern
  already used for `_dblift_config_only_client`/
  `_dblift_skip_secret_resolution`. Guarded to single-command invocations
  only, so a chained command (e.g. `dblift license migrate`) falls through
  to the normal pipeline instead of silently running only the zero-config
  command and dropping the rest. (#746)
- **`dblift license` in a pure open-source install failed with argparse's
  generic "unrecognized arguments" instead of naming the command.** The
  premium-command catalog that lets the OSS CLI show a proper upsell for
  paid-only commands (`diff`, `export-schema`, `snapshot`, `plan`,
  `preflight`, ...) had no entry for `license`, so it fell through to
  argparse's default error instead of the same "this is an Enterprise
  command, here's how to upgrade" message every other paid command gets.
  `license` is CLI-only administrative surface — unlike the other entries,
  it has no corresponding `DBLiftClient` method. (#746)
- **SQL Server ``CREATE FULLTEXT INDEX``, ``DROP FULLTEXT INDEX``, and
  ``DROP FULLTEXT CATALOG`` failed with SQL Server's own error instead of
  running.** SQL Server refuses to run any of these statements inside a user
  transaction, the same restriction dblift already worked around for
  ``CREATE FULLTEXT CATALOG`` by routing it through autocommit. The other
  three full-text DDL forms carry the identical restriction but weren't
  recognized, so a migration containing one ran inside dblift's normal
  transaction and failed with SQL Server's own "cannot run inside a user
  transaction" error — or, if combined with a ``CREATE FULLTEXT CATALOG`` in
  the same migration, tripped dblift's guard against mixing autocommit and
  transactional statements in one file. All four full-text DDL forms are now
  classified identically and run through autocommit.
- **SQL Server ``clean`` now drops full-text catalogs.** ``clean
  --clean-enabled`` enumerated tables, views, sequences, types and synonyms
  but never queried ``sys.fulltext_catalogs``, so it reported success while
  leaving any full-text catalog in place. A subsequent migration that
  recreated a same-named catalog then failed with SQL Server error 7642
  ("catalog already exists"). Full-text catalogs are not schema-owned in SQL
  Server — unlike every other object type ``clean`` enumerates, there is no
  ``schema_id`` column to filter on directly — but a catalog is only ever
  populated by full-text indexes, and every full-text index belongs to a
  table, and every table belongs to a schema, so the catalog is scoped
  indirectly: only a catalog referenced by at least one full-text index on a
  table in the schema being cleaned is dropped, and only after the tables
  that may reference it (a table's full-text index disappears implicitly
  with the table; the catalog that held it is a separate object and needs
  its own explicit drop). Dropping a full-text catalog also cannot run
  inside a transaction — the same restriction the entry above now handles
  for the other full-text DDL forms.
- **Index introspection no longer logs a spurious error when a dialect's
  vendor queries decline per-table index retrieval.** A vendor queries class
  may signal "no per-table indexes query for this dialect" by returning a
  ``None`` query. ``IndexExtractor`` passed that ``None`` straight into query
  execution instead of checking for it first, which raised a ``TypeError``
  caught by the surrounding error handling and reported as a warning plus a
  tracked error — appearing as an ``[ERROR]`` log line on every affected
  table, even though the migration or snapshot itself succeeded. The
  ``None`` query is now treated as "no indexes to report" and skipped
  silently, matching how the same extractor already handles a declined bulk
  index query.
- **A failing ``beforeEach``/``beforeEachMigrate`` callback now reports its own
  error instead of an unrelated ``UnboundLocalError``.** The per-migration
  timing variable used to report execution time on failure was assigned
  *after* these callbacks ran, but read in the exception handler that a
  callback failure unwinds through. When a callback raised, the handler tried
  to read a variable that had never been set, so the surfaced error was
  ``cannot access local variable 'start_time'`` rather than the callback's
  actual failure. The real cause was still logged just above it, but the
  message in the FAILED banner pointed at a Python internals bug instead of
  the broken callback. The timing variable is now initialised before the
  callback dispatch, so a failing callback surfaces as the callback failure it
  is. As a side effect, the reported execution time for a successful migration
  now includes ``beforeEach``/``beforeEachMigrate`` callback dispatch time,
  where previously only the migration script itself was timed.

- **``undo`` no longer silently no-ops when it is the first call on a fresh
  client.** ``migrate`` and ``info`` both establish the database connection
  as an explicit first step before touching migration history; ``undo`` did
  not — it assumed a connection already existed and relied on history-table
  creation to establish one as a side effect. That assumption held for
  providers that reconnect lazily on demand, but not for CosmosDB, whose
  history-table creation talks to a lower-level connection manager without
  updating the provider's own connection state. On a brand-new client whose
  very first operation was ``undo()``, this meant every subsequent read of
  the migration history failed with a connection error — and that failure
  was swallowed by a broad exception handler (added to tolerate mocked
  dependencies in tests) that treated *any* history-read failure as "no
  applied migrations found," reporting ``No migrations to undo`` and
  ``success=True`` even though migrations were, in fact, applied. ``undo``
  now establishes its own connection up front, the same way ``migrate`` and
  ``info`` do, so it correctly finds and processes pending undos on a fresh
  client instead of reporting a false success.

- **A concurrent-migrate race on a brand-new schema no longer crashes with a
  raw driver traceback on DB2, Oracle, or SQL Server.** When two ``migrate``
  processes bootstrap the migration-history table for the first time at once,
  the loser used to get a graceful retry only on PostgreSQL and MySQL — the
  retry loop recognised the race by matching driver error text against a
  short, PostgreSQL-shaped list of English substrings (``"already exists"``,
  ``"duplicate key"``, ...). DB2 reports the same race as ``SQL0601N``
  (SQLSTATE 42710), Oracle as ``ORA-00955``, and SQL Server as
  ``"already an object named ..."`` (Msg 2714) — none of which matched, so
  the loser's raw exception propagated as an uncaught crash instead of a
  clean retry. Race detection is now a dialect hook
  (``is_schema_history_race_error``) so each engine classifies its own error
  by a stable vendor code where one exists, instead of by driver message
  text that can also be locale-translated.
- **``--version`` and the log banner no longer report a stale, unrelated
  ``dblift`` version.** Both resolvers called
  ``importlib.metadata.version("dblift")`` first, which scans ``sys.path``
  for *any* distribution metadata named ``dblift`` without checking that it
  belongs to the code actually executing. In a dev checkout or an extracted
  source tree, that lookup can resolve to a stale or otherwise unrelated
  ``dblift`` distribution recorded elsewhere on ``sys.path`` — for example an
  editable install whose metadata was captured at an earlier version and
  never refreshed after subsequent source edits — silently shadowing the
  version of the code that's actually running. Both resolvers now read the
  bundled ``__init__.py`` first when not running from a frozen build, since
  that file unambiguously is the code being executed; ``importlib.metadata``
  is used as the fallback there and remains first under a frozen build,
  where the filesystem layout is unreliable.
- **Migrations from a secondary ``--scripts`` directory now record the same
  bare filename in history as migrations from the primary directory.**
  ``load_migration_scripts`` computed a correct bare ``script_name`` for every
  migration by default, then overwrote it with the full source-directory path
  for anything found outside the primary directory — an absolute path on most
  setups. That value is what gets persisted into the schema history table's
  ``script`` column, so a migration from a secondary directory was recorded
  there as, say, ``/home/ci/project/extra-migrations/V2__add_col.sql`` instead
  of ``V2__add_col.sql``. Moving the checkout, running on a different machine,
  or even a ``/tmp`` vs ``/private/tmp`` path difference on macOS then made
  ``validate`` report the migration as renamed. The override is removed;
  ``script_name`` is now the bare filename regardless of which configured
  directory a migration came from.

  **Upgrade note:** history rows written *before* this fix (any project that
  used ``--scripts``/multi-directory support previously) still have the old,
  directory-qualified value stored in the ``script`` column. On upgrade, those
  rows are matched against their now-bare-named script on disk with a
  basename fallback, the same way an equivalent legacy-name mismatch is
  already handled for versioned migrations — so an already-applied migration
  from a secondary directory continues to resolve correctly: ``migrate`` does
  not re-execute it and ``validate --strict`` does not fail on it. Two
  repeatable migrations in different directories that happen to share a
  filename are now also caught as a naming conflict during validation, since
  removing the directory qualification means they'd otherwise be
  indistinguishable by name.
- **``repair`` now fixes a corrupted or non-numeric stored checksum instead of
  silently doing nothing.** A history row's checksum is normalized to an
  integer before any comparison; when the stored value can't be parsed (for
  example a manually edited row), normalization returns ``None``. The drift
  check in ``repair`` required both the stored and the filesystem checksum to
  be non-``None`` before flagging a mismatch, so a stored checksum that failed
  to parse was silently excluded from repair — the command reported no issues
  found while ``validate`` kept failing on that same migration, with no
  CLI-only way to recover. The check no longer requires the stored checksum to
  have parsed successfully: a row whose stored checksum is unreadable is now
  treated as drifted whenever a matching migration script exists on disk, and
  ``repair`` rewrites it like any other checksum mismatch.
- **``validate --strict`` now runs out-of-order detection on Python
  migrations.** Internally ``MigrationType.SQL`` names a migration's *role* —
  versioned, run-once — and not its file format; a versioned ``.py`` script is
  labelled ``MigrationType.PYTHON`` instead. Strict mode fails validation when
  a pending versioned script has a version lower than the highest applied
  version, but both halves of the check — the pending set and the applied set
  — compared against ``MigrationType.SQL`` directly. On a project whose
  versioned migrations are all ``.py`` the check found nothing to compare and
  returned a pass without examining anything. After upgrading,
  ``validate --strict`` **will start failing** on such a project if it has a
  genuine out-of-order migration and passed yesterday. That failure is correct
  and the ordering was already wrong — the gate simply was not running.
  Resolve it exactly as on a SQL project: renumber the out-of-order migration
  above the highest applied version, or drop ``--strict``.

  ``migrate --strict`` is unaffected: it was already rejecting out-of-order
  Python migrations through a separate, format-agnostic check in the migration
  state manager, and its behaviour and error message are unchanged.
- **Internal consistency:** baseline filtering in the validator now recognises
  versioned Python scripts. No observable behaviour change — the branch is
  unreachable from the current validation path, because the script loader never
  classifies a file as a baseline (baselines are command-generated history
  entries, not script files). Corrected so the code reads as intended, and so
  the branch is right if it is ever wired up.
- **``undo``, ``validate`` and ``repair`` now treat versioned Python
  migrations like versioned SQL ones.** Three checks tested the recorded
  migration type against ``SQL``, which is the type of a versioned *SQL*
  script — a versioned Python script is recorded as ``PYTHON``, so each check
  silently excluded it. ``migrate → undo → migrate → undo`` refused the second
  undo with *"Version N has already been undone"* and walked down to the
  previous version instead, because the re-apply was not counted; out-of-order
  detection could never flag a Python migration; and ``repair`` skipped a
  Python migration's checksum drift while still reporting success, leaving
  ``validate`` failing afterwards. All three now use the shared versioned-type
  predicate, so any versioned script format is handled identically. The
  "next version to undo" suggestion that accompanies a refused undo was dead
  code (it compared an enum member to a string) and never appeared; it is now
  live, ignores failed and already-undone versions, and orders versions
  semantically so it names the version ``undo`` would actually pick.

- **Two safety gates that had been silently skipping Python migrations now
  run. Behaviour changes on upgrade for any project with ``.py`` migrations —
  read this before upgrading.** Internally, ``MigrationType.SQL`` names a
  migration's *role* — versioned, run-once — and not its file format; a
  versioned ``.py`` script is labelled ``MigrationType.PYTHON`` instead. Two
  checks compared against ``MigrationType.SQL`` directly and therefore applied
  to ``.sql`` migrations only. Nothing needs to be configured or opted into:
  both gates take effect as soon as you upgrade.
  - **Baseline filtering now suppresses pre-baseline Python migrations.**
    Versioned scripts at or below the baseline version are dropped before
    validation, because a baseline declares them already applied. Python
    migrations were never dropped, so a pre-baseline ``.py`` migration stayed
    in scope and was re-executed against the very schema that had been
    baselined to say it had already run — re-running arbitrary migration code
    against live data. After upgrading, those migrations are correctly
    suppressed: ``info`` and ``validate`` list fewer migrations than before,
    and ``migrate`` stops re-running them. If a pre-baseline ``.py`` migration
    genuinely still needs to run, renumber it above the baseline version.
  - **Strict-mode out-of-order detection now runs on Python migrations.**
    Strict mode fails validation when a pending versioned script has a version
    lower than the highest applied version. Both halves of the check — the
    pending set and the applied set — were restricted to ``.sql``, so on a
    project whose versioned migrations are all ``.py`` the check found nothing
    to compare and returned a pass without examining anything. Because
    validation also runs as ``migrate``'s pre-flight, this gated ``migrate``
    and not only ``validate``. After upgrading, ``validate --strict``,
    ``migrate --strict`` and any command run with ``strict_mode`` enabled in
    configuration **will start failing** on Python projects that have a real
    out-of-order migration and that passed yesterday. That failure is correct
    and the migration order was already wrong — the gate simply was not
    running. Resolve it exactly as on a SQL project: renumber the
    out-of-order migration above the highest applied version, or drop
    ``--strict`` / ``strict_mode`` if applying migrations out of order is
    intended.
- **PostgreSQL extension functions installed in ``public`` are resolvable
  again.** dblift set a schema-only ``search_path``, so anything an extension
  installs into ``public`` — ``gen_random_uuid`` and ``digest`` (pgcrypto),
  ``ST_MakePoint`` (PostGIS), ``uuid_generate_v4`` (uuid-ossp), ``hstore``,
  ``create_hypertable`` and ``by_range`` (TimescaleDB) — was invisible to
  anything dblift executed. A migration calling one of them unqualified failed
  with ``function ... does not exist`` while the identical file replayed
  cleanly through ``psql``, whose default ``search_path`` ends in ``public``.
  A schema dblift had exported itself could therefore not be replayed through
  ``dblift migrate``. ``public`` is now appended to the search path — *after*
  the target schema, so an object in the target still shadows a same-named
  object in ``public``, and an unqualified ``CREATE`` still lands in the
  target. A ``public`` target schema is not listed twice, and a database whose
  ``public`` schema has been dropped is unaffected: PostgreSQL ignores search
  path entries that do not exist. dblift's own ``dblift_schema_history`` and
  ``dblift_migration_lock`` tables are always schema-qualified and were never
  resolved through the search path. Applies both to the connection URL and to
  the explicit ``SET search_path`` issued before callbacks, and so to every
  PostgreSQL-compatible engine — CockroachDB, Redshift, TimescaleDB, Citus,
  YugabyteDB, Neon, Supabase, Aurora PostgreSQL and AlloyDB.
- **One failing ``DROP`` no longer turns a PostgreSQL ``clean`` into a total
  no-op.** PostgreSQL aborts the *entire* transaction on any statement error,
  so the first object that could not be dropped — a permission-denied object,
  a dependency, an object type the enumeration misclassifies — left the
  connection unusable and every remaining ``DROP`` failed with
  ``InFailedSqlTransaction``. The command reported the failures but had
  dropped nothing at all, including its own ``dblift_schema_history`` and
  ``dblift_migration_lock`` tables, leaving a schema that could not be cleaned
  again without manual repair. Each drop now runs inside a savepoint that is
  unwound on failure, so the loop genuinely continues and only the objects
  that really could not be dropped are left behind. A partial clean is still
  reported as a failure. Dialects that keep the transaction alive after a
  statement error, or that commit DDL implicitly, are unchanged — no savepoint
  statement is sent to them.
- **Non-transactional DDL — ``CREATE INDEX CONCURRENTLY`` and similar
  statements PostgreSQL refuses to run inside a transaction block — now
  actually executes in autocommit, and no longer leaves the connection
  permanently autocommitting afterwards.** At SQLAlchemy's default isolation
  level the DBAPI connection has ``autocommit=False``: not opening dblift's
  own explicit transaction was not enough, because the driver still opened
  one of its own per statement, and PostgreSQL rejected the statement before
  dblift's trailing commit was ever reached. ``SqlAlchemyProvider`` now
  exposes ``execute_autocommit_statement()``, which switches the connection
  to ``isolation_level="AUTOCOMMIT"`` for the one statement and restores the
  previous state afterwards, so the rest of the migration keeps its normal
  all-or-nothing rollback. A second defect, found in review, meant the
  restore was incomplete: it put the DBAPI connection back, but the switch's
  own ``AUTOCOMMIT`` execution option stayed recorded on the connection, so
  the *next* flagged statement read that back as though the caller had
  configured it and reapplied ``AUTOCOMMIT`` permanently. Two
  ``CREATE INDEX CONCURRENTLY`` statements in one migration — the ordinary
  way to write an index migration — therefore disarmed rollback for every
  migration that followed in the same run: a later migration failing
  partway left its earlier statements applied while history recorded it
  ``FAILED``. The restore now captures and reapplies the connection's whole
  execution-option mapping instead of just the isolation level, so the
  recorded option is cleared rather than latched.
- **Placeholders in SQL callbacks are substituted before the SQL is parsed.**
  ``execute_callback`` handed the raw file content to the statement parser and
  substituted afterwards, per statement. Tokenisers that do not recognise ``$``
  drop it and pad the braces with whitespace, so a callback containing
  ``CREATE TABLE ${schema}.callback_log (...)`` reached the server as
  ``CREATE TABLE {schema }.callback_log (...)`` — rejected as an invalid table
  name, aborting the whole ``migrate`` run before any versioned migration ran.
  Oracle, SQL Server, MySQL and PostgreSQL were affected; SQLite, DuckDB and
  DB2 leave ``${...}`` intact and were not. Callbacks now substitute the full
  content first and pass the result to the parser, as versioned migrations
  already did. Substitution happens exactly once, so an unresolved ``${NAME}``
  still passes through as a literal and warns once.
- **Unrecognised characters in SQL are preserved instead of silently
  dropped — a missing ``%`` or ``@`` could change which statement actually
  ran while ``migrate`` reported success.** ``_handle_unknown_char`` consumed
  and discarded any character no tokenizer rule claimed, and the token
  stream is reserialized into the statement that gets executed, so the drop
  changed the SQL sent to the database. ``CREATE TABLE res AS SELECT id,
  a % b FROM t`` executed as ``SELECT id, a b FROM t``, which PostgreSQL
  reads as ``a AS b`` — a different column entirely; ``WHERE j @>
  '{"a":1}'`` executed as ``WHERE j > '{"a":1}'``, a different containment
  operator that matched the wrong rows. The unclaimed character is now
  emitted verbatim, so a gap in a dialect's rules produces odd tokenization
  or a database error rather than silently different SQL, and the base
  symbol set gained ``%``, ``&``, ``#``, ``?``, ``^`` and ``@`` so these
  tokenize correctly instead of merely surviving.
- **``clean`` no longer fails on a schema holding a TimescaleDB continuous
  aggregate.** A continuous aggregate's user-facing name is a plain
  ``relkind='v'`` row, so it is listed by ``pg_views`` and never by
  ``pg_matviews``. Clean enumeration therefore emitted ``DROP VIEW`` for it,
  which PostgreSQL rejects with *cannot drop continuous aggregate using DROP
  VIEW*. Because every drop shares one transaction, that single rejection
  aborted the transaction and every remaining object failed with
  ``InFailedSqlTransaction`` — leaving the whole schema, including
  ``dblift_schema_history`` and ``dblift_migration_lock``, undropped and
  needing manual cleanup. Continuous aggregates are now detected and dropped
  with ``DROP MATERIALIZED VIEW``. The lookup is gated on a ``pg_class``
  probe, so servers without TimescaleDB never touch the
  ``timescaledb_information`` catalog.
- **``repair`` fixes checksum drift on SQLite.** ``SQLiteProvider`` never
  defined ``repair_migration_history``, which every other provider implements
  and which ``repair`` calls to rewrite a drifted checksum. The resulting
  ``AttributeError`` was swallowed, so the command reported "No history entry
  updated … Repair may require manual intervention", left the stored checksum
  unchanged and exited failed. SQLite now updates the row like the other
  relational providers — ``COALESCE(?, success)`` preserves the stored success
  flag when no explicit value is given, and the real ``UPDATE`` rowcount
  reports whether a row matched. A conformance test now requires every
  provider to expose the method, since no base class declared it.
- **Per-call placeholders reach Python migrations.** ``migrate(placeholders=...)``
  and ``undo(placeholders=...)`` are applied to the placeholder service that the
  SQL path substitutes from, but the Python executor built
  ``MigrationContext.placeholders`` from the placeholders baked into the config
  at construction time. A ``.py`` migration therefore never saw a value passed
  per call — on any dialect — and silently ran with the default instead of
  failing. The executor now resolves the context mapping from the shared
  placeholder service at execution time, so Python and SQL migrations see the
  same effective set: ``dblift_*`` system placeholders, then configured
  placeholders, then per-call ones.
- **Callback events no longer collide on shared name prefixes.** Callback files
  were matched to an event with a bare ``startswith()``, and five event prefixes
  are substrings of others (``afterMigrate`` / ``afterMigrateError``,
  ``beforeEach`` / ``beforeEachMigrate``, ``afterEach`` / ``afterEachMigrate``,
  ``afterClean`` / ``afterCleanError``, ``afterUndo`` / ``afterUndoError``). So
  ``afterMigrateError__notify.sql`` executed on a fully successful ``migrate``
  — alerting or compensating SQL firing when nothing had failed — and
  ``beforeEachMigrate__mark.sql`` executed twice per script, once for each of
  the two events it matched. The ``__`` separator is now required immediately
  after the prefix, so ``afterMigrate__finalize.sql`` runs on ``afterMigrate``
  and nothing else does.

- **Callback names missing ``__`` are rejected instead of silently accepted.**
  The naming convention is ``<eventPrefix>__<description>.<ext>``, but any name
  merely *starting* with an event prefix was classified as a callback — so
  ``afterMigrate.sql``, and the single-underscore typo
  ``afterMigrate_notify.sql``, were loaded as callbacks. Such names are no
  longer callbacks anywhere (script discovery, ``parse_filename`` and
  ``Migration.type`` now agree), and are reported as a naming-convention
  violation once per run instead of sitting in the migrations directory looking
  like a working callback.

- **Tagged callbacks run again regardless of where the tag sits.** Script names
  are classified with their ``[tag1,tag2]`` group stripped, but callback event
  matching read the raw name, so a callback tagged anywhere before the ``__``
  separator — ``afterMigrate[prod]__notify.sql`` — was filed as a callback and
  then dispatched to no event. It never ran and drew no warning, since the name
  itself is valid. Tag stripping is now a single shared step used by both
  classification and event matching, so every tag position the one accepts the
  other resolves to the same event.

- **Internal consistency: the persisted ``MigrationType`` vocabulary is now
  pinned against silent drift.** The characterization-lock test for the type
  names dblift persists to history was parametrized from the
  ``MigrationType`` enum under test itself, so renaming or removing a member
  shrank or renamed the parametrization along with it and still passed — 35
  to 37 out of 37, either way. It now pins a literal roster, so a rename or
  removal shows up as a mismatch instead of a quietly smaller test.
  ``repair_command.py``'s ``[DELETE:{type}]`` description marker had a
  second, untested copy of the same vocabulary — hardcoded string literals
  in its script-name-inference fallback — and now derives from
  ``MigrationType`` itself, with a round-trip test covering the write and
  the read path together.

- **``import-flyway`` no longer causes ``migrate`` to silently re-execute
  already-applied migrations.** Flyway's own ``flyway_schema_history.type``
  vocabulary (``JDBC``, ``SPRING_JDBC``, ``SCRIPT``, ``UNDO_SCRIPT`` /
  ``UNDO_SQL``, ``DELETE``, ...) was written straight into
  ``dblift_schema_history``. None of those are ``MigrationType`` members, so
  ``AppliedMigration.from_history_row`` silently degraded every imported row
  to ``UNKNOWN`` on read; ``UNKNOWN`` is not a versioned type, so
  ``migrate`` stopped treating the row as already applied and re-ran it
  against a schema that already had it — live data loss, not a display
  quirk. Flyway's type is now mapped to the matching ``MigrationType``
  member before the row reaches ``record_migration``
  (``core/sql_validator/_flyway_compatibility.py``'s
  ``FLYWAY_TYPE_TO_MIGRATION_TYPE``): ``JDBC`` / ``SPRING_JDBC`` / ``SCRIPT``
  all describe a versioned migration executed by a non-``.sql`` resolver and
  map to ``SQL``; ``UNDO_SCRIPT`` (Flyway 9.0 renamed ``UNDO_SQL``, and every
  9.x-12.x install writes it) and ``DELETE`` map to their matching members;
  ``SQL`` / ``BASELINE`` / ``UNDO_SQL`` already round-trip unchanged. A type
  with no defined mapping now aborts the import with a clear error and a
  full rollback, instead of writing a value that would later silently read
  back as ``UNKNOWN``.

- **Schema export works again on every dialect.** An OSS-only dead-code
  sweep removed ``generate_schema_script`` from ``BaseSqlGenerator`` because
  no caller in this repository referenced it — but ``core/sql_generator`` is
  an extension point: dialect generators are supplied by external packages
  that subclass ``BaseSqlGenerator``, and reach this method through
  ``SqlGeneratorFactory.create()``. A repository-wide search therefore
  cannot tell whether a public method on that class is dead, because its
  callers live outside this repository. Removing it broke schema export on
  every dialect with ``'SQLiteSqlGenerator' object has no attribute
  'generate_schema_script'``. The method is restored byte-for-byte from
  before the removal. A new contract test now exercises every public method
  of the generator through the factory for each supported dialect and pins
  the method-name set, so a future cleanup sweep that can't see the
  external caller fails loudly instead of removing it again.

- **DuckDB parameterized DML reports real affected-row counts.** The 3.3.4
  ``RETURNING 1`` rewrite only ran when ``params is None``, so bound
  ``INSERT`` / ``UPDATE`` / ``DELETE`` (including data-correction undo restore
  and history mark-undone) still saw SQLAlchemy ``rowcount == -1`` and treated
  successful statements as zero rows affected. The rewrite now applies with or
  without parameters, binds via the same ``?`` → named-parameter path as the
  rest of the provider, and returns ``len(fetchall())``. Non-rewritable
  statements still fall through to the driver (which may report ``-1``).

- **DB2 compound bodies survive a missing trailing terminator.** A migration
  whose last statement is a trigger, a procedure or a bare ``BEGIN ATOMIC``
  block is valid DB2 without a closing ``;`` or ``@``, but the detection
  patterns that route such a script to the block-aware splitter all required
  ``END`` to be followed by a delimiter. The block extractors themselves count
  ``BEGIN``/``END`` depth and already handled a bare ``END``, so the detection
  was stricter than the code it guarded: an unterminated block fell through to
  plain semicolon splitting and was cut at the first semicolon inside its body,
  which DB2 rejected with ``SQL0104N ... unexpected token "END-OF-STATEMENT"``.
  The trigger and procedure detectors now accept an ``END`` that ends the
  script; they only decide which splitter runs, so the block boundary still
  comes from depth counting. Compound ``BEGIN ATOMIC`` blocks are now located
  by that same depth counting instead of by a pattern reaching for the closing
  ``END`` — a pattern cannot tell a block's own ``END`` from a nested one, so
  it truncated a compound at an inner ``END;`` or at a ``CASE ... END``, and
  could run past the block to a later ``END`` and swallow the statement after
  it. Scripts that end with ``;`` or ``@`` are unaffected.
- **DB2 ``CASE...END CASE`` and trigger ``IF...END IF`` bodies are no longer
  truncated mid-statement — a compiled procedure or trigger could silently
  ship missing its tail.** The block-boundary scanner only recognised a
  ``CASE`` expression's closing ``END`` when it was followed by ``;``, ``,``
  or ``)``; any other legal continuation (``INTO``, ``AS``, a bare
  ``FROM``, ...) was mistaken for the enclosing block's own ``END`` and cut
  a procedure short partway through a ``CASE``. Triggers had a second,
  independent bug: their extractor kept a private depth counter with no
  control-structure lookahead, so an ``IF...END IF`` inside a trigger body
  truncated the trigger early even though the identical body worked inside
  a procedure. Closing that surfaced four more gaps, each confirmed live
  against DB2 12.1.5.0: advancing past only the three letters of ``END``
  instead of the full matched keyword let a closed ``END CASE`` re-open as
  a fresh ``CASE`` and poison depth tracking for everything after it; the
  whitespace skip before a control keyword handled only space and tab, so
  ``END`` and ``CASE`` on separate lines reproduced the original
  truncation; ``END`` itself had no right-boundary check, so identifiers
  merely starting with the letters ``END`` (``ENDDATE``, ``END_IF``) were
  misread as the closing keyword; and the ``--`` / ``/* */`` comment
  detectors weren't guarded against already being inside an open block
  comment, so a decorative dash divider inside a header comment truncated
  the block — DB2 block comments nest, confirmed live. Triggers now share
  the same control-structure-aware scanner procedures already use, and
  every boundary check in the scanner routes through one identifier-
  character helper instead of five independent character enumerations that
  could drift out of sync.

- **Two more DB2 detection/extraction mismatches, found while auditing the
  fix above.** Each detector that decides "is this a block?" must agree with
  the extractor that then carves it out, or the script silently falls back to
  plain semicolon splitting and is cut at the first internal ``;``.

  - A trigger body may open with a plain ``BEGIN`` and not just ``BEGIN
    ATOMIC`` — confirmed live, DB2 compiles and fires such a trigger without
    complaint. The detector already accepted plain ``BEGIN``, but the
    extractor required the literal keyword ``ATOMIC`` and silently skipped
    any trigger that didn't have it, even with a trailing ``;`` present.
  - A comment following a block's closing ``END`` (when the script has no
    explicit ``;``/``@`` after it) defeated the procedure and trigger
    detectors, which anchored an undelimited ``END`` on end-of-input and
    treated a trailing comment as disqualifying rather than as trailing
    trivia to skip over. The extractors themselves were never affected —
    they already stop right at ``END`` and never absorb a trailing comment
    into the statement text.

- **DB2 ``CREATE PACKAGE`` (with or without ``BODY``) is no longer shredded
  into fragments at its first internal ``END``.** The remaining detector/
  extractor mismatch from the audit above: ``_has_package_blocks``'s pattern
  required exactly one token between ``PACKAGE`` and ``AS``, so ``CREATE
  PACKAGE BODY name AS`` — two tokens, ``BODY`` and the name — never matched
  and the whole block fell back to naive semicolon splitting. Separately, the
  extractor used a non-greedy match for the closing ``END``, so any package
  with more than one internal procedure or function stopped at the first
  nested ``END`` and silently dropped everything after it, including the
  package's real closing ``END``. The extractor now finds the package's true
  closing ``END`` via the same depth-tracking scan the trigger/procedure/
  compound-statement extractors already use, rather than a regex, and the
  detector accepts the optional ``BODY`` keyword, an optional repeated
  package name before the terminator, and the same trailing-comment/
  undelimited-end-of-input handling given to the procedure and trigger
  detectors above, for consistency.
- **MySQL history-table bootstrap no longer crashes on a concurrent race.**
  The migration lock table has always been created with
  ``CREATE TABLE IF NOT EXISTS``, but the history table used a bare
  ``CREATE TABLE``, so two processes bootstrapping the same schema at once
  raced: the loser's ``CREATE TABLE`` failed with a duplicate-table error
  that propagated uncaught, crashing that process outright. The history
  table now uses ``IF NOT EXISTS`` too, matching the lock table, so the
  statement itself is safe under a concurrent race rather than failing and
  needing a catch. MariaDB, which shares this provider, gets the same fix.
- **CosmosDB ``repair`` always failed with "no history document found",**
  even when the document genuinely existed. The lookup addressed the
  history container by ``partition_key=script_name``, but the container is
  actually partitioned on ``/version`` — every ``read_item`` call missed.
  ``repair`` now queries by ``script`` and updates the matching document
  directly, so a checksum drift or failed-migration entry can actually be
  repaired. (#134)
- **CosmosDB ``.sql`` migrations were executed instead of rejected.** The
  documented ``DBLIFT-NOSQL-001`` upfront guard only ran for non-SQL
  migrations and SQL callbacks; a plain ``.sql`` script fell through both
  checks and failed deep in SQL parsing with a confusing, unrelated error
  instead of the clear "this dialect doesn't execute SQL migrations"
  message. (#134)
- **Oracle ``clean`` left orphaned sequences behind indefinitely.** ``DROP
  TABLE`` never included ``PURGE``, so a dropped table (and any
  ``IDENTITY``-column sequence backing it) only moved into Oracle's
  recycle bin instead of being fully removed — invisible to every
  subsequent ``clean`` run. (#134)
- **Oracle ``clean`` still failed outright on schemas with triggers,
  after the ``PURGE`` fix above.** The real drop path a live ``clean``
  run takes (``list_droppable_objects`` + ``drop_object``, per-object) had
  no Oracle override and no awareness that ``DROP TABLE ... CASCADE
  CONSTRAINTS`` already takes a table's triggers with it — the follow-up
  explicit ``DROP TRIGGER`` then failed with ``ORA-04080`` ("trigger does
  not exist"). ``OracleProvider.drop_object`` now recognizes that specific
  error, by its real numeric Oracle error code rather than string-matching
  the exception text, and treats an already-gone trigger as the desired
  end state rather than a failure. (#135)
- **DB2 leaked raw Python tracebacks to stdout on any SQL error.** The
  ``ibm_db_sa`` driver logs (and thus prints, via Python's default
  stderr fallback) the full exception internally before re-raising it,
  so every DB2 statement failure showed ~25 lines of driver-internal
  traceback ahead of dblift's own formatted error panel. The driver's
  logger is now disabled on connection setup. (#134)
- **``db check-connection``/``diagnose-connection``/``list-drivers``
  never finalized their log file** under ``--log-format``/``--log-file``
  — these commands run before the CLI's normal log-dispatch path, which is
  what actually closes and flushes the log elsewhere, so a JSON log file
  was left empty and an HTML one never got its closing footer.
  ``check-connection`` now always closes its logger, on every exit path.
  (#134)
- **``info --tags``/``--exclude-tags`` never filtered repeatable
  migrations,** always showing every applied ``R__`` script regardless of
  its tags — even though ``migrate --tags`` filtered the same fixtures
  correctly. A stray ``version and`` guard skipped the whole filter check
  for any version-less migration. (#134)
- **``migrate`` silently reported "no pending migrations" (exit 0)
  instead of failing when a ``--scripts`` directory existed but was
  unreadable.** Both ``pathlib``'s directory-exists check and its glob
  scan succeed on a permission-denied directory without raising, so a lost
  read permission on a mounted migrations volume degraded to a false "all
  good" instead of failing the deployment. (#134)
- **``baseline --dry-run`` gave no visible indication it was a dry
  run,** unlike every other dry-run-aware command — the write was
  correctly skipped, but the console output was identical to a real run.
  (#134)
- **Flyway-imported repeatable migrations (``type=SQL``, no version) were
  categorized as "Versioned" instead of "Repeatable"** in ``info``, since
  ``import-flyway`` copied Flyway's ``type`` field verbatim without
  checking for its version-less-repeatable convention. (#134)
- **SQL Server connection failures could leak a raw pymssql error tuple**
  (e.g. a byte-string literal) instead of a clean message, when the
  failure didn't match any of the already-handled error shapes. (#134)
- **"Unsupported database type" errors gave no clue which value was
  unsupported** — an unrecognized URL scheme produced the bare, unhelpful
  ``Unsupported database type: ``. The message now names the offending
  value. (#134)
- **Top-level ``--db-url``/``--db-username``/``--db-password``/
  ``--db-schema`` flags worked but weren't documented** in ``migrate``/
  ``info``/``validate``/``undo --help`` — only ``db check-connection
  --help`` showed them. (#134)
- **A nonexistent schema produced a raw SQLAlchemy exception** — including
  the full generated ``CREATE TABLE`` SQL text and a documentation link —
  instead of a clean connection-style error message, because only the
  first of two connection-setup phases was wrapped in dblift's own error
  formatting. (#134)
- **``migrate`` skipped the boxed FAILED panel on a duplicate-version
  validation failure,** showing only a bare ``ERROR:`` line while every
  other failure path renders the usual panel — a presentation
  inconsistency, not a correctness bug. (#134)
- **``import-flyway`` logged a spurious "Unknown migration file
  extension" warning for Flyway ``BASELINE`` marker rows,** which have no
  real file extension by nature. (#134)

### Removed

## [3.3.4] - 2026-07-30

Patch release after release qualification of 3.3.3: DuckDB data-correction
rowcounts and log-banner version reporting.

### Fixed

- **DuckDB DML reports real affected-row counts.** SQLAlchemy/DuckDB often
  returned ``rowcount == -1`` for ``INSERT`` / ``UPDATE`` / ``DELETE``, so
  callers that assert ``expect=N`` (including data-correction apply) failed
  even when the statement changed the right number of rows. Parameter-free
  single statements now strip leading/trailing SQL comments (including
  inline trailing ``--``) and use ``RETURNING 1`` to count affected rows.
  Execution errors propagate instead of falling back to a second attempt
  that only surfaces a follow-on aborted-transaction error.

- **Log banners show the installed package version.** The Rich/JSON header
  preferred a filesystem walk to ``__init__.py``, which under PyInstaller
  (and some layout edge cases) could print a stale version (e.g. ``2.5.2``)
  while ``dblift --version`` was correct. Version resolution now prefers
  ``importlib.metadata.version("dblift")``, then the package attribute, and
  only falls back to reading ``__init__.py`` in non-frozen checkouts.

## [3.3.3] - 2026-07-30

CockroachDB connection fix: SQLAlchemy can parse CockroachDB
``version()`` banners so migrate and other commands connect successfully.

### Fixed

- **CockroachDB connections no longer fail on SQLAlchemy version parsing.**
  SQLAlchemy's stock PostgreSQL dialect requires a ``PostgreSQL X.Y`` banner
  from ``select version()``. CockroachDB returns banners such as
  ``CockroachDB CCL v24.3.18 (... go1.22.8 ...)`` (and newer v26.x forms),
  which raised ``AssertionError: Could not determine version from string`` on
  every ``create_engine`` connect. A thin ``cockroachdb+psycopg`` dialect
  reuses the psycopg PostgreSQL dialect and extracts the product ``vX.Y.Z``
  token (never the trailing Go version). The URL builder rewrites
  ``postgresql://`` / ``postgresql+psycopg://`` URLs onto that dialect,
  rejects non-PostgreSQL/Cockroach schemes, and only accepts the registered
  ``psycopg`` driver.

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
