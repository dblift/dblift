# Plugin Entry Points and Install Extras

DBLift uses setuptools entry points for provider and extension discovery.

## Stable Python Imports

Plugin code should import schema-model types from the stable extension surface,
not from `dblift.core` implementation modules:

```python
from dblift.extensions.sql_model import Index, Table, View
```

The complete supported surface is listed in `dblift.extensions.sql_model.__all__`
and covered by the semantic-versioning policy.

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

Pass `connects=False` when the command your tool runs needs no database
connection — it runs from the project's files and configuration. The default is
`True`: a tool that does not say is assumed to connect, and a server started
`--offline` fails every such call with an error naming that flag. The tool is
still registered and listed; only the call refuses.

The server may have been started `--read-only`, `--mode review` or with
`--tools NAME[,...]`. A tool it will not accept — `read_only=False` on a
write-forbidding server or on a review session, or a name outside the
allowlist — is skipped and logged, never raised, so the server
still starts with what remains; `server.skipped_tools()` lists the skips. Offer
every tool unconditionally and let the server skip — do not consult
`server.allow_writes` (it is informational only) to withhold a tool: a tool the
registrar never offers is invisible to `--tools`, which then counts its name as
unknown and refuses to start, whereas an offered-but-skipped tool is admitted by
name and skipped with a reason. A skipped name stays reserved: registering it
again is still a duplicate. `--resources NAME[,...]` fences resources the same
way: `server.skipped_resources()` lists those skips, and a name in that
allowlist that nothing offered refuses to start, as with `--tools`.

`command_resource` is outside the **write** boundary — it takes no `read_only`,
so a resource must not run a writing command — but it is fenced by
`--resources NAME[,NAME...]` (which accepts the resource's name or its URI) and
it takes `connects=` exactly as a tool does.

A tool `fn`'s keyword-only parameters and their annotations become the tool's
input schema, and its docstring the description. Write those annotations however
you normally would — `Optional[str]`, `List[str]`, `dict[str, str]`, with or
without `from __future__ import annotations`; the server resolves them before
handing the signature to the SDK.

For a resource whose content is not a command's output — a document your
package ships, or one derived from the loaded configuration — call
`server.resource(uri=..., name=..., description=..., fn=...)` instead, where
`fn() -> str` takes no parameters and returns the resource text; `mime_type=`
(default `application/json`) labels it, and nothing is encoded for you. It is
the sibling of `raw_tool`, and it is fenced exactly as `command_resource` is:
by `--resources`, and by `--offline` unless you pass `connects=False`.
`connects` defaults to `True` as it does everywhere else — a registrar that
forgets it must not get an offline pass by omission — so pass `connects=False`
only when your body reads nothing but files and configuration. A duplicate
resource name or URI raises, exactly as a duplicate tool name does, and the
error says which of the two collided; a resource the `--resources` allowlist
skipped keeps both spellings reserved. It is outside the write boundary too:
neither `--read-only` nor `--tools` fences a resource, so its body must not
write. Raise the SDK's `ResourceError`, or a `CommandInvocationError`, to send
a message of your own to the client; any other exception type has its message
replaced.

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
