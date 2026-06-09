# Commands Reference

This guide covers all DBLift commands and their usage.

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

### Exporting Existing Schema

If you have an existing database and want to create migration files from it:

**Export entire schema from live database (default):**
```bash
dblift export-schema --output migrations/V1__baseline.sql
```

**Export schema from database stored snapshot:**
```bash
dblift export-schema --source=database-model --output migrations/V1__baseline.sql
```

**Export schema from a JSON model file:**
```bash
dblift export-schema --source=file-model --snapshot-model snapshots/schema.json --output migrations/V1__baseline.sql
```

**Export only specific object types:**
```bash
dblift export-schema --types tables,views,functions --output migrations/schema.sql
```

**Export only managed objects (objects defined in migrations):**
```bash
dblift export-schema --managed-only --output migrations/managed.sql
```

**Export only unmanaged objects (brownfield baseline):**
```bash
dblift export-schema --unmanaged-only --output migrations/unmanaged.sql
```

**Export with filtering by migration tags/versions:**
```bash
dblift export-schema --managed-only --tags feature1,feature2 --output migrations/feature.sql
dblift export-schema --managed-only --target-version=1.5.0 --output migrations/up_to_1_5.sql
```

**Split output by object type:**
```bash
dblift export-schema --split-by-type --output-dir migrations/baseline/
```

This creates separate files for tables, views, functions, etc.

### Exporting Schema Snapshots

**Export snapshot from database (latest stored snapshot):**
```bash
dblift snapshot --output snapshots/public_schema.json
```

**Export snapshot from live database (capture new snapshot):**
```bash
dblift snapshot --source=live-database --output snapshots/public_schema.json
```

!!! note "CosmosDB supports database-stored snapshots"
    As of v1.6.0, CosmosDB captures snapshots automatically during `migrate` (stored in `dblift_schema_snapshots`). Use `--source database-stored` to retrieve them, same as other dialects.

## Everyday Commands

Here are the commands you'll use most often:

| Command | What it does | When to use it |
|---------|--------------|----------------|
| `dblift info` | Shows status of all migrations | Check what's applied and what's pending |
| `dblift migrate` | Applies pending migrations | Deploy database changes |
| `dblift migrate --dry-run` | Preview without applying | Check what will happen before doing it |
| `dblift undo --target-version=X` | Rolls back to a specific version | Reverse recent changes |
| `dblift validate` | Checks migration history and metadata consistency | Before applying changes |
| `dblift plan --snapshot-model=FILE` | Computes pending migrations from a snapshot without DB access | CI checks for environment branches |
| `dblift export-schema` | Exports schema to SQL files from live database, database model, or file model | Capture an existing database as migrations |
| `dblift snapshot` | Exports schema snapshot to JSON model file from database or live database | Create snapshot for diff comparisons |
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

# Export schema from live database to SQL
dblift export-schema --output migrations/schema.sql

# Export schema from database stored snapshot to SQL
dblift export-schema --source=database-model --output migrations/schema.sql

# Export schema snapshot to JSON model file
dblift snapshot --output snapshots/public_schema.json

# Capture a new snapshot from live database
dblift snapshot --source=live-database --output snapshots/public_schema.json
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

### Comparing Database State (diff)

Compare your current database state with what migrations define, or compare migrations against stored snapshots:

**Compare live database with migrations:**
```bash
dblift diff
```

This will show any drift between your database and what your migrations should have created.

**Compare database-stored snapshot with migrations:**
```bash
dblift diff --source=database-model
```

**Compare file-stored snapshot with migrations:**
```bash
dblift diff --source=file-model --snapshot-model=snapshots/prod.json
```

**Ignore unmanaged objects in comparison:**
```bash
dblift diff --ignore-unmanaged
```

**Compare only up to specific version:**
```bash
dblift diff --target-version=1.5.0
```

**Generate SQL from diffs (diff-to-SQL):**

The `diff` command can generate SQL scripts to synchronize schemas. For CosmosDB, operations requiring Azure SDK (like `DROP CONTAINER`) are automatically translated to SDK operations. Generated scripts include both SQL statements and Python SDK code for manual execution if needed.

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
- Ensure history reflects what scripts are actually present

!!! warning "Repair does not reconcile modified scripts"
    If you changed an already-applied script and the checksum no longer matches, `repair` will not fix it. Options:
    - If the migration was already undone: `clean` + `migrate` (restores history)
    - If the migration is still applied: update the checksum manually in the history table, or `clean` + `migrate`

