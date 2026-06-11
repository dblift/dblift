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

### Validating Migrations

Validate migration scripts before applying them:

```bash
dblift validate
```

This checks migration metadata and script consistency against the configured
database without applying pending migrations.

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
