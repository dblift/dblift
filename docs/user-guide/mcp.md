# dblift with coding agents (MCP)

`dblift mcp` serves dblift's built-in read-only commands as tools over the
Model Context Protocol on stdin/stdout. A coding agent (Claude Code, Cursor, Copilot) starts it
as a subprocess in your project directory; it uses the same `dblift.yaml`,
environment variables and secrets your shell would.

```bash
pip install "dblift[mcp]"
```

Claude Code — `.mcp.json` at the project root:

```json
{ "mcpServers": { "dblift": { "command": "dblift", "args": ["mcp"] } } }
```

Root flags go before `mcp` and apply to every tool call:
`"args": ["--config", "config/dblift.yaml", "--env", "dev", "mcp"]`.

At start, the server prints on stderr the environment it resolved and the
database it will use, never a secret — check that line before letting an
agent call anything, especially if you meant to pin it to a read-only
environment. A missing or unreadable configuration file, an unknown
environment, an invalid database field (a bad port, a missing username) or a
secret that cannot be resolved never stops the start — the line says so and
the server starts anyway; every tool call still loads the configuration
itself and reports its own error.

Each tool call logs under `--log-dir`, exactly as one CLI invocation does.
With the default text log format, the server writes one log file per
session: the first call's file is reused and appended to for every later
call in that process. HTML and JSON log formats do not share a file across
calls — HTML rewrites the whole file on every result and JSON writes the
complete document when the log closes, so a shared file would erase the
previous call's log. Asking for a second format alongside text
(`--log-format text,html`) is not shared either, since both formats are
named from the same pattern. Those formats name their file after the time
it was opened, so calls within the same second still land in one file.

| Tool | Runs | Returns |
|---|---|---|
| `info` | `info --format json` | migration history rows |
| `validate` | `validate --format json` | validated / failed migrations |
| `migrate_dry_run` | `migrate --dry-run --format json` | what would be applied — applies nothing |
| resource `dblift://history` | `info --format json` | the `migrations` array |
| resource `dblift://pending` | `migrate --dry-run --format json` | pending migrations as a JSON array, the same rows `migrate_dry_run` returns |

`validate` checks the scripts on disk for consistency (duplicate versions,
unsupported formats) and, once migrations have been applied, compares them
against the recorded history too — checksums, script order, missing files.
It does not parse or check the SQL inside them; a script with invalid SQL
passes both `validate` and `migrate_dry_run`.

Pass `show_sql: true` to `migrate_dry_run` to also run with `--show-sql`; the
result then carries a `sql` array with each pending migration's rendered
statements — review it to catch an unresolved `${VAR}` or an unexpected
value before proposing the change. Without it, the result has no `sql` key.

## What protects the database

None of the built-in tools can apply, undo or clean a migration (see *Not
exposed* below). That is not what protects a database from an agent, though.
The agent has a shell next to this server, and both run with the same
`dblift.yaml`, environment variables and secrets. What protects the database is
the role the server connects with and the environment it is pointed at. The
flags in the next section only shape what an agent sees and asks this server
for: `--read-only` and `--mode review` trust each tool's own `read_only`
declaration, `--offline` trusts its `connects` declaration, `--tools` and
`--resources` are exact-name allowlists, and all of them live in a file the
agent can edit.

**Give the agent a role that can only read.** Once the schema-history table
exists, `info`, `validate` and `migrate_dry_run` need `USAGE` on the schema and
`SELECT` on its tables, nothing else; the integration suite pins this on
PostgreSQL. On a database that has no history table yet, the reader has no
`CREATE`, so `info` and `validate` fail instead of creating it, and
`migrate_dry_run` neither fails nor creates it: a dry run skips the table
entirely and reports every script as pending. Create the table with the role
that applies migrations first (`dblift migrate` or `dblift baseline`), then
hand the reader to the agent. On PostgreSQL:

```sql
CREATE ROLE dblift_reader LOGIN PASSWORD '...';
GRANT USAGE ON SCHEMA public TO dblift_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dblift_reader;
```

