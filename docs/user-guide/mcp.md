# dblift with coding agents (MCP)

`dblift mcp` serves the read-only commands as tools over the Model Context
Protocol on stdin/stdout. A coding agent (Claude Code, Cursor, Copilot) starts it
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

Each tool call writes its own log file under `--log-dir`, exactly as one CLI
invocation does — an agent working through a session leaves several files
behind, not one per server run.

| Tool | Runs | Returns |
|---|---|---|
| `info` | `info --format json` | migration history rows |
| `validate` | `validate --format json` | validated / failed migrations |
| `migrate_dry_run` | `migrate --dry-run --format json` | what would be applied — applies nothing |
| resource `dblift://history` | `info --format json` | the `migrations` array |

`validate` checks the migration history against the scripts on disk —
checksums, script order, missing files — it does not parse or check the SQL
inside them; a script with invalid SQL passes both `validate` and
`migrate_dry_run`.

Installed add-on packages can contribute further tools through the
`dblift.mcp_tools` entry-point group.

**Not exposed, on purpose:** applying migrations, `undo`, `clean`, `baseline`,
`repair`. No tool applies, undoes or cleans a migration, and none changes your
data; an agent that needs one of those should ask you to run it. The one write
a tool can cause is the one every dblift command can: the first call against a
database with no schema-history table creates that table.

Tool errors carry the same message the CLI prints (a missing configuration, a
command the installed edition does not cover, …) and never stop the server.
