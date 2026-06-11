# Core Modules Reference

Core modules for migration execution, SQL parsing, and schema management.

## Migration Engine

The migration engine orchestrates all database migration operations.

::: core.migration.executor.migration_executor.MigrationExecutor
    options:
      show_root_heading: true
      show_source: true
      show_signature_annotations: true

**Key Responsibilities**:
- Execute migrations in order
- Manage transaction lifecycle
- Track migration state
- Handle errors and rollbacks

## Commands

Command pattern implementation for all migration operations.

::: core.migration.commands.migrate_command.MigrateCommand
    options:
      show_root_heading: true
      show_source: true

::: core.migration.commands.undo_command.UndoCommand
    options:
      show_root_heading: true
      show_source: true

::: core.migration.commands.baseline_command.BaselineCommand
    options:
      show_root_heading: true
      show_source: true

::: core.migration.commands.info_command.InfoCommand
    options:
      show_root_heading: true
      show_source: true

::: core.migration.commands.validate_command.ValidateCommand
    options:
      show_root_heading: true
      show_source: true

## State Management

Manages migration state and determines which migrations need to run.

::: core.migration.state.migration_state_manager.MigrationStateManager
    options:
      show_root_heading: true
      show_source: true

**Key Features**:
- Computes pending/applied migrations
- Handles version conflicts
- Detects modified migrations
- Filters by tags and versions

## Script Management

Discovers and loads migration scripts from filesystem.

::: core.migration.scripting.migration_script_manager.MigrationScriptManager
    options:
      show_root_heading: true
      show_source: true

**Features**:
- Discovers migration files
- Parses migration metadata
- Supports multiple directories
- Recursive directory scanning

## SQL Parsing

Parses SQL scripts and extracts statements.

::: core.sql_parser
    options:
      show_root_heading: true
      show_source: true

**Capabilities**:
- Splits SQL into statements
- Handles dialect-specific syntax
- Processes comments
- Supports multiple SQL dialects

See `core/sql_parser/` for implementation details.

## SQL Generation

Generates SQL from schema model objects.

::: core.sql_generator.sql_generator.SqlGenerator
    options:
      show_root_heading: true
      show_source: true

**Features**:
- Generates CREATE/ALTER/DROP statements
- Database-specific SQL generation
- Dependency ordering
- Safety checks

## Related Documentation

- [Migration Engine Architecture](../architecture/migration-engine.md)
- [Database Providers](db.md)
- [API Client](api.md)
