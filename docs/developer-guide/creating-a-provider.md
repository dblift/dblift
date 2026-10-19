# Creating a Third-Party Provider

DBLift's database support is entirely plugin-based. First-party providers live under `db/plugins/` inside the `dblift` package. Third-party providers (e.g. `dblift-snowflake`, `dblift-cockroach`, internal corporate dialects) are distributed as separate pip-installable packages and register themselves the same way.

Adding a provider never requires changes to `core/`, `api/`, `cli/`, or `config/`.

## Prerequisites

- A working knowledge of the dialect's SQLAlchemy dialect/driver (or native SDK for non-SQLAlchemy transports).
- The `DialectQuirks` contract (see `db/base_quirks.py`).
- ADR-0026: plugin isolation.

## Step 1: Use the cookiecutter

```bash
pip install cookiecutter
cookiecutter /path/to/your/dblift/checkout/templates/dblift-provider-cookiecutter
# Answer the prompts (project name, dialect identifier, etc.)
```

This produces a minimal but installable package skeleton:

```
dblift-myprovider/
├── pyproject.toml
├── README.md
└── db/
    └── plugins/
        └── myprovider/
            ├── __init__.py
            ├── plugin.py
            ├── provider.py
            ├── quirks.py
            └── sqlalchemy_url.py
```

The layout deliberately mirrors `db/plugins/postgresql/` (and siblings) so the same mental model applies.

## Step 2: Fill in the pieces

1. **pyproject.toml** — the critical bit is already present:

   ```toml
   [project.entry-points."dblift.providers"]
   myprovider = "dblift.db.plugins.myprovider.plugin:PLUGIN"
   ```

   Use the explicit `packages = ["dblift.db.plugins.myprovider"]` (already in the template) so your distribution only contributes the leaf plugin directory. This avoids clobbering `dblift`'s `db/__init__.py`.

2. **plugin.py** — the registration point. It must export a module-level `PLUGIN` that is an instance of `PluginInfo`. The structure is identical to first-party:

   ```python
   from dblift.extensions.providers import PluginInfo
   from dblift.db.plugins.myprovider.provider import MyproviderProvider
   from dblift.db.plugins.myprovider.quirks import MyproviderQuirks
   from dblift.db.plugins.myprovider.sqlalchemy_url import build_sqlalchemy_url

   PLUGIN: PluginInfo = PluginInfo(
       name="myprovider",
       version="0.1.0",
       description="MyProvider database provider",
       dialects=["myprovider", "myprov"],  # include all aliases you want to accept
       provider_class=MyproviderProvider,
       transport="native",
       quirks_class=MyproviderQuirks,
       sqlalchemy_url_builder=build_sqlalchemy_url,
       # config_class=...   # supply your own if you need custom config fields
       # native_driver_module="mydriver",
   )
   ```

3. **sqlalchemy_url.py** — **owned by the plugin** (ADR-0026).

   ```python
   def build_sqlalchemy_url(database_config: Any) -> str:
       ...
   ```

   The callable receives the fully-populated database config object for your dialect and must return a SQLAlchemy URL string suitable for `create_engine`. There are no central maps or if/elif ladders in `config/` or `core/`.

4. **provider.py**, **quirks.py** — implement behaviour and any required hooks. Start with the generated stubs.

   **Transport vs base class (clarification).** `transport` on `PluginInfo` stays `"native"` for every first-party plugin — it does *not* select "SQLAlchemy mode". Whether you get SQLAlchemy plumbing is decided by which base class your provider subclasses:
   - Subclass **`SqlAlchemyProvider`** (`db/sqlalchemy_provider.py`) to get connection/execute/transaction handling from a SQLAlchemy engine (this is what PostgreSQL, MySQL, Oracle, SQL Server, DB2 do). You still implement the history table, lock table, schema ops, and `clean` — even PostgreSQL overrides ~15 methods. "Just subclass `SqlAlchemyProvider`" gets you a *connection*, not a finished provider.
   - Subclass **`NativeProvider`** to drive a raw DB-API driver yourself (SQLite, CosmosDB). More code; full control.

   Only `create_migration_history_table_if_not_exists` is a hard `@abstractmethod`; everything else has a safe default or is exercised at runtime, so lean on an existing plugin (PostgreSQL for a SQLAlchemy example) as your template rather than the base classes alone. See `db/base_quirks.py` for the full hook recipe (generators, parsers, the five manager components, etc.).

   **File-based dialects need a config field.** The generated config stub only carries the base fields (`url`/`host`/`port`/`database`/`schema`). An embedded, file-path dialect (SQLite, DuckDB) must add its own `path` field and a `__post_init__` that resolves `path` from `url`/`database` and defaults the schema — copy SQLite's `config.py`.

   **Provide a regex parser.** `quirks.parser_class("regex")` must return a parser class. Returning `None` makes the hybrid splitter log `"<dialect>-specific statement splitter failed: Unsupported dialect"` and fall back — and that fallback *raises* under `strict_tokenizer=True`. Ship a `parser/parser_config.py` (`DialectConfig` subclass) + a small `EnhancedRegexParser` subclass. For a non-procedural dialect the splitter only needs to respect string literals and comments around `;`.

5. Add a driver extra if desired:

   ```toml
   [project.optional-dependencies]
   myprovider = ["mydriver>=x.y"]
   ```

## Statement splitting contract

`StatementSplitter(dialect).split(script)` returns `Statement` records
(`dblift.core.sql_parser.statement`). A parser that implements `split(script)` returns them itself:

| Field | Meaning |
| --- | --- |
| `text` | the statement verbatim, without its terminator |
| `line` | the line where it starts |
| `terminator` | what ended it (`";"`), or `None` when the script ended it |
| `kind` | `"sql"`, `"copy_stdin"` (a COPY header with its data) or `"directive"` (a client directive dropped and recorded). Execution runs `sql` and `copy_stdin` records only; a record of any other kind is not a statement. A `directive` is sent only when it has `execution_text` |
| `multi` | reserved for psql's `\;` |
| `repeat` | how often execution sends it: 1 by default, or the count of the `GO n` that ended a T-SQL batch (0 sends it never) |
| `execution_text` | the string to send when it is not `text`. `None` sends `text` for `sql` and `copy_stdin`, and nothing for a `directive` |
| `analysis_statements` | the statements analysis reads from this record; `None` means the record is one analysis statement, `()` contributes none |
| `source_start`, `source_end` | half-open offsets of the record in the original script, including a consumed client terminator such as `GO`; optional |

A record is a statement: do not return empty pieces, comment-only pieces or batch separators.
`split_statements` is the list of strings execution sends, derived from the records.

A parser that implements only `split_statements` (strings) still works. dblift adapts its strings
to records, skipping any piece that is empty after Python's `str.strip()` (a no-break space
is whitespace there, so such a piece is lost), comment-only pieces and any piece the dialect's
`is_batch_separator` accepts, and logs once per dialect and process a message asking the
parser to implement `split()` and return `Statement` records. The adaptation, and so the
skipping, ends in the next major release; return only statements from `split_statements`
before then, or implement `split()`, whose records keep a piece of that kind.

## Step 3: Install & discover

```bash
cd dblift-myprovider
pip install -e .
python -c '
from dblift.extensions.providers import ProviderRegistry
ProviderRegistry.discover_plugins()
plugin = ProviderRegistry.get_plugin_info("myprovider")
assert plugin is not None
print(plugin)
'
```

`DBLiftClient`, the CLI, `from_config`, etc. will now accept `type: myprovider` (and your aliases) exactly as they accept `postgresql`.

## ADR-0026 constraints (must follow)

- **Plugin owns its URL builder.** `sqlalchemy_url_builder` on `PluginInfo` is the only place the mapping from config object → SQLAlchemy URL lives for your dialect. Do not add branches in `config/database_config.py`, `config/_url_builder_mixin.py`, or anywhere in `core/`.
- No edits outside your package. The isolation guarantee is verified by `tests/unit/test_plugin_isolation.py` and the `scripts/lint_patterns.py` "dialect-string-literal" rule.
- Quirks (via `provider.quirks`) are the single source of truth for dialect-specific rendering, parsing, and comparison behaviour.
- Third-party plugins are first-class: `ProviderRegistry` makes no distinction between in-tree and entry-point plugins after discovery.

## Discovery mechanics

- `ProviderRegistry.discover_plugins()` (called early by config loading and client factories) does two passes:
  1. Entry points (`importlib.metadata.entry_points(group="dblift.providers")`).
  2. Filesystem fallback under `db/plugins/` (only for in-tree development).
- Once registered, `ProviderRegistry.get_provider_by_name`, `create_provider`, `build_sqlalchemy_url`, `get_quirks` etc. work for your dialect.
- The same mechanism is used by `dblift.commands`, `dblift.command_handlers`, `dblift.features`, and `dblift.terminal_commands` for other extension points.

## Next steps / testing

- Add real tests under your package (or in a tests/ tree) exercising your URL builder, quirks hooks, and a minimal migration round-trip (SQLite-style or against a Docker service).
- **Test-package `__init__.py` (importlib-mode trap).** The suite runs with `--import-mode=importlib`. If your plugin's directory name equals a top-level importable module (e.g. `duckdb`, whose driver is also imported as `duckdb`), a missing `__init__.py` on an *ancestor* of your test dir makes pytest treat your test package as top-level and insert its parent onto `sys.path` — so `import <name>` resolves to your test package instead of the driver, and collection dies with a confusing `AttributeError`. Ensure every level down to your test dir has an `__init__.py` (this is why `tests/unit/db/plugins/__init__.py` exists). Dialects whose name differs from their driver module (postgresql→psycopg) never hit this.
- **The ADR-0026 "zero core edits" promise is real** — verified end-to-end when DuckDB was added (2026-07-04): a working provider (discovery + migrate + history + clean, capabilities auto-derived from quirks) touched only `db/plugins/duckdb/`, one `pyproject.toml` entry-point line, one driver extra, and the test tree. No edits to `core/`, `api/`, `cli/`, or `config/`. If you find yourself needing one, treat it as a framework gap to fix, not a step to follow.
- When you are ready for first-party inclusion, the same files can be moved into the main tree under `db/plugins/<name>/` + one line added to the main `pyproject.toml` (the cookiecutter deliberately produces the identical shape).
- See also:
  - [Plugin entry points](plugin-entry-points.md)
  - `dblift.extensions.providers` (the stable `PluginInfo` and registry import path)
  - Existing first-party plugins (especially `postgresql` for a full native SQLAlchemy example and `sqlite` for the simplest URL builder).

If your provider only needs the stock ANSI behaviour, the generated stubs + a correct `build_sqlalchemy_url` may be sufficient to get `migrate` / `info` / Python migrations working immediately.