### Using Migration Placeholders

Migration placeholders are replaced when DBLift executes migration scripts:

```bash
dblift migrate --placeholders "TABLE_NAME=ph_test,LABEL_VALUE=hello"
dblift migrate --placeholders TABLE_NAME=ph_test LABEL_VALUE=hello
```

Use comma-separated values in a single shell argument, or pass multiple `key=value` tokens after `--placeholders`.

### Validating SQL Syntax

Validate SQL syntax before applying migrations:

**Validate all migrations:**
```bash
dblift validate-sql
```

This checks SQL syntax against your target database dialect without executing it.
Use `--fail-on never|error|warning|info` to choose the minimum finding severity
that returns a non-zero exit code. The default is `error`.

```bash
dblift validate-sql migrations/ --format github-actions --fail-on error
dblift validate-sql migrations/ --format sarif --fail-on warning > validation.sarif
```

Generate an offline enterprise evidence report:

```bash
dblift validate-sql migrations/ \
  --profile enterprise \
  --fail-on warning \
  --format html \
  --output sql-validation-evidence.html
```

The HTML report is intended for release review and audit evidence. It includes
the checked files, failure threshold, findings, rule rationale, remediation
guidance, control mappings, and governed exception details when present.

Use built-in rule profiles when CI should apply DBLift-managed rule coverage
without a custom YAML rules file:

```bash
dblift validate-sql migrations/ --profile enterprise --format github-actions --fail-on warning
dblift validate-sql migrations/ --profile core --rules no_public_schema_access,require_primary_key
```

Available profiles are `core`, `enterprise`, `strict`, and `technical-debt`.
Use `--rules` to add rule packs or individual rules to a profile. Use
`--rules-file` only for a fully custom YAML rules file; it cannot be combined
with `--profile` or `--rules`.

### Planning from a Snapshot

Build a CI-safe deployment plan from a committed environment snapshot:

```bash
dblift plan --snapshot-model prod.snapshot.json --format json --fail-on error
```

`plan` uses the snapshot as the target environment state. It reports pending
versioned migrations, changed repeatables, checksum drift for already-applied
migrations when the snapshot contains checksums, and SQL validation for planned
SQL scripts. Pending migrations are warnings; checksum drift and SQL validation
failures are errors.

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

## License Management

DBLift requires a valid license key to run. The `license` subcommand manages your license without requiring an active license itself.

### Activate a License

```bash
dblift license activate <your-license-key>
```

Validates the key, then saves it to `~/.dblift/license.key` (mode 600). Output:

```
License activated successfully!

  Customer:  Jane Smith
  Email:     jane@example.com
  Issued:    2025-01-01
  Expires:   2026-01-01
  License:   lic_abc123
```

### Show License Information

```bash
dblift license info
```

Displays full details about the currently active license.

### Check License Validity

```bash
dblift license check
```

Prints a one-line status and exits 0 if valid, 1 if expired or missing:

```
License status: VALID (247 days remaining)
```

### Deactivate a License

```bash
dblift license deactivate
```

Removes the saved license file. dblift will require a new license to run after this.

### Supplying a License Without Activating

You can pass a license key directly on any command without saving it:

```bash
dblift --license-key <token> migrate
```

Or via environment variable:

```bash
export DBLIFT_LICENSE_KEY=<token>
dblift migrate
```

## Quick Reference Card

```bash
# Setup
dblift --version                                    # Check installation
dblift license activate <key>                       # Activate license (first-time setup)
dblift license check                                # Verify license status

# Daily workflow
dblift info                                         # Check status
dblift validate                                     # Validate migrations
dblift migrate                                      # Apply changes
dblift migrate --dry-run                           # Preview changes

# Working with existing databases
dblift baseline --baseline-version=1.0.0           # Set starting point

# Rollback
dblift undo --target-version=1.0.0                 # Roll back to version

# Organization
dblift migrate --tags=core                         # Apply tagged migrations
dblift migrate --scripts=./migrations/core --scripts=./migrations/features  # Multiple directories
dblift info --scripts=./custom/migrations          # Use different directory
```

## Next Steps

- Learn about **[Best Practices](best-practices.md)** for effective migrations
- Check out **[Troubleshooting](troubleshooting.md)** if you encounter issues
- See the **[API Reference](../api-reference/cli.md)** for complete command documentation
