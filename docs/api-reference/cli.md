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

Additional handlers may be registered by installed add-ons through the CLI entry-point groups documented in the developer guide.
