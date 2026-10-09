# Commands Reference

This guide covers all DBLift commands and their usage.

## Global Flags

Every command accepts these configuration-selection flags before the command
name:

| Flag | Purpose |
|---|---|
| `--config <path>` | Path to the configuration file |
| `--env <name>` | Active environment from the file's `environments:` section (see [Configuration → Environments](configuration.md#environments)) |

```bash
dblift --env prod migrate     # or: dblift migrate --env prod
```

## Common Tasks

### Applying Changes to Your Database

**See what needs to be applied:**
```bash
dblift info
```
This shows you which migrations are pending (not yet applied) and which are already done.

**Apply pending migrations:**
```bash
dblift migrate
```
This will run all migrations that haven't been applied yet, in order.

**Preview changes before applying:**
```bash
dblift migrate --dry-run
```
This shows you what would happen without actually making changes.

Both `validate` and `migrate` accept `--format json` for scripts and agents. The payload
carries `success`, `error` and the per-migration rows (`script`, `version`, `status`,
`checksum`, …); `migrate --dry-run --format json` also reports `dry_run_count`. A pending
SQL script's row, in `info` and in `migrate --dry-run`, carries `analysis`: its statements
(`operation`, `kind`, the `objects` each names, `full_table` for an UPDATE or DELETE
without WHERE) and `cautions`, each `destroys` (DROP TABLE, VIEW or SCHEMA, TRUNCATE,
DROP COLUMN, UPDATE or DELETE without WHERE) or `changes_rows` (UPDATE, DELETE, MERGE)
and naming its rule in `code` (`null` when no rule applies); and the script's `verdict`
and `findings`, as [`validate-sql`](#checking-migration-sql) reports them. All of it is
read from the file in the database's dialect without connecting; `analysis` is `null` on
applied rows and on Python scripts. The console output of `migrate --dry-run` shows each
pending script's verdict and the findings it does not allow. Neither command's exit code
depends on the verdict, and the SQL is not checked for validity:

```bash
dblift migrate --dry-run --format json
```

### Checking Migration Status

**View all migrations:**
```bash
dblift info
```

You'll see a summary line and a standardized table:
```
Current schema version: 1.0.1

| Category | Version | Description             | Type      | Installed On        | Installed By | State    | Undoable | Execution Time |
|----------|---------|-------------------------|-----------|---------------------|--------------|----------|----------|----------------|
| Applied  | V1_0_0  | create_users_table      | VERSIONED | 2024-01-15 10:42:12 | db_admin     | Success  | Yes      | 120 ms         |
| Applied  | V1_0_1  | add_email_column        | VERSIONED | 2024-01-16 09:07:51 | db_admin     | Success  | Yes      | 85 ms          |
| Pending  | V1_0_2  | create_orders_table     | VERSIONED |                     |              | Pending  | No       | --             |

Command info completed successfully in 128 ms
```
The **Undoable** column tells you whether there's a matching undo migration ready to roll the change back.

!!! tip "Tip"
    Every CLI command now ends with a completion banner like the one above, including the total execution time. This makes automation logs much easier to scan.

### Checking Migration SQL

`dblift validate` checks your scripts against the applied history; it does not read the
SQL. `dblift validate-sql` reads the SQL, without connecting to a database, and reports
statements that destroy data, break the application already deployed, or lock a table:

```bash
dblift validate-sql                                        # V and R scripts of the migration directories
dblift validate-sql --files migrations/V7__drop_legacy.sql # only these files
dblift validate-sql --dialect postgresql --format json     # machine-readable findings
```

**What it reads.** Without `--files`, the `V` and `R` scripts of the migration directories
(`migrations.directory`, or each `--scripts` directory). Undo, baseline and callback
scripts are read only when you name them with `--files`: an undo script destroys what its
migration created by design. Placeholders (`${name}`) from the `placeholders` section of
your configuration file, or given with `--placeholders key=value`, are substituted before a
script is read.

**Dialect.** Scripts are read in the dialect given by `--dialect`, or else in the
configured database type (`database.type`, or the scheme of the database URL). With neither,
the command stops and asks for `--dialect`. The database flags (`--db-url`, …) are accepted
but nothing connects.

**Rules.** Each finding has a code and a fixed severity:

| Code | What it detects | Severity | Dialects |
|---|---|---|---|
| `drop-table` | `DROP TABLE` or `DROP MATERIALIZED VIEW` | error | all |
| `drop-schema` | `DROP SCHEMA` or `DROP DATABASE` | error | all |
| `drop-column` | `ALTER TABLE … DROP COLUMN` | error | all |
| `truncate` | `TRUNCATE` | error | all |
| `mixed-transaction-modes` | A statement that needs autocommit (for example `CREATE INDEX CONCURRENTLY`) in a script whose other statements run in a transaction: `migrate` refuses such a script | error | all |
| `dml-no-where` | `UPDATE` or `DELETE` without `WHERE` | warning | all |
| `add-not-null-no-default` | `ADD COLUMN … NOT NULL` without a `DEFAULT`, on a table the script did not create | warning | all |
| `rename-column` | A column rename (`RENAME COLUMN`, `sp_rename … 'COLUMN'`) | warning | all |
| `rename-table` | A table rename (`RENAME TO`, `RENAME TABLE`, `sp_rename`) | warning | all |
| `alter-column-type` | A column type change (`ALTER COLUMN … TYPE`, `MODIFY`, `CHANGE`) | warning | all |
| `pg-index-not-concurrent` | `CREATE INDEX` without `CONCURRENTLY` on a table the script did not create | warning | PostgreSQL family |
| `pg-constraint-not-valid` | `ADD CONSTRAINT … FOREIGN KEY` or `CHECK` without `NOT VALID` | warning | PostgreSQL family |
| `pg-set-not-null` | `ALTER COLUMN … SET NOT NULL` | warning | PostgreSQL family |
| `pg-missing-lock-timeout` | The first statement that locks an existing table (`ALTER TABLE`, `CREATE INDEX`, `DROP TABLE`, `TRUNCATE`) with no `SET lock_timeout` earlier in the script; reported once per script | warning | PostgreSQL family |
| `statement-not-analysed` | An `ALTER` statement the SQL parser could not structure, so no rule could check it | info | all |

The PostgreSQL family is `postgresql`, `neon`, `supabase`, `aurora-postgresql`, `alloydb`,
`timescaledb` and `citus`. The `add-not-null-no-default` and `pg-` rules skip a table
created earlier in the same script: it has no rows yet and nothing else uses it.

**Verdict.** Each script gets one verdict:

- `UNSAFE`: at least one `error` finding.
- `REVIEW`: no error, but at least one `warning` or `info` finding (a statement that could
  not be analysed counts), or a part of the script that could not be read.
- `SAFE`: no finding left.

**Accepting a finding.** A comment `-- dblift:allow code[, code]` anywhere in a script
accepts those codes for the whole script. The findings are still listed, marked
`(allowed)` in the console and `"allowed": true` in JSON, but they no longer count toward the
verdict:

```sql
-- dblift:allow drop-column, pg-missing-lock-timeout
ALTER TABLE users DROP COLUMN legacy_flag;
```

**Exit code.** `0` when no script is `UNSAFE`; `1` when a script is `UNSAFE` or a path given
with `--files` does not exist. A `REVIEW` verdict does not fail the command.

**Console output.** Each script, its verdict, then each finding with its statement
(numbered from 1) under it:

```
V2__drop_legacy.sql: UNSAFE
  error   drop-column, statement 1: DROP COLUMN discards a column of users
          ALTER TABLE users DROP COLUMN legacy_flag;
  warning pg-missing-lock-timeout, statement 1: takes a table lock with no lock_timeout set earlier in the script, so queries on the table can queue behind it; start with SET LOCAL lock_timeout = '5s'
          ALTER TABLE users DROP COLUMN legacy_flag;
  warning pg-index-not-concurrent, statement 2: CREATE INDEX without CONCURRENTLY blocks writes to the table while the index builds (row count unknown — severity not adjusted for table size)
          CREATE INDEX idx_users_email ON users (email);
1 script(s): 0 SAFE, 0 REVIEW, 1 UNSAFE
```

**JSON output.** `--format json` prints `success`, `error` (a missing `--files` path, or
`null`), the `dialect`, one entry per script (`script`, `verdict`, `findings`, and `errors`
for the parts that could not be read) and a `summary` counting the verdicts. Each finding
carries `code`, `severity`, `statement` (numbered from 0), `message`, `snippet` and
`allowed`. For the script above (the third finding left out):

```json
{
  "success": false,
  "error": null,
  "dialect": "postgresql",
  "scripts": [
    {
      "script": "V2__drop_legacy.sql",
      "verdict": "UNSAFE",
      "findings": [
        {
          "code": "drop-column",
          "severity": "error",
          "statement": 0,
          "message": "DROP COLUMN discards a column of users",
          "snippet": "ALTER TABLE users DROP COLUMN legacy_flag;",
          "allowed": false
        },
        {
          "code": "pg-missing-lock-timeout",
          "severity": "warning",
          "statement": 0,
          "message": "takes a table lock with no lock_timeout set earlier in the script, so queries on the table can queue behind it; start with SET LOCAL lock_timeout = '5s'",
          "snippet": "ALTER TABLE users DROP COLUMN legacy_flag;",
          "allowed": false
        }
      ],
      "errors": []
    }
  ],
  "summary": {
    "SAFE": 0,
    "REVIEW": 0,
    "UNSAFE": 1
  }
}
```

**In CI.** Check only the migrations a pull request adds or changes:

```bash
dblift validate-sql --dialect postgresql --files $(git diff --name-only origin/main -- 'migrations/V*.sql')
```

`--files` needs at least one path, and a deleted file counts as missing: skip the step when
the diff is empty, or add `--diff-filter=d` to `git diff` to leave deleted files out.

`migrate --dry-run` shows the same verdict next to each pending script, with the findings
not allowed, without changing its exit code.

### Rolling Back Changes

If you need to undo a migration:

**Step 1: Create an undo migration**

For each versioned migration `V1_0_1__add_email_column.sql`, create a matching undo file `U1_0_1__remove_email_column.sql`:

```sql
-- U1_0_1__remove_email_column.sql
ALTER TABLE users DROP COLUMN email;
```

**Step 2: Run the rollback**
```bash
dblift undo --target-version=1.0.0
```

This will undo all migrations after version 1.0.0.

**Migrations written as one group:** if several migrations carry the same
`dblift-group-...`-prefixed tag (see [Using Tags](#using-tags)) -- for
example because a tool generated them together as one logical change split
across several files -- `dblift undo` treats them as a single unit. A plain
`dblift undo` with no `--target-version` reverts every applied migration in
that group, highest version first, instead of stopping after just the most
recent one; `--target-version` does the same when the target version would
otherwise land in the middle of a group, widening the rollback to cover the
whole group rather than leaving part of it applied.

### Working with Existing Databases

Already have a database with tables? Use baseline to tell DBLift where to start:

**Step 1: Check what DBLift sees:**
```bash
dblift info
```

**Step 2: Set a baseline version:**
```bash
dblift baseline --baseline-version=1.0.0 --baseline-description="Existing production database"
```

This tells DBLift: "Everything up to version 1.0.0 is already in the database, skip those migrations."

**Step 3: Apply new migrations:**
```bash
dblift migrate
```

Now only migrations after version 1.0.0 will be applied.

## Everyday Commands

Here are the commands you'll use most often:

| Command | What it does | When to use it |
|---------|--------------|----------------|
| `dblift info` | Shows status of all migrations | Check what's applied and what's pending |
| `dblift migrate` | Applies pending migrations | Deploy database changes |
| `dblift migrate --dry-run` | Preview without applying | Check what will happen before doing it |
| `dblift undo --target-version=X` | Rolls back to a specific version | Reverse recent changes |
| `dblift validate` | Checks migration history and metadata consistency | Before applying changes |
| `dblift validate-sql` | Checks migration SQL for destructive, breaking or locking statements, without connecting | Before merging a new migration |
| `dblift baseline --baseline-version=X` | Mark migrations as already applied | Working with existing databases |

**Quick Examples:**

```bash
# The usual workflow
dblift info                    # See what's pending
dblift validate               # Check for errors
dblift migrate                # Apply changes

# Rolling back
dblift undo --target-version=1.0.0

# Working with existing databases
dblift baseline --baseline-version=2.0.0
```

## Organizing Your Migrations

### Basic Structure

```
my-project/
├── dblift.yaml              # Configuration file
└── migrations/              # Your migration files
    ├── V1_0_0__create_users.sql
    ├── V1_0_1__add_orders.sql
    └── V1_0_2__add_products.sql
```

!!! note "Document stores use `.py` migrations"
    Azure Cosmos DB and MongoDB have no SQL DDL surface, so their migrations
    are Python scripts (`V1_0_0__create_users.py`) that drive the vendor SDK.
    A `.sql` migration aimed at either target fails with `DBLIFT-NOSQL-001`.
    Everything in this page — ordering, tags, `--dry-run`, undo, multiple
    directories — applies unchanged. See
    [NoSQL Python migrations](nosql-python-migrations.md).

### Multi-Module Projects

For larger projects, you can organize migrations by feature or module:

```
my-project/
├── dblift.yaml
├── core/
│   └── migrations/
│       ├── V1_0_0__core_tables.sql
│       └── V1_0_1__core_functions.sql
├── auth/
│   └── migrations/
│       └── V2_0_0__auth_tables.sql
└── billing/
    └── migrations/
        └── V3_0_0__billing_tables.sql
```

Then in your `dblift.yaml`:
```yaml
migrations:
  directories:
    - ./core/migrations
    - ./auth/migrations
    - ./billing/migrations
```

**Per-Directory Recursive Settings:**

You can control whether each directory is searched recursively:

```yaml
migrations:
  directories:
    - path: ./core/migrations
      recursive: true    # Search subdirectories
    - path: ./auth/migrations
      recursive: false   # Only top-level files
    - path: ./billing/migrations
      recursive: true    # Search subdirectories
  recursive: true  # Global default (used if recursive not specified per directory)
```

This is useful when some directories have a flat structure (no subdirectories needed) while others are organized in subdirectories.

!!! note "Recursive scan is ON by default"
    DBLift scans subdirectories recursively by default — even without `--recursive`. To disable, pass `--no-recursive` on the CLI or set `recursive: false` in your config. The CLI flag overrides the config value.

    ```bash
    dblift migrate --no-recursive   # top-level only
    dblift migrate --recursive      # explicit (same as default)
    ```

### Using Tags

Add tags to migration filenames to group related changes:

```
V1_0_0__create_users[core,init].sql
V1_0_1__create_auth[core,auth].sql
V2_0_0__add_billing[billing].sql
```

Deploy specific modules:
```bash
# Deploy only auth-related migrations
dblift migrate --tags=auth

# Deploy everything except billing
dblift migrate --exclude-tags=billing
```

## Advanced Commands

### Repairing Migration History

If your migration history table gets corrupted or out of sync:

**Check for issues:**
```bash
dblift validate
```

**Repair the history table:**
```bash
dblift repair
```

This will:
- Remove failed migration entries from the history table
- Mark history entries for missing script files as deleted
- Recalculate and update checksums for applied migrations whose script content
  has changed since it was applied
- Ensure history reflects what scripts are actually present

### Using Migration Placeholders

Migration placeholders are replaced when DBLift executes migration scripts:

```bash
dblift migrate --placeholders "TABLE_NAME=ph_test,LABEL_VALUE=hello"
dblift migrate --placeholders TABLE_NAME=ph_test LABEL_VALUE=hello
```

Use comma-separated values in a single shell argument, or pass multiple `key=value` tokens after `--placeholders`.

### Importing from Flyway

Migrating from Flyway to DBLift? Import your existing migration history:

```bash
dblift import-flyway
```

This imports records from Flyway's `flyway_schema_history` table into DBLift's history table.
The default Flyway source table name is `flyway_schema_history` for every database.
If your Flyway installation uses a different source table, pass `--flyway-table`:

```bash
dblift import-flyway --flyway-table custom_flyway_history
```

Use `--table` only to choose the target DBLift history table:

```bash
dblift import-flyway --flyway-table custom_flyway_history --table dblift_schema_history
```

### Database Utilities

**List available drivers:**
```bash
dblift db list-drivers
```

**Check database connection:**
```bash
dblift db check-connection
```

**Validate configuration:**
```bash
dblift db validate-config
```

**Diagnose connection issues:**
```bash
dblift db diagnose-connection
```

## Quick Reference Card

```bash
# Setup
dblift --version                                    # Check installation

# Daily workflow
dblift info                                         # Check status
dblift validate                                     # Validate migrations
dblift migrate                                      # Apply changes
dblift migrate --dry-run                           # Preview changes
dblift validate-sql                                 # Check migration SQL offline

# Working with existing databases
dblift baseline --baseline-version=1.0.0           # Set starting point

# Rollback
dblift undo --target-version=1.0.0                 # Roll back to version

# Organization
dblift migrate --tags=core                         # Apply tagged migrations
dblift migrate --scripts=./migrations/core --scripts=./migrations/features  # Multiple directories
dblift info --scripts=./custom/migrations          # Use different directory

# Coding agents
dblift mcp                                          # Serve read-only commands as MCP tools (pip install "dblift[mcp]")
dblift mcp --tools info,validate,migrate_dry_run    # Serve an allowlist only
dblift mcp --resources history                      # Serve an allowlist of resources
dblift mcp --offline                                # Refuse every tool and resource that would connect
dblift mcp --mode review                            # Review session: writers withheld, instructions say so
```

See **[Coding agents (MCP)](mcp.md)** for the tool list and the client setup.

## Next Steps

- Learn about **[Best Practices](best-practices.md)** for effective migrations
- Check out **[Troubleshooting](troubleshooting.md)** if you encounter issues
- See the **[API Reference](../api-reference/cli.md)** for complete command documentation
