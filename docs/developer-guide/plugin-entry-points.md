# Plugin Entry Points and Install Extras

DBLift uses setuptools entry points for provider and extension discovery.

## Entry Point Groups

### `dblift.providers`

Value: a module path that yields a `PluginInfo` instance, usually by importing
a module-level `PLUGIN` constant.

```toml
[project.entry-points."dblift.providers"]
postgresql = "dblift.db.plugins.postgresql.plugin:PLUGIN"
```

Third-party packages use the same pattern:

```toml
[project.entry-points."dblift.providers"]
snowflake = "dblift.db.plugins.snowflake.plugin:PLUGIN"
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

### `dblift.mcp_tools`

Value: a callable `register(server) -> None` receiving the `dblift mcp` server.
Call `server.command_tool(name=..., command=..., description=..., fn=...)` where
`fn(**params) -> list[str]` maps tool parameters to the subcommand's argv; the
tool result is that command's `--format json` payload. For a tool whose body
needs more than one command run, call `server.raw_tool(name=..., description=...,
fn=..., signature_of=...)` instead, supplying the handler directly. Tools are
read-only by contract. See `docs/user-guide/mcp.md`.

`fn`'s keyword-only parameters and their annotations become the tool's input
schema, and its docstring the description. Write those annotations however you
normally would — `Optional[str]`, `List[str]`, `dict[str, str]`, with or without
`from __future__ import annotations`; the server resolves them before handing
the signature to the SDK.

Pass `json_argv=None` to `command_tool` for a command that has no `--format`
option. The tool then returns `{"success": <bool>, "output": <stdout>}` — the
command's text output, unparsed — instead of a JSON payload.

Raise the SDK's `ToolError` (`mcp.server.mcpserver.exceptions`) for a failure of
your own: the SDK carries that message to the model and replaces the message of
any other exception type with a generic one. A `CommandInvocationError` from a
command run is already converted for you.

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
| `dblift[mcp]` | `mcp` | Enables the `dblift mcp` server. |
| `dblift[all]` | every engine extra above | Convenience meta-extra. |

A bare `pip install dblift` installs **no** database driver or SDK — including
Cosmos DB's. Every engine's client library sits behind its own extra, so the
plugins all have to import without their driver present; that is what keeps
`ProviderRegistry.discover_plugins()` working on a bare install.

## pytest-dblift

`pytest-dblift` is a separate PyPI package (`pip install pytest-dblift`), not a `dblift` extra. It registers a `pytest11` plugin. A bare `dblift` is enough for SQLite; other engines need the matching extra so the native driver is installed. See [`packages/pytest-dblift/README.md`](../../packages/pytest-dblift/README.md).

## Provider Packages

If you publish a `dblift-foo` provider:

```toml
[project.optional-dependencies]
foo = ["your-native-driver"]

[project.entry-points."dblift.providers"]
foo = "dblift.db.plugins.foo.plugin:PLUGIN"
```

See `docs/developer-guide/creating-a-provider.md` for the provider workflow.
