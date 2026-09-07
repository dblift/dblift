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

| Tool | Runs | Returns |
|---|---|---|
| `info` | `info --format json` | migration history rows |
| `validate` | `validate --format json` | validated / failed migrations |
| `migrate_dry_run` | `migrate --dry-run --format json` | what would be applied — never writes |
| resource `dblift://history` | `info --format json` | the `migrations` array |

Installed add-on packages can contribute further tools through the
`dblift.mcp_tools` entry-point group.

**Not exposed, on purpose:** applying migrations, `undo`, `clean`, `baseline`,
`repair`. An agent that needs them should ask you to run them. Tool errors carry
the same message the CLI prints (a missing configuration, a command the
installed edition does not cover, …) and never stop the server.
