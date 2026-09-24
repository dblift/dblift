# Forking DBLift as the base of your own tool

This page is for a team that wants to ship a migration tool of their own
built on this code base: rename it, keep the engines you need, and drop the
hooks that exist for optional add-on packages. Everything below refers to
files in this repository; `tests/unit/docs/test_forking_guide.py` fails if
one of them moves, so the lists stay current.

## 1. The package map

| Package | What it holds | Depends on |
| --- | --- | --- |
| `dblift/config/` | Configuration model, YAML/env/CLI merging, the property registry that derives `--flags` and `DBLIFT_*` variables. | `core.constants`, `core.utils`; `db.provider_registry` lazily, for dialect lookup |
| `dblift/core/` | The engine: migration commands and executors, history and locking, the SQL model, parsers, generators, introspection, validators, logging. Dialect-neutral; it asks the provider's `quirks` for anything dialect-specific. | `config`, `db` |
| `dblift/db/` | Provider contract and registry, plus one plugin per engine under `db/plugins/<engine>/` (provider, quirks, parser, introspection, history and lock managers). | `config`, `core` (constants, sql_model, sql_parser, logger, sql_generator, utils, migration, among others) |
| `dblift/api/` | `DBLiftClient` and the async client: the programmatic surface, events and callbacks. | `core`, `config`, `db` |
| `dblift/cli/` | argparse setup, command dispatch, the MCP server. The only package that may import everything else. | all of the above except `db` (see the layer rules below) |
| `dblift/extensions/` | Stable import paths for third-party plugin code (`logging`, `providers`, `sql_generation`, `sql_model`). Re-exports only. | `core`, `db` |
| `dblift/integrations/` | Thin helpers for Django, Flask, FastAPI and OpenTelemetry. | `api`, `core.exceptions` |

`core` and `db` import each other; for a fork they are one unit.

Two layer rules are enforced by `.importlinter` (run through
`scripts/check_code_quality.sh`):

- `dblift.cli` must not import `dblift.db` directly; it reaches the database
  through `api` and `core`.
- Nothing under `api`, `config`, `core` or `db` may import `dblift.cli`.

`dblift/core/constants.py` imports nothing and is imported everywhere: it is
the place for values that several packages share.

## 2. Renaming the product

Start with the "Product identity" block at the top of
`dblift/core/constants.py`. It defines the strings a database or an
environment sees:

| Constant | Used for |
| --- | --- |
| `DEFAULT_HISTORY_TABLE` | The schema-history table every engine creates (`--table`). |
| `MIGRATION_LOCK_TABLE` | The lock table and the advisory-lock names derived from it. |
| `ENV_PREFIX` | Every environment variable the tool reads (`<PREFIX>DB_URL`, ...). |
| `DBLIFT_SCHEMA_SNAPSHOTS_TABLE`, `DBLIFT_DATA_CHANGE_SET_TABLE`, `DBLIFT_DATA_AUDIT_TABLE` | The other tables the tool owns. |

`tests/unit/core/test_product_constants.py` scans the package for copies of
these literals and fails if one reappears; after changing the values, update
the expected strings in that test.

Then the identifiers that are not constants, because each is a public
contract of its own:

- **The package name.** `dblift/` is the import root; `pyproject.toml`
  declares the distribution name, the `dblift` console script and the
  `dblift.*` entry-point groups. Renaming the directory means rewriting every
  `from dblift.` import (a `sed` over `dblift/`, `tests/`, `packages/` and
  `docs/`) and the entry-point values.
- **Migration placeholders.** `dblift/core/migration/executor/placeholder_manager.py`
  substitutes `${dblift_schema}`, `${dblift_database}`, `${dblift_timestamp}`,
  `${dblift_date}`, `${dblift_time}` and `${dblift_username}` into users' SQL
  files. Renaming them changes what users write in their migrations.
- **Framework command names.** Django management commands live under
  `dblift/integrations/django/management/commands/` and are named after the
  files; the Flask CLI command is registered in `dblift/integrations/flask.py`;
  the Django settings the integration reads (`DBLIFT_DATABASE_URL`,
  `DBLIFT_MIGRATIONS_DIR`, `DBLIFT_DATABASE_ALIAS`) are literal in
  `dblift/integrations/django/_client.py` on purpose.
- **Entry-point group names.** The `dblift.*` group names are string
  literals in code as well as in `pyproject.toml`: `dblift/db/provider_registry.py`
  (`dblift.providers`), `dblift/cli/extensions.py`, `dblift/cli/mcp/registry.py`,
  `dblift/config/secrets/_registry.py` and the modules under `dblift/core/seams/`.
  Rename both sides together; no test ties them, and a mismatch shows up
  later as an unknown dialect.
- **Oracle's lock handle.** `dblift/db/plugins/oracle/provider.py` builds
  `DBLIFT_MIG_LOCK_<schema>` with a fixed prefix because Oracle caps the name
  at 30 characters; it cannot be derived from `MIGRATION_LOCK_TABLE`.
- **Tracing.** `dblift/integrations/opentelemetry.py` names its tracer after
  the distribution.
- **Docstrings and docs** mention the old names in prose; they do not affect
  behaviour.

After a rename, regenerate the public-surface snapshots once and commit them
with the change:

```bash
DBLIFT_UPDATE_CONTRACTS=1 python -m pytest tests/unit/contracts
```

