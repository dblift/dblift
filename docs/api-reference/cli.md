# CLI Reference

Command-line interface documentation.

::: cli.main
    options:
      show_root_heading: true
      show_source: true

## Commands

All CLI commands are documented in the [User Guide Commands](../user-guide/commands.md).

For detailed API documentation of command implementations, see:

- `cli.handlers.migrate` - Migration execution
- `cli.handlers.undo` - Rollback operations
- `cli.handlers.baseline` - Baseline management
- `cli.handlers.info` - Status information
- `cli.handlers.validate` - Validation operations
- `cli.handlers.clean` - Clean operations
- `cli.handlers.repair` - History repair
- `cli.handlers.import_flyway` - Flyway history import
- `cli._command_handlers` - Command dispatch
- `dblift_pro.handlers.diff` - Schema comparison (PRO)
- `dblift_pro.handlers.export_schema` - Schema export (PRO)
- `dblift_pro.handlers.validate_sql` - SQL validation (PRO)
- `dblift_enterprise.handlers.plan` - Offline migration plans (ENTERPRISE)
- `dblift_enterprise.handlers.preflight` - Deployment preflight (ENTERPRISE)
- `dblift_enterprise.handlers.snapshot` - Schema snapshots (ENTERPRISE)