**Point the server at its own environment and pin it.** Declare the reader's
credentials as an environment of their own and name it in `.mcp.json`, so the
agent never runs under the block your deploy pipeline uses. An environment is
deep-merged over the root sections (see [Configuration](configuration.md#environments)), so
only the credential differs:

```yaml
database:
  type: postgresql
  host: localhost
  database: app
  username: dblift_app
  password: "${DBLIFT_APP_PASSWORD}"

environments:
  agent:
    database:
      username: dblift_reader
      password: "${DBLIFT_READER_PASSWORD}"
```

```json
{ "mcpServers": { "dblift": { "command": "dblift", "args": ["--env", "agent", "mcp"] } } }
```

`--env` placed before `mcp` applies to every tool call, and no tool argument
can change it.

**Keep production out of the agent's process entirely.** The credential that
can `CREATE`, `DROP` or `TRUNCATE` belongs to the pipeline that runs
`dblift migrate`, not to a developer's shell with a coding agent in it. A
production connection string in that shell's environment is reachable by the
agent whatever this server withholds. A rule in a prompt is a request; a
secret that is not there is a lock.

## Restricting a session

These flags narrow what an agent can ask this server for. They are not what
protects the database; the section above is.

`dblift mcp --read-only` skips every tool whose registrar declared it
`read_only=False`. It trusts declarations: it catches an honest add-on's
writing tool, not a dishonest one. The built-in tools are all read-only and
are unaffected.

`dblift mcp --tools NAME[,NAME...]` is the allowlist: only the named tools
are served, built-in or add-on, and everything else is skipped. An unknown
name makes the server refuse to start, so a typo cannot silently shrink the
tool list, and so does a list with no usable name in it (`--tools ""`) rather
than serving everything. This is the right choice for CI and for agents that
should see nothing beyond `info`, `validate` and `migrate_dry_run`:

```json
{
  "mcpServers": {
    "dblift": { "command": "dblift", "args": ["mcp", "--tools", "info,validate,migrate_dry_run"] }
  }
}
```

`dblift mcp --mode review` serves a review session. It withholds the same
tools `--read-only` does — every tool whose registrar declared it
`read_only=False` — and additionally tells the agent, in the server
instructions, that the session is for reading and reporting rather than for
producing files. Use `--read-only` when you are fencing a job's capabilities
and `--mode review` when you are telling an agent what it is there for; the
default, `--mode author`, restricts nothing. The mode is the only thing the
server does with it: where an add-on command reads the mode and softens a
stop into a warning — a stale input a review may report on but an authoring
run must not build from — that behaviour is the command's, not the server's.

`dblift mcp --resources NAME[,NAME...]` is the allowlist for resources, the
way `--tools` is the one for tools. `--resources history` serves
`dblift://history` and withholds `dblift://pending`; either spelling works
(`history` or `dblift://history`), and an unknown name — or an empty list —
makes the server refuse to start, as with `--tools`. `--tools` has never
fenced resources and still does not: an allowlist written before this flag
existed keeps serving both resources.

`dblift mcp --offline` refuses every tool and resource that would open a
database connection. The refusal happens when the tool is called, not when
the server starts: the tool stays in `tools/list` and the call returns an
error naming `--offline`, so an agent is told why rather than left to guess
from a missing tool. **All three built-in tools and both built-in resources
read the schema-history table**, so on an install with no add-on packages an
offline server refuses everything; the flag is for installs whose add-on
tools run from the project's files. The server starts even with no
`dblift.yaml` and no database configured — the configuration is read at
start only to print the resolved target; no connection is opened until a
tool is called. Start-up prints, on stderr, which registrations will refuse.

The flags compose: `--read-only --tools my_addon_tool` admits the name an
add-on contributed and still skips the tool if it declares
`read_only=False`; `--offline --tools
info` serves `info` and refuses every call to it; `--tools` and `--resources`
fence their own lists side by side, and a name unknown to either refuses the
start. Skipped tools and resources are listed on stderr when the server
starts; the server still serves what is left.

Installed add-on packages can contribute further tools through the
`dblift.mcp_tools` entry-point group. An add-on tool that overwrites a file
you name reports `destructive_hint` true, and a client that auto-approves
non-destructive tools should prompt for it.

**Not exposed, on purpose:** applying migrations, `undo`, `clean`, `baseline`,
`repair`. None of the built-in tools above applies, undoes or cleans a
migration, and none changes your data; an agent that needs one of those
should ask you to run it. The one write a built-in tool can cause is the one
every dblift command can: the first call against a database with no
schema-history table creates that table. An add-on tool may not be
read-only — each tool declares its own read-only hint, and a client should
trust that per-tool hint over this paragraph.

Tool errors carry the same message the CLI prints (a missing configuration, a
command the installed edition does not cover, …) and never stop the server. A
command that fails before producing a result — a refused connection, a
history table that could not be created, an exception inside the command —
is returned as an MCP error result carrying the CLI's message, and
`dblift://history` / `dblift://pending` report that failure instead of
returning an empty list. A command that ran to a result, even a failed one
such as validation issues, is still a normal result with `success: false`.
