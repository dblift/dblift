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
fn=..., signature_of=...)` instead, supplying the handler directly. Tools default
to read-only (`read_only_hint` and `idempotent_hint` both true, `destructive_hint`
false). A registrar whose tool writes a file the caller names — not one of
these commands — should pass `read_only=False` to either call, which reports the
tool as neither read-only nor idempotent. A writing tool is additive by default;
pass `destructive=True` as well when it overwrites a caller-named path, which
sets `destructive_hint`. `destructive=True` with `read_only=True` is a
contradiction and raises `ValueError` (`destructive_hint` is only meaningful
when `read_only_hint` is false). See `docs/user-guide/mcp.md`.

The server may have been started `--read-only` or with `--tools NAME[,...]`. A
tool it will not accept — `read_only=False` on a write-forbidding server, or a
name outside the allowlist — is skipped and logged, never raised, so the server
still starts with what remains; `server.skipped_tools()` lists the skips. A
registrar can read `server.allow_writes` to decide what to offer. A skipped name
stays reserved: registering it again is still a duplicate.

`fn`'s keyword-only parameters and their annotations become the tool's input
schema, and its docstring the description. Write those annotations however you
normally would — `Optional[str]`, `List[str]`, `dict[str, str]`, with or without
`from __future__ import annotations`; the server resolves them before handing
the signature to the SDK.

Pass `json_argv=None` to `command_tool` for a command that has no `--format`
option. The tool then returns `{"success": <bool>, "output": <text>}` instead of
a JSON payload — `text` is the command's captured stdout followed by its
captured stderr (each stripped, joined with a newline, empty parts omitted).
A command's content may land on either console — some commands render
through the stdout console, others through the console logger, which writes
to stderr — so both are joined rather than risk losing whichever one
carried it.

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
