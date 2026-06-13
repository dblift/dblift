# Plugin Entry Points and Install Extras

DBLift uses setuptools entry points for all extension and plugin discovery. This makes first-party code, third-party packages, and the (future) `dblift-enterprise` package indistinguishable at runtime.

All groups are declared in the main `pyproject.toml` (even when empty). This documents the public contract and lets tools / type checkers / downstream packages see the extension surface.

## Entry Point Groups

### `dblift.providers`

Value: a module path that yields a `PluginInfo` instance (usually by importing a module-level `PLUGIN` constant).

Example (first-party):

```toml
[project.entry-points."dblift.providers"]
postgresql = "db.plugins.postgresql.plugin:PLUGIN"
```

Third-party packages use the identical pattern, e.g.:

```toml
[project.entry-points."dblift.providers"]
snowflake = "db.plugins.snowflake.plugin:PLUGIN"
```

See `ProviderRegistry.discover_plugins()`, `PluginInfo`, and `docs/developer-guide/creating-a-provider.md`.

The plugin supplies:
- `provider_class`
- `sqlalchemy_url_builder` (plugin-owned per ADR-0026)
- `quirks_class` (optional)
- `config_class` (optional, for custom config fields)
- `native_driver_module` (for availability checks)
- `dialects` list (the names under which the provider is known)

### `dblift.commands`

Value: a callable that receives an `argparse.ArgumentParser` and mutates it (typically by adding sub-parsers or argument groups).

Used by `cli.extensions.load_command_extensions`.

The builtin implementation lives in `cli.extensions:register_builtin_command_extensions` and is deliberately skipped when other entries are processed so that third-party / enterprise commands can coexist.

### `dblift.command_handlers`

Value: a callable that returns a `dict[str, CommandHandler]` where `CommandHandler = Callable[[Any], tuple[bool, Any]]`.

Used by `cli.extensions.load_command_handlers` (duplicate names raise at load time).

Builtin handlers are provided by `cli.extensions:load_builtin_command_handlers`.

### `dblift.terminal_commands`

Value: a callable returning `dict[str, TerminalCommand]` (`TerminalCommand = Callable[[Any], int]`).

Loaded by `cli.extensions.load_terminal_commands`. Intended for commands that take over the whole process (exit code based) rather than the normal (success, result) contract.

### `dblift.features`

Reserved extension point (currently empty in the public package).

Enterprise / paid packages register feature metadata, entitlement claims, or factory hooks here. OSS code treats the group as a neutral extension surface (see `docs/architecture/oss-enterprise-boundaries.md`).

## Install Extras (`[project.optional-dependencies]`)

The main `dblift` wheel always contains **all** first-party providers (via their `db/plugins/*` code + the `dblift.providers` entries). The extras only pull in the corresponding native drivers or thin integration dependencies.

| Extra                | Installed dependencies                          | Effect on providers / surface                                                                 |
|----------------------|-------------------------------------------------|-----------------------------------------------------------------------------------------------|
| `dblift[postgresql]` | `psycopg[binary]`                               | Enables the PostgreSQL provider at runtime (the provider registration itself is unconditional). |
| `dblift[oracle]`     | `oracledb`                                      | Enables the Oracle provider (all first-party providers including Oracle ship in OSS; Pro/Enterprise *features* such as `plan`, paid `validate-sql` packs etc. require `dblift-enterprise` on top). |
| `dblift[mysql]`      | `PyMySQL`                                       | MySQL (and mariadb extra reuses the same driver).                                             |
| `dblift[fastapi]`    | `fastapi`                                       | Brings in the thin FastAPI integration helpers (`dblift.integrations.fastapi`). The helpers are info-only guards; no separate execution engine. |
| `dblift[flask]`      | `flask`                                         | Brings in the thin Flask integration helpers (`dblift.integrations.flask`).                   |
| `dblift[all]`        | all of the above DB drivers                     | Convenience meta-extra.                                                                       |

### `pytest-dblift`

Separate PyPI package (see `packages/pytest-dblift/`).

```bash
pip install pytest-dblift
```

It depends on `dblift` (and pytest) and registers itself under the `pytest11` entry point group. It is **not** an extra of the main `dblift` wheel.

Provides the `dblift_*` fixtures and `--dblift-*` CLI options for pytest-based tests that use `DBLiftClient.from_sqlalchemy`.

### `dblift-enterprise`

Feature add-on package (private / paid). Typical usage:

```bash
pip install dblift[postgresql] dblift-enterprise
```

- Depends on `dblift`.
- Registers additional entries under `dblift.commands`, `dblift.features` (and potentially `dblift.command_handlers` / terminal) for Pro/Enterprise surfaces (`plan`, `preflight`, `snapshot`, `diff`, paid validation, enterprise reports, license handling, etc.).
- Does **not** duplicate or replace database providers — all first-party dialects remain in the base `dblift` package.

Feature gating is performed inside the registered handlers / feature objects using the license claims; the base OSS command surfaces stay usable without the enterprise package.

## How to consume in your own package

If you publish a `dblift-foo` provider:

```toml
[project.optional-dependencies]
foo = ["your-native-driver"]

[project.entry-points."dblift.providers"]
foo = "db.plugins.foo.plugin:PLUGIN"
```

Consumers then do:

```bash
pip install dblift dblift-foo
# or
pip install "dblift[foo]"   # only if you also publish a matching extra on the *main* dblift metadata (rare)
```

The second form only makes sense for first-party drivers that we chose to expose as extras on the core wheel.

See `docs/developer-guide/creating-a-provider.md` for the full cookiecutter-based workflow and the ADR-0026 rules around URL builders.
