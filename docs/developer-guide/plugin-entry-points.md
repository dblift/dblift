# Plugin Entry Points and Install Extras

DBLift uses setuptools entry points for provider and extension discovery.

## Entry Point Groups

### `dblift.providers`

Value: a module path that yields a `PluginInfo` instance, usually by importing
a module-level `PLUGIN` constant.

```toml
[project.entry-points."dblift.providers"]
postgresql = "db.plugins.postgresql.plugin:PLUGIN"
```

Third-party packages use the same pattern:

```toml
[project.entry-points."dblift.providers"]
snowflake = "db.plugins.snowflake.plugin:PLUGIN"
```

The plugin supplies provider classes, URL builders, optional quirks/config
classes, native driver metadata, and dialect aliases.

### `dblift.commands`

Value: a callable that receives an `argparse.ArgumentParser` and mutates it.
The OSS package declares the group so third-party packages can add commands.

### `dblift.command_handlers`

Value: a callable returning `dict[str, CommandHandler]`, where
`CommandHandler = Callable[[Any], tuple[bool, Any]]`.

### `dblift.terminal_commands`

Value: a callable returning `dict[str, TerminalCommand]`, where
`TerminalCommand = Callable[[Any], int]`.

### `dblift.features`

Reserved extension point. OSS treats this as neutral metadata.

## Install Extras

The main `dblift` wheel contains all first-party provider code. Extras install
the corresponding native drivers or thin integration dependencies.

| Extra | Installed dependencies | Effect |
| --- | --- | --- |
| `dblift[postgresql]` | `psycopg[binary]` | Enables PostgreSQL connections. |
| `dblift[oracle]` | `oracledb` | Enables Oracle connections. |
| `dblift[mysql]` | `PyMySQL` | Enables MySQL and MariaDB connections. |
| `dblift[cosmosdb]` | `azure-cosmos`, `azure-identity` | Enables Azure Cosmos DB connections. |
| `dblift[fastapi]` | `fastapi` | Enables FastAPI integration helpers. |
| `dblift[flask]` | `flask` | Enables Flask integration helpers. |
| `dblift[all]` | every engine extra above | Convenience meta-extra. |

A bare `pip install dblift` installs **no** database driver or SDK — including
Cosmos DB's. Every engine's client library sits behind its own extra, so the
plugins all have to import without their driver present; that is what keeps
`ProviderRegistry.discover_plugins()` working on a bare install.

## Provider Packages

If you publish a `dblift-foo` provider:

```toml
[project.optional-dependencies]
foo = ["your-native-driver"]

[project.entry-points."dblift.providers"]
foo = "db.plugins.foo.plugin:PLUGIN"
```

See `docs/developer-guide/creating-a-provider.md` for the provider workflow.
