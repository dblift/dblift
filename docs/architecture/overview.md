# Architecture Overview

**Technical Reference for Developers**

This document describes the current architecture of DBLift - a database migration tool supporting PostgreSQL, MySQL, SQL Server, Oracle, DB2, SQLite, and Azure Cosmos DB. It focuses on how the system is structured today and how components interact.

## System Overview

### High-Level Architecture

DBLift follows a layered architecture where each layer has clear responsibilities:

```
┌─────────────────────────────────────────────────────────┐
│                     CLI Layer                           │
│                  (cli/main.py)                          │
│  - Argument parsing                                     │
│  - Command routing                                      │
│  - Output formatting                                    │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                  API Client Layer                       │
│                  (api/client.py)                        │
│  - DBLiftClient: High-level operations API              │
│  - Configuration loading                                │
│  - Provider instantiation                               │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                 Migration Engine                        │
│            (core/migration/executor/)                   │
│  - MigrationExecutor: Orchestrates operations           │
│  - Commands: migrate, undo, baseline, validate, etc.    │
│  - State management                                     │
│  - Script management                                    │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│             Database Provider Layer                     │
│                 (db/plugins/)                           │
│  - BaseProvider: Abstract interface                     │
│  - 5 components per database:                           │
│    • ConnectionManager                                  │
│    • QueryExecutor                                      │
│    • SchemaOperations                                   │
│    • LockingManager                                     │
│    • HistoryManager                                     │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              Database Layer                             │
│  SQLAlchemy: PostgreSQL, MySQL, SQL Server, Oracle, DB2 │
│  Native: SQLite (Python sqlite3)                        │
│  SDK:  Azure Cosmos DB                                  │
└─────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Explicit Ownership**: Provider owns connection, passes it to components as parameters
2. **Stateless Components**: QueryExecutor, SchemaOperations, etc. store no connection state
3. **Dependency Injection**: Dependencies passed explicitly through call chain
4. **Database Abstraction**: Common interface for all database types
5. **Factory Pattern**: Centralized creation of dialect-specific components
6. **Public Package**: All bundled commands run without product-tier gates

## Layer Architecture

### Layer Responsibilities

| Layer | Location | Purpose | Key Components |
|-------|----------|---------|----------------|
| **CLI** | `cli/` | User interaction, command parsing | `main.py`, command handlers |
| **API Client** | `api/` | Public API, configuration, provider setup | `DBLiftClient` |
| **Migration Engine** | `core/migration/` | Migration orchestration | `MigrationExecutor`, Commands |
| **Database Providers** | `db/plugins/` | Database-specific operations | Provider implementations |
| **SQL Parsing** | `core/sql_parser/` | SQL dialect parsing | Parser implementations |
| **Configuration** | `config/` | Settings management | `DbliftConfig` |

### Data Flow

**Example: Running a Migration**

```
1. User runs: dblift migrate

2. CLI Layer (cli/main.py)
   - Parses "migrate" command and options
   - Calls: DBLiftClient(config).migrate()

3. API Client Layer (api/client.py)
   - Loads configuration from file/env/args
   - Creates Provider instance
   - Creates MigrationExecutor
   - Calls: executor.migrate()

4. Migration Engine (core/migration/executor/)
   - MigrateCommand.execute()
   - Loads scripts via ScriptManager
   - Computes state via StateManager
   - Gets connection from Provider
   - Executes SQL statements
   - Records in history table

5. Database Provider Layer (db/plugins/postgresql/)
   - Provider.begin_transaction()
   - QueryExecutor.execute(connection, sql)
   - HistoryManager.record_migration(connection, ...)
   - Provider.commit_transaction()

6. Database Layer
   - Native driver connection executes SQL
   - Returns results
```

## API Client Layer

**Location**: `api/client.py`

The `DBLiftClient` class provides the main programmatic API for DBLift operations.

### Core Structure

```python
class DBLiftClient:
    def __init__(self, config: DbliftConfig):
        self.config = config
        self.provider = self._create_provider()
        self.executor = MigrationExecutor(
            config=config,
            provider=self.provider,
            log=self.log
        )

    # Public API Methods
    def migrate(self, **options) -> MigrationResult
    def undo(self, **options) -> MigrationResult
    def baseline(self, **options) -> BaselineResult
    def info(self, **options) -> InfoResult
    def validate(self, **options) -> ValidationResult
    def clean(self, **options) -> CleanResult
    def repair(self, **options) -> RepairResult
    def export_schema(self, **options) -> ExportResult
    def snapshot(self, **options) -> SnapshotResult
```

### Key Responsibilities

1. **Configuration Management**: Load and merge config from multiple sources
2. **Provider Creation**: Instantiate correct database provider
3. **Executor Setup**: Create MigrationExecutor with dependencies
4. **Command Delegation**: Route commands to appropriate handlers
5. **Result Formatting**: Convert internal results to API responses

### Usage Example

```python
from api.client import DBLiftClient
from config.config import DbliftConfig

# Load configuration
config = DbliftConfig.from_file("dblift.yaml")

# Create client
client = DBLiftClient(config)

# Execute operations
result = client.migrate()
if result.success:
    print(f"Applied {result.migrations_applied} migrations")
else:
    print(f"Error: {result.error_message}")
```

## Related Documentation

- **[Migration Engine](migration-engine.md)** - How migrations are executed
- **[Database Providers](database-providers.md)** - Provider system architecture
- **[SQL Parsing](sql-parsing.md)** - SQL parsing and analysis
- **[Configuration](configuration.md)** - Configuration system details
- **[Licensing](licensing.md)** - License validation and enforcement
