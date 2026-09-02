# CLI Reference

Command-line interface documentation.

::: dblift.cli.main
    options:
      show_root_heading: true
      show_source: true

## Commands

All CLI commands are documented in the [User Guide Commands](../user-guide/commands.md).

For detailed API documentation of command implementations, see:

- `dblift.cli.handlers.migrate` - Migration execution
- `dblift.cli.handlers.undo` - Rollback operations
- `dblift.cli.handlers.baseline` - Baseline management
- `dblift.cli.handlers.info` - Status information
- `dblift.cli.handlers.validate` - Validation operations
- `dblift.cli.handlers.clean` - Clean operations
- `dblift.cli.handlers.repair` - History repair
- `dblift.cli.handlers.import_flyway` - Flyway history import
- `dblift.cli._command_handlers` - Command dispatch

Additional handlers may be registered by installed add-ons through the CLI entry-point groups documented in the developer guide.