## 3. Removing the extension hooks

The open-source tree ships seams that an installed add-on package can
register into. A fork that will never install such a package can delete
them. `dblift/core/seams/__init__.py` lists every seam, its entry-point
group and the core call sites; this section is the removal recipe.

Delete these files and directories:

- `dblift/core/seams/`
- `dblift/core/premium_manifest.py` and `dblift/cli/premium_manifest.py`
  (the catalogue behind the command stubs the CLI and API create when no
  add-on registered a command)
- `dblift/cli/extensions.py` (command, handler and terminal-command
  entry-point loaders)
- `dblift/cli/mcp/registry.py` (MCP tool registrars)
- `tests/unit/core/seams/` and `tests/unit/cli/test_premium_stubs.py`

Remove from `pyproject.toml` every `[project.entry-points."dblift.<group>"]`
table except `dblift.providers`, which is how the engines themselves load.

Then edit the call sites. Find them with:

```bash
grep -rn 'core\.seams\|premium_manifest\|cli\.extensions\|mcp\.registry\|license_tier\|license_info' dblift --include='*.py'
```

At the time of writing that is:

| File | What to change |
| --- | --- |
| `dblift/cli/main.py` | Drop the `load_feature_extensions()` call at startup, the `get_license_info(args)` value on the command context, `_propagate_license_banner`, the `PREMIUM_STUB_COMMANDS` branch, and use `DBLiftClient` where `resolve_client_class()` is called; `load_terminal_commands()` becomes an empty dict. |
| `dblift/cli/_command_handlers.py` | Drop the `load_command_handlers()` / `load_terminal_commands()` merges, the `PREMIUM_STUB_COMMANDS` loop, `license_tier=resolve_tier(args)` (pass `None`) and the `except CapabilityDeniedError` branch. |
| `dblift/cli/_parser_setup.py` | Drop `_register_premium_stub_parsers` and the `load_command_extensions(parser)` call. |
| `dblift/cli/mcp/runner.py` | Drop `license_tier=resolve_tier(...)` (pass `None`) and the `except CapabilityDeniedError` branch. |
| `dblift/cli/mcp/server.py` | Drop `load_feature_extensions()` and the `load_mcp_tool_registrars()` loop. |
| `dblift/api/client.py` | Drop `load_feature_extensions()` and `attach_registered_listeners(...)` in `__init__`, the `_PREMIUM_COMMANDS_BY_API_METHOD` stub methods, and make `_resolve_factory_client_cls` return `cls`; then remove the now-unused imports of `premium_manifest` and `CapabilityDeniedError`. |
| `dblift/core/migration/executor/execution_engine.py`, `dblift/core/migration/commands/migrate_command.py` | Drop the `run_checks(...)` call and its import. |
| `dblift/core/sql_generator/generator_factory.py`, `dblift/core/sql_generator/alter/alter_generator_factory.py` | Drop `load_feature_extensions()` / `attach_registered_sql_generators()`. |
| `dblift/core/introspection/introspector_factory.py`, `dblift/core/introspection/vendor_queries_factory.py` | Drop `attach_registered_introspection()`. |
| `dblift/core/logger/_formatters.py` | The `license_info` attribute and the banner block are inert without a provider; delete them or leave them. |
| `dblift/cli/handlers/_shared.py` | `CliCommandContext.license_tier` can stay as an unused field or go. |
| `dblift/cli/_constants.py` | A comment mentions `cli/premium_manifest.py`; reword or leave. |

Run `python -m pytest tests/unit -q` afterwards and delete or fix the tests
that named removed symbols (`grep -rln 'seams\|premium\|license_tier' tests`).
`tests/unit/test_oss_public_surface.py` and `tests/smoke/test_oss_standalone.py`
assert properties of the open-source packaging and can go with the hooks.

The CLI contract snapshot under `tests/unit/contracts/snapshots/` records
the stub commands, so `tests/unit/contracts/test_cli_contract.py` fails
once they are gone; regenerate it with the command in section 2.

## 4. Keeping only some engines

Each engine is self-contained under `dblift/db/plugins/<engine>/` and
registered in `pyproject.toml` under `dblift.providers` with a matching
extra. To drop an engine, delete its directory, its entry-point line, its
extra (and its line in the `all` extra), and its tests: a directory
`tests/unit/db/plugins/<engine>/` where one exists, otherwise the engine's
entries in the parametrised tables of
`tests/unit/db/plugins/test_pg_compatible_plugins.py` and
`tests/unit/db/plugins/test_pg_compatible_locking.py`, plus anything under
`tests/integration/`. Then `grep -rln '<engine>' tests/` and prune what
remains: several registration and capability tables name every shipped
engine. The PostgreSQL-compatible dialect names also appear in
`_POSTGRESQL_FAMILY` in `dblift/db/plugins/postgresql/config.py`.

Seven PostgreSQL-compatible plugins (`neon`,
`supabase`, `aurora_postgresql`, `alloydb`, `yugabytedb`, `timescaledb`,
`citus`) are built by `make_pg_compatible_plugin` in
`dblift/db/plugins/_pg_compatible.py` and are two files each; `cockroachdb`
subclasses the PostgreSQL provider with its own locking and dialect
registration. See
[Creating a provider](creating-a-provider.md) for the plugin contract and
[Plugin entry points](plugin-entry-points.md) for the packaging.
