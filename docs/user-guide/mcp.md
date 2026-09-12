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

`validate` checks the migration history against the scripts on disk —
checksums, script order, missing files — it does not parse or check the SQL
inside them; a script with invalid SQL passes both `validate` and
`migrate_dry_run`.

## Restricting a session

`dblift mcp --read-only` skips every tool whose registrar declared it
`read_only=False`. It trusts declarations: it catches an honest add-on's
writing tool, not a dishonest one. The built-in tools are all read-only and
are unaffected.

`dblift mcp --tools NAME[,NAME...]` is the allowlist: only the named tools
are served, built-in or add-on, and everything else is skipped. An unknown
name makes the server refuse to start, so a typo cannot silently shrink the
tool list. This is the right choice for CI and for agents that should see
nothing beyond `info`, `validate` and `migrate_dry_run`:

```json
{
  "mcpServers": {
    "dblift": { "command": "dblift", "args": ["mcp", "--tools", "info,validate,migrate_dry_run"] }
  }
}
```

The two flags compose: `--read-only --tools export_schema` admits the name
and still skips the tool if it declares `read_only=False`. Skipped tools are
listed on stderr when the server starts; the server still serves what is
left. Resources (`dblift://history`, `dblift://pending`) are unaffected by
either flag: both connect to the database regardless of `--read-only` or
`--tools` — an allowlist fences tools, not resources.

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
command the installed edition does not cover, …) and never stop the server.
