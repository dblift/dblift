### Breaking

- **Everything now lives under the `dblift` package.** The wheel used to
  install six generic top-level packages (`api`, `cli`, `config`, `core`,
  `db`, `integrations`). Any project with its own `core/` or `api/` package
  ahead of site-packages on `sys.path` (a Django project run through
  `manage.py`, a pytest session with the project root as rootdir) shadowed
  DBLift's own modules and failed with `No module named 'core.logger'`. The
  wheel now installs exactly one top-level package, `dblift`, and every
  import path gains that prefix. The CLI, the config file, the history table
  and the migration file formats are unchanged. Upgrading:

  | Before | After |
  |---|---|
  | `from api import DBLiftClient, MigrationContext` | `from dblift.api import DBLiftClient, MigrationContext` |
  | `from config import load_config` | `from dblift.config import load_config` |
  | `from core.migration import Migration` | `from dblift.core.migration import Migration` |
  | `from integrations.flask import init_dblift` | `from dblift.integrations.flask import init_dblift` |
  | `INSTALLED_APPS = ["integrations.django"]` | `INSTALLED_APPS = ["dblift.integrations.django"]` |
  | `python -m cli.main` | `python -m dblift.cli.main` |

  The Django app label stays `dblift`, so `manage.py dblift_migrate`,
  `dblift_validate`, `dblift_info` and the `dblift.W001` check keep their
  names. Python migration files are loaded by path, so only their
  `MigrationContext` import changes. Third-party dialect plugins register
  through the same `dblift.providers` entry-point group as before.

### Added

- **README demo GIF** of a real `dblift migrate --dry-run --show-sql` run
  (`logo/dblift-migrate-dry-run.gif`), above the fold.
- **`pytest-dblift` 0.1.0 on PyPI.** Separate package (`pip install pytest-dblift`)
  with a `pytest11` plugin, fixtures (`dblift_migrated_db`, `dblift_empty_db`,
  `dblift_validate`, `dblift_undo`, session `dblift_client` / `dblift_engine` /
  `dblift_config`), and per-worker default SQLite files under xdist. It depends
  on bare `dblift`; non-SQLite engines still need `dblift[<extra>]` for the
  driver.

### Changed

- **PyPI / README one-liner.** Description is now
  “Flyway-style raw-SQL migrations for Python teams. No JVM, and you see the
  exact SQL before it runs.” PyPI keywords: `flyway`, `migrations`, `python`,
  `sql`, `postgresql`, `mysql`.

### Fixed

- **`migrate` crashed when `migrations.directories` held `DirectoryConfig`
  objects.** API construction keeps those objects so per-directory `recursive`
  flags survive; `Path()` rejected them. Directory entries are coerced to
  paths before use.
- **PostgreSQL identity export dropped `START WITH` / `INCREMENT BY`.**
  `PostgresqlQuirks.render_identity_clause` now emits
  `(START WITH n INCREMENT BY m)` when either seed or increment is set,
  matching Oracle. Bare `GENERATED … AS IDENTITY` is unchanged when
  neither is set.
- **PostgreSQL export emitted `CREATE SEQUENCE` for identity-owned sequences.**
  Sequences backing `GENERATED … AS IDENTITY` (``pg_depend.deptype = 'i'``)
  are excluded from introspection so replay no longer fails with
  `relation "…_seq" already exists`. Free-standing sequences still export.
- **`undo --target-version` stopped at the first installed version ≤ target.**
  Out-of-order history (V3 installed before V2, `--target-version 2`) left V3
  installed and still reported success. Undo now rolls back every installed
  version strictly above the target, regardless of install rank.
- **`ALTER TABLE … ADD CONSTRAINT CHECK` truncated nested parentheses.**
  Regex fallback (DB2 and sqlglot-fail paths) stopped at the first `)`, so
  re-emitted DDL was unbalanced. CHECK bodies are now parsed with balanced
  parentheses.
- **Migrate `beforeVersioned` / `afterVersioned` / `afterMigrateError` callbacks
  omitted per-directory recursive settings.** Those events now receive
  `dir_recursive_map` the same way sibling callbacks already did.
- **API clients dropped `DirectoryConfig.recursive`.** Constructing a client
  from config replaced per-directory `recursive: false` (and `true`) with the
  global default. The configured flag is preserved.
- **HTML command reports were never finalized.** `set_command_completed`
  checked `FileLog.format` instead of `log_format`, so the HTML close path
  never ran.
- **A failed versioned history row after undo is no longer treated as a
  reapply.** Undo/reapply "latest successful rank wins" now lives in one
  helper; the data-service copy previously counted unsuccessful later rows.
- **Oracle, DB2, and SQL Server `repair_migration_history(success_value=None)`
  flipped SUCCESS to failed.** Those dialects now keep the stored flag via
  `COALESCE`, matching PostgreSQL, MySQL, and SQLite. Callers that pass
  `success_value=True` are unchanged.
- **DB2, MySQL, and SQL Server qualified identifiers did not match
  `schema.table`.** An `rf` string used `\\.` (backslash + any character)
  instead of a literal dot; the patterns now match PostgreSQL/SQLite.

### Removed