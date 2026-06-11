# Database Provider System

**Location:** `db/plugins/`

Each supported database is a self-contained **plugin** under `db/plugins/<dialect>/`.
Adding a new database requires creating only that folder — no file in `core/`, `api/`,
`cli/`, or `config/` needs to change (ADR-0026, ADR-0027).

Providers are classified by transport:

- **Native SQLAlchemy providers** — connect through SQLAlchemy Core and Python database drivers; relational databases.
- **Native providers** — connect via a Python SDK (CosmosDB uses `azure-cosmos`).

---

## Plugin structure

Every plugin folder follows this layout:

```
db/plugins/<dialect>/
├── __init__.py
├── plugin.py          # PluginInfo constant — registered via pyproject.toml entry-point
├── quirks.py          # DialectQuirks subclass — all dialect-specific behaviour
├── provider.py        # BaseProvider subclass — connection lifecycle
├── generator/
│   ├── ddl_generator.py    # CREATE / DROP DDL
│   └── alter_generator.py  # ALTER TABLE DDL
├── parser/
│   ├── <dialect>_regex_parser.py
│   └── parser_config.py
```

A plugin folder contains 100 % of the dialect-specific code; adding a
new database touches no other directory in the tree.

### plugin.py — entry-point registration

```python
from db.provider_registry import PluginInfo
from db.plugins.mydb.provider import MyDbProvider
from db.plugins.mydb.quirks import MyDbQuirks

PLUGIN = PluginInfo(
    name="mydb",
    version="1.0.0",
    description="MyDB provider",
    dialects=["mydb"],           # all name variants that resolve to this plugin
    sqlalchemy_url_builder=build_sqlalchemy_url,
    provider_class=MyDbProvider,
    transport="native",
    quirks_class=MyDbQuirks,
)
```

Register in `pyproject.toml`:
```toml
[project.entry-points."dblift.providers"]
mydb = "db.plugins.mydb.plugin:PLUGIN"
```

`ProviderRegistry.discover_plugins()` finds every installed plugin via
`importlib.metadata.entry_points(group="dblift.providers")` — no hardcoded list in core.

---

## Plugin discovery

`ProviderRegistry` uses a two-pass strategy:

1. **Entry-point pass** — reads `importlib.metadata.entry_points(group="dblift.providers")`.
   First-party plugins are registered here when the wheel is installed; third-party plugins
   install their own package and register through the same group.

2. **Filesystem fallback** — scans `db/plugins/<X>/` for any dialect not yet registered.
   Used during source-checkout development (e.g., running tests without installing the package).

---

## DialectQuirks — the plugin's behaviour contract

`BaseQuirks` (`db/base_quirks.py`) is the single interface between `core/` and each plugin.
Core calls hook methods; plugins override only the deltas. Every hook has a safe default so
unregistered dialects degrade gracefully.

### Hook categories

| Category | Hook method(s) | Default |
|---|---|---|
| **Parser** | `parser_class(parser_type)` | `None` |
| **Type normalisation** | `normalize_column_data_type(col, data_type)` | passthrough |
| **Identity/auto-increment** | `render_identity_clause(col)` | `None` |
| **Column ALTER** | `render_column_nullable_change(...)`, `render_column_default_change(...)`, `render_column_type_change(...)`, `render_column_collation_change(...)` | `None` (warning logged) |
| **Default value unwrap** | `unwrap_default_value(default_str, col)` | passthrough |
| **DROP generation** | `render_drop_for_object(obj_type, name, schema_prefix, table_name)` | `None` (uses BaseQuirks generic) |
| **SQL\*Plus preprocessing** | `supports_sqlplus_preprocessing` | `False` |
| **SDK operations** | `requires_sdk_for_drop()`, `sdk_operation_hint_prefix()` | `False` / `None` |
| **sqlglot** | `sqlglot_dialect`, `sqlglot_unsupported_sql_patterns`, `is_sqlglot_opaque_valid_ddl(sql)`, `preprocess_sql_for_sqlglot(sql)` | `None` / `()` / `False` / passthrough |
| **FK safety check** | `fk_reference_bind_params(schema, table, col)` | `[schema, table, col]` |
| **Round-trip testing** | `round_trip_extra_object_types()` | `[]` |
| **Identifiers** | `uppercase_identifiers`, `quote_open`, `quote_close`, `unquoted_identifier_case` | `False` / `"` / `"` / `"lowercase"` |
| **Transactions** | `supports_transactions`, `supports_transactional_ddl` | `False` / `False` |
| **Schema defaults** | `default_schema_name`, `parser_default_schema` | `None` / `None` |
| **Capabilities** | `drop_supports_if_exists`, `drop_table_default_cascade`, `select_supports_limit`, etc. | conservative defaults |
| **DDL shape** | `table_drop_style`, `proc_body_wrap_style`, `trigger_body_style`, sequence/index/synonym flags | ANSI defaults |
| **Migration scripts** | `extract_script_context(sql)`, `terminate_script_directives(sql)`, `apply_script_substitution(sql, ctx)`, `is_script_directive(stmt)`, `parse_error_policy_directive(stmt)`, `enable_session_output(connection)`, `read_session_output(connection, log)`, `is_batch_separator(stmt)` | `None` / passthrough |

A complete reference is in `db/base_quirks.py`.

---

## Layering contract

Three invariants govern imports between `core/`, `db/`, and individual
plugins. They are enforced in CI by
`tests/unit/test_plugin_isolation.py` — every violation either fails
the build or has to be registered as a documented exemption with a
follow-up reference.

### Rule 1 — no hardcoded `core` → plugin imports

Code in `core/` must not write `from db.plugins.<specific>...`. Core
talks to plugins through two channels only:

- `BaseQuirks` hooks (`parser_class(...)`,
  `is_batch_separator(...)`, etc.) called
  via `ProviderRegistry.get_quirks(dialect).<hook>`.

A new dialect is added by dropping a folder under `db/plugins/` —
never by editing `core/`.

### Rule 2 — no cross-plugin imports

A file in `db/plugins/<a>/` must not import from `db/plugins/<b>/`
(a ≠ b). Plugins are siblings — they communicate through the
abstract interfaces in `db/` (`BaseQuirks`, `BaseProvider`,
`BaseHistoryManager`, `BaseLockingManager`, `BaseQueryExecutor`,
`BaseSchemaOperations`).

Two intentional exceptions are documented in
`ALLOWED_CROSS_PLUGIN_IMPORTS`:

- **MariaDB ⊃ MySQL** — `MariadbQuirks` extends `MysqlQuirks` (same
  Python driver family, same SQL dialect for ~95% of cases).
- **CosmosDB parser ⊃ SQL Server parser** — CosmosDB SQL is
  T-SQL-flavoured enough that its regex parser inherits SQL Server's.

A new exception requires adding the entry and a brief justification
to that constant.

### How CI enforces it

`test_plugin_isolation.py` parses every `.py` file under `core/` and
`db/plugins/` with `ast` and asserts the three rules. Both top-level
and function-scope imports count — a lazy import is still a coupling.

`KNOWN_CORE_TO_PLUGIN_VIOLATIONS` (Rule 1) carries entries awaiting
follow-up; each entry must reference the PR or ADR that justifies
the exemption. A companion test asserts every listed violation is
still present in source — once a follow-up PR removes the import,
the allow-list entry must go with it (no dead exemptions). After
the introspection-to-core move and the H.2 followup, this dict is
empty: every dialect decision routes through `BaseQuirks`.

---

## BaseProvider — connection lifecycle

`BaseProvider` (`db/base_provider.py`) owns the connection and delegates to five components:

```
BaseProvider
├── ConnectionManager  — creates / configures the connection
├── QueryExecutor      — executes SQL and returns results
├── SchemaOperations   — CREATE SCHEMA, DROP SCHEMA, clean
├── LockingManager     — acquire / release migration lock
└── HistoryManager     — read / write dblift_schema_history
```

**Design rule:** components receive `connection` as a parameter — they never store it.
The provider owns the connection lifecycle; components are stateless.

### Locking strategies

| Database | Strategy |
|---|---|
| PostgreSQL | Advisory locks (`pg_advisory_lock`) |
| SQL Server | Application locks (`sp_getapplock`) |
| Oracle | DBMS_LOCK package |
| MySQL / MariaDB | Named locks (`GET_LOCK`) |
| DB2 | Table-based locking |
| SQLite | Table-based with busy timeout |
| CosmosDB | ETag-based optimistic concurrency |

---

## Supported databases

| Database | Plugin | Transport |
|---|---|---|
| PostgreSQL | `db/plugins/postgresql/` | Native SQLAlchemy (`psycopg`) |
| MySQL | `db/plugins/mysql/` | Native SQLAlchemy (`PyMySQL`) |
| MariaDB | `db/plugins/mariadb/` | Native SQLAlchemy (`PyMySQL`, inherits MySQL) |
| SQL Server | `db/plugins/sqlserver/` | Native SQLAlchemy (`pymssql`) |
| Oracle | `db/plugins/oracle/` | Native SQLAlchemy (`python-oracledb`) |
| DB2 | `db/plugins/db2/` | Native SQLAlchemy (`ibm_db_sa`) |
| SQLite | `db/plugins/sqlite/` | Python native |
| CosmosDB | `db/plugins/cosmosdb/` | Azure SDK |

---

## Native connection integration

```
NativeConnectionManager  — owns SQLAlchemy Engine / Connection lifecycle
SqlAlchemyProvider       — implements the provider contract over SQLAlchemy Core
PluginInfo               — exposes the plugin-owned SQLAlchemy URL builder
```

Legacy runtime transport infrastructure has been removed after the relational plugins moved to native validation.

---

## Related documentation

- **[Architecture overview](overview.md)** — system-level architecture
- **[SQL parsing](sql-parsing.md)** — how dblift parses and generates SQL per dialect
- **[CONTRIBUTING.md](../../CONTRIBUTING.md)** — how to contribute a new database provider
