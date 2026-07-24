# Best Practices

Follow these guidelines to make your database migrations effective, maintainable, and safe.

## 1. Always Preview Before Applying

Use `--dry-run` to see what will happen:
```bash
dblift migrate --dry-run
```

This helps you:
- Understand what changes will be made
- Catch potential issues before they happen
- Verify migrations are in the correct order

## 2. Version Numbers Matter

Use a consistent versioning scheme:
- **Major.Minor.Patch**: `V1_0_0`, `V1_0_1`, `V1_1_0`, `V2_0_0`
- Increment patch for small changes
- Increment minor for new features
- Increment major for breaking changes

!!! tip "Versioning Strategy"
    Consider using semantic versioning aligned with your application version numbers for easier tracking.

## 3. Make Migrations Reversible

For every migration, consider creating an undo migration:
```
V1_0_1__add_email_column.sql
U1_0_1__remove_email_column.sql
```

Benefits:
- Easy rollback when needed
- Safer deployments
- Better testing capabilities

## 4. Keep Migrations Small

One change per migration makes them easier to:
- Understand
- Review
- Roll back if needed
- Debug when something goes wrong

!!! warning "Avoid Large Migrations"
    Large migrations are harder to debug and rollback. If you need to make multiple changes, create separate migration files.

## 5. Test in Development First

Always test migrations on a development database before production. Declare
both targets once in `dblift.yaml` under `environments:` and switch with
`--env` instead of maintaining one config file per environment:

```bash
# On dev database
dblift info --env dev
dblift migrate --dry-run --env dev
dblift migrate --env dev

# Verify everything works, then apply to production
dblift migrate --env prod
```

See [Configuration → Environments](configuration.md#environments) for the
`environments:` block, selection precedence, and branch mapping.

## 6. Use Descriptive Names

Good migration names tell you what they do:
- ✅ `V1_0_1__add_user_email_column.sql`
- ✅ `V1_0_2__create_orders_table.sql`
- ❌ `V1_0_1__changes.sql`
- ❌ `V1_0_2__updates.sql`

The description after `__` should clearly describe the change.

## 7. Don't Modify Applied Migrations

Once a migration has been applied to any database (especially production), never change it. Instead:
- Create a new migration to fix issues
- Keep the history intact
- Maintain audit trail

!!! danger "Critical Rule"
    Modifying applied migrations can cause inconsistencies and break your migration history. Always create new migrations for fixes.

## 8. Use Transactions When Possible

Most databases support transactions. DBLift automatically wraps migrations in transactions when supported, ensuring:
- All-or-nothing execution
- Automatic rollback on errors
- Consistent database state

## 9. Validate Before Deploying

Always validate migrations before applying:
```bash
dblift validate
```

This catches:
- Syntax errors
- Migration conflicts
- Versioning issues

## 10. Organize by Feature or Module

For larger projects, organize migrations by feature:
```
migrations/
├── core/
│   ├── V1_0_0__core_tables.sql
│   └── V1_0_1__core_functions.sql
├── auth/
│   └── V2_0_0__auth_tables.sql
└── billing/
    └── V3_0_0__billing_tables.sql
```

Use tags to group related migrations:
```
V1_0_0__create_users[core,init].sql
V1_0_1__create_auth[core,auth].sql
```

## 11. Document Complex Changes

Add comments in your SQL files explaining:
- Why the change is needed
- Business logic behind the change
- Dependencies on other migrations

```sql
-- This migration adds email verification support
-- Required for user authentication feature (see V1_5_0)
-- Depends on: V1_0_0__create_users_table.sql
ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE;
```

## 12. Handle Data Migrations Carefully

Data migrations require special attention:
- Test with production-like data volumes
- Consider performance impact
- Plan for downtime if needed
- Have a rollback strategy

## 13. Use Environment Variables for Secrets

Never commit passwords or sensitive credentials:
```bash
export DBLIFT_DB_PASSWORD="your-secure-password"
```

Use environment variables or secret management systems in production.

## 14. Monitor Migration Execution

Check migration status regularly:
```bash
dblift info
```

Look for:
- Failed migrations
- Long execution times
- Unexpected states

## 15. Keep Migration History Clean

Use `dblift repair` if you notice inconsistencies:
```bash
dblift validate  # Check for issues
dblift repair    # Fix inconsistencies
```

## Summary

Following these best practices will help you:
- ✅ Maintain a clean migration history
- ✅ Deploy changes safely
- ✅ Recover from issues quickly
- ✅ Work effectively in teams
- ✅ Scale your database changes

## Next Steps

- Review the **[Commands Reference](commands.md)** for all available options
- Check **[Troubleshooting](troubleshooting.md)** for common issues
- See **[Configuration Guide](configuration.md)** for setup options
