# Core Modules Reference

Core modules for migration execution, SQL parsing, and schema management.

## Migration Engine

The migration engine orchestrates all database migration operations.

::: dblift.core.migration.executor.migration_executor.MigrationExecutor
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

::: dblift.core.migration.commands.migrate_command.MigrateCommand
    options:
      show_root_heading: true
      show_source: true

::: dblift.core.migration.commands.undo_command.UndoCommand
    options:
      show_root_heading: true
      show_source: true

::: dblift.core.migration.commands.baseline_command.BaselineCommand
    options:
      show_root_heading: true
      show_source: true

::: dblift.core.migration.commands.info_command.InfoCommand
    options:
      show_root_heading: true
      show_source: true

::: dblift.core.migration.commands.validate_command.ValidateCommand
    options:
      show_root_heading: true
      show_source: true

## State Management

Manages migration state and determines which migrations need to run.

::: dblift.core.migration.state.migration_state_manager.MigrationStateManager
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

::: dblift.core.migration.scripting.migration_script_manager.MigrationScriptManager
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

Migration execution and undo generation use the stateless
`dblift.core.migration.sql.migration_sql_parser.parse_migration_sql` helper.
`Migration.parse_sql_statements(dialect=None, content_override=None)` remains a
deprecated compatibility API throughout 4.x; its removal is planned for a future
major version. Calls without an override recompute and store canonical statements.
Overrides, including an empty string, leave that cache untouched.

Script preprocessing can use the same comment-only check as migration execution:

```python
# Previously, callers had to reach into ExecutionEngine._is_comment_only_statement.
from dblift.core.migration.sql import is_comment_only_statement

is_comment_only_statement("-- documentation only")  # True
is_comment_only_statement("/*!40014 SET FOREIGN_KEY_CHECKS=0 */")  # False
```

This provider-free helper preserves the executor's existing behavior, including
MySQL/MariaDB executable comment directives. Existing executor callers remain
compatible; ordinary migration behavior is unchanged.

::: dblift.core.sql_parser
    options:
      show_root_heading: true
      show_source: true

**Capabilities**:
- Splits SQL into statements
- Handles dialect-specific syntax
- Processes comments
- Supports multiple SQL dialects

See `core/sql_parser/` for implementation details.

**Features**:
- Generates CREATE/ALTER/DROP statements
- Database-specific SQL generation
- Dependency ordering
- Safety checks

## Related Documentation

- [Migration Engine Architecture](../architecture/migration-engine.md)
- [Database Providers](db.md)
- [API Client](api.md)
