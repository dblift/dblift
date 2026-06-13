# Creating a Third-Party Provider

DBLift's database support is entirely plugin-based. First-party providers live under `db/plugins/` inside the `dblift` package. Third-party providers (e.g. `dblift-snowflake`, `dblift-cockroach`, internal corporate dialects) are distributed as separate pip-installable packages and register themselves the same way.

Adding a provider never requires changes to `core/`, `api/`, `cli/`, or `config/`.

## Prerequisites

- A working knowledge of the dialect's SQLAlchemy dialect/driver (or native SDK for non-SQLAlchemy transports).
- The `DialectQuirks` contract (see `docs/development/adding-database-support.md` and `db/base_quirks.py`).
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
   myprovider = "db.plugins.myprovider.plugin:PLUGIN"
   ```

   Use the explicit `packages = ["db.plugins.myprovider"]` (already in the template) so your distribution only contributes the leaf plugin directory. This avoids clobbering `dblift`'s `db/__init__.py`.

2. **plugin.py** — the registration point. It must export a module-level `PLUGIN` that is an instance of `PluginInfo`. The structure is identical to first-party:

   ```python
   from db.provider_registry import PluginInfo
   from db.plugins.myprovider.provider import MyproviderProvider
   from db.plugins.myprovider.quirks import MyproviderQuirks
   from db.plugins.myprovider.sqlalchemy_url import build_sqlalchemy_url

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

4. **provider.py**, **quirks.py** — implement behaviour and any required hooks. Start with the generated stubs. For pure SQLAlchemy drivers you usually only need to subclass `SqlAlchemyProvider`. See `docs/development/adding-database-support.md` for the full recipe (generators, parsers, introspection, the five manager components, etc.).

5. Add a driver extra if desired:

   ```toml
   [project.optional-dependencies]
   myprovider = ["mydriver>=x.y"]
   ```

## Step 3: Install & discover

```bash
cd dblift-myprovider
pip install -e .
python -c '
from db.provider_registry import ProviderRegistry
ProviderRegistry.discover_plugins()
print("myprovider" in ProviderRegistry._plugins)
print(ProviderRegistry._plugins["myprovider"])
'
```

`DBLiftClient`, the CLI, `from_config`, etc. will now accept `type: myprovider` (and your aliases) exactly as they accept `postgresql`.

## ADR-0026 constraints (must follow)

- **Plugin owns its URL builder.** `sqlalchemy_url_builder` on `PluginInfo` is the only place the mapping from config object → SQLAlchemy URL lives for your dialect. Do not add branches in `config/database_config.py`, `config/_url_builder_mixin.py`, or anywhere in `core/`.
- No edits outside your package. The isolation guarantee is verified by `tests/unit/test_plugin_isolation.py` and the `scripts/lint_patterns.py` "dialect-string-literal" rule.
- Quirks (via `provider.quirks`) are the single source of truth for dialect-specific rendering, parsing, comparison, and introspection behaviour.
- Third-party plugins are first-class: `ProviderRegistry` makes no distinction between in-tree and entry-point plugins after discovery.

## Discovery mechanics

- `ProviderRegistry.discover_plugins()` (called early by config loading and client factories) does two passes:
  1. Entry points (`importlib.metadata.entry_points(group="dblift.providers")`).
  2. Filesystem fallback under `db/plugins/` (only for in-tree development).
- Once registered, `ProviderRegistry.get_provider_by_name`, `create_provider`, `build_sqlalchemy_url`, `get_quirks` etc. work for your dialect.
- The same mechanism is used by `dblift.commands`, `dblift.command_handlers`, `dblift.features`, and `dblift.terminal_commands` for other extension points.

## Next steps / testing

- Add real tests under your package (or in a tests/ tree) exercising your URL builder, quirks hooks, and a minimal migration round-trip (SQLite-style or against a Docker service).
- When you are ready for first-party inclusion, the same files can be moved into the main tree under `db/plugins/<name>/` + one line added to the main `pyproject.toml` (the cookiecutter deliberately produces the identical shape).
- See also:
  - `docs/development/adding-database-support.md`
  - `docs/architecture/database-providers.md`
  - `docs/adr/0026-dialect-plugin-isolation.md`
  - `db/provider_registry.py` (the PluginInfo dataclass and discovery code)
  - Existing first-party plugins (especially `postgresql` for a full native SQLAlchemy example and `sqlite` for the simplest URL builder).

If your provider only needs the stock ANSI behaviour, the generated stubs + a correct `build_sqlalchemy_url` may be sufficient to get `migrate` / `info` / Python migrations working immediately.
