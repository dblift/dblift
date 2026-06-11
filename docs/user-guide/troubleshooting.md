# Troubleshooting

Common issues and their solutions.

## "Migration already applied" Error

**Problem**: You see an error saying a migration was already applied.

**Solution**: Check which migrations are applied:
```bash
dblift info
```

If you see the migration listed as applied, it's already been run. If you need to make changes, create a new migration instead.

!!! tip "Prevention"
    Always check `dblift info` before creating new migrations to avoid version conflicts.

## Can't Connect to Database

**Problem**: DBLift can't connect to your database.

**Solution**: 
1. Check your `dblift.yaml` file has the correct connection details
2. Verify your database is running
3. Test the connection with your database client first
4. Make sure your username and password are correct
5. Check firewall/network settings

**Diagnostic commands:**
```bash
dblift db check-connection
dblift db diagnose-connection
dblift db validate-config
```

## Wrong Migrations Applied

**Problem**: You applied migrations to the wrong database or need to undo changes.

**Solution**: Use the undo command:
```bash
# Roll back to a specific version
dblift undo --target-version=1.0.0
```

!!! note "Undo Migrations Required"
    You need undo migrations (`U*.sql` files) for this to work. See [Rolling Back Changes](commands.md#rolling-back-changes) for details.

## File Encoding or Special Character Issues

**Problem**: Special characters (é, ñ, ö, etc.) in your SQL files aren't working.

**Solution**: Add encoding to your `dblift.yaml`:
```yaml
migrations:
  script_encoding: "utf-8"
```

DBLift reads migration files strictly with `script_encoding` by default. For legacy files where the encoding is mixed or unknown, enable detection:

```yaml
migrations:
  script_encoding: "utf-8"
  detect_encoding: true
```

If detection or decoding fails, DBLift stops with an encoding error so accented characters are not silently corrupted.

## Migration Out of Order

**Problem**: Someone created a migration with an older version number than what's already applied.

**Solution**: 
1. Rename the migration file with a newer version number
2. Or use `--mark-as-executed` if you need to skip it:
```bash
dblift migrate --mark-as-executed --versions=1.0.5
```

!!! warning "Use with Caution"
    Only use `--mark-as-executed` if you're certain the migration's changes are already in the database.

## Want to Start Fresh

**Problem**: You want to remove all migrations and start over.

**Solution**: Use the clean command (⚠️ **Warning: This deletes all managed objects!**):
```bash
dblift clean --dry-run  # Preview first
dblift clean --clean-enabled  # Actually clean
```

!!! danger "Destructive Operation"
    The `clean` command is disabled by default. `--clean-enabled` is required for destructive execution. Use only in development or when you're certain you want to start fresh.

## Migration History Corrupted

**Problem**: Migration history table is out of sync or corrupted.

**Solution**: Use the repair command:
```bash
dblift validate  # Check for issues
dblift repair    # Fix inconsistencies
```

The repair command will:
- Recalculate checksums for applied migrations
- Fix any inconsistencies in the history table
- Ensure history matches migration files

## Failed Migration Recovery

**Problem**: A migration failed and the database/history state may not match what automation expected.

**Solution**:
1. Run `dblift info` and inspect the failed migration row.
2. Review the command log. Failed migrate results expose whether the failed row was persisted with `failed_history_persisted`.
3. If `failed_history_persisted` is `false`, use database logs plus the DBLift command log as the source of truth because the history table may not contain the failure.
4. On databases without transactional DDL, inspect partially created/altered objects manually before retrying.
5. Run `dblift repair` only after deciding whether the failed row or missing row should be reconciled.

## Migration Journal and Audit Evidence

**Problem**: You expected a durable per-statement journal file after a crash.

**Explanation**: DBLift's `MigrationJournal` is in-memory only. It is used to enrich command results and log reports during a process, but `journal_dir` is intentionally ignored and no separate statement-journal file is written.

**Recommended evidence to retain**:
- DBLift text/JSON/HTML command logs.
- The `dblift_schema_history` table.
- Database-native audit/error logs for the migration window.
- CI job logs and artifact bundles for release/customer runs.

## Stuck Migration Lock

**Problem**: A migration reports that another migration may be running.

**Solution**:
1. Confirm no active DBLift process is still running.
2. Check database-native locks first: PostgreSQL advisory locks, SQL Server application locks, MySQL named locks, Oracle/DB2 lock mechanisms, or CosmosDB lock documents.
3. For table-based fallback locks, inspect the `dblift_migration_lock` table in the target schema and remove only rows whose owning process/session is confirmed dead.
4. Re-run `dblift info` before retrying `dblift migrate`.

## SQL Syntax Errors

**Problem**: Migrations fail with SQL syntax errors.

**Solution**: 
1. Validate migrations before applying:
```bash
dblift validate
```

2. Check your SQL against the database dialect documentation
3. Test SQL directly in your database client first
4. Ensure you're using the correct SQL dialect for your database

## SQL Server: Full-text Catalog and Index Fail in Transactional Migration

**Problem**: A SQL Server migration containing `CREATE FULLTEXT CATALOG` or `CREATE FULLTEXT INDEX` fails with:

```
Error: Migration V1__create_schema.sql mixes transactional and autocommit-on SQL
```

**Cause**: Full-text DDL requires autocommit mode in SQL Server and cannot share a transaction with standard DDL statements.

**Fix**: Move full-text catalog/index creation into its own migration file:

```
V1__create_tables.sql          ← standard DDL (transactional)
V2__create_fulltext_index.sql  ← FULLTEXT DDL only (autocommit)
```

## Slow Migration Execution

**Problem**: Migrations are taking too long to execute.

**Possible causes and solutions**:
- **Large data migrations**: Consider breaking into smaller batches
- **Missing indexes**: Add indexes before large data operations
- **Lock contention**: Check for blocking queries
- **Network issues**: Verify database connection quality

Use `dblift info` to see execution times for each migration.

## Driver Issues

**Problem**: Can't find or load the database driver.

**Solution**:
1. Install the matching Python driver extra, for example `dblift[postgresql]`, `dblift[mysql]`, `dblift[oracle]`, `dblift[sqlserver]`, or `dblift[db2]`
2. Verify the Python package can be imported in the same environment, using the relevant package name:
   ```bash
   python -c "import psycopg"
   ```

3. Verify driver compatibility with your database version
4. Re-run `dblift db check-connection`

## CosmosDB Connection Issues

**Problem**: Can't connect to Azure Cosmos DB.

**Solution**:
1. Verify account endpoint is correct
2. Check account key or managed identity configuration
3. For local emulator, ensure it's running on port 8081
4. Verify network/firewall allows connections
5. Check Azure portal for account status

## SQLite Path Issues

**Problem**: SQLite can't find the database file.

**Solution**:
- Use absolute paths: `/path/to/database.db`
- Or relative paths from the working directory
- Ensure the directory exists
- Check file permissions

## Multiple Migration Directories Not Working

**Problem**: Migrations from multiple directories aren't being found.

**Solution**:
1. Verify `dblift.yaml` configuration:
```yaml
migrations:
  directories:
    - ./migrations/core
    - ./migrations/features
```

2. Check directory paths are correct (relative to `dblift.yaml` location)
3. Verify `recursive` settings if using subdirectories
4. Run `dblift info` to see which migrations are detected

## Tags Not Working

**Problem**: Tagged migrations aren't being filtered correctly.

**Solution**:
1. Verify tag syntax in filename: `V1_0_0__migration[tag1,tag2].sql`
2. Check tag names match exactly (case-sensitive)
3. Use comma-separated tags: `--tags=tag1,tag2`
4. Verify tags are in square brackets `[]` after the description

## Still Having Issues?

If you're still experiencing problems:

1. **Check the logs**: Look for detailed error messages
2. **Validate configuration**: Run `dblift db validate-config`
3. **Diagnose connection**: Run `dblift db check-connection` and `dblift db diagnose-connection`
4. **Review documentation**: Check the [Commands Reference](commands.md) and [Configuration Guide](configuration.md)
5. **Open an issue**: [GitHub Issues](https://github.com/cmodiano/dblift/issues)

## Diagnostic Commands

Use these commands to gather information:

```bash
# Check configuration
dblift db validate-config

# Test connection
dblift db check-connection

# Diagnose connection issues
dblift db diagnose-connection

# List available drivers
dblift db list-drivers

# Check migration status
dblift info

# Validate migrations
dblift validate
```

## Next Steps

- Review the **[Commands Reference](commands.md)** for all available options
- Check **[Best Practices](best-practices.md)** to prevent common issues
- See **[Configuration Guide](configuration.md)** for setup options
