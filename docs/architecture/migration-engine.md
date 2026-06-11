# Migration Engine

**Location**: `core/migration/executor/`

The migration engine orchestrates all database change operations.

## Core Components

### MigrationExecutor

Central orchestrator that manages the migration lifecycle.

**Location**: `core/migration/executor/migration_executor.py`

```python
class MigrationExecutor:
    def __init__(self, config, provider, log):
        self.config = config
        self.provider = provider
        self.log = log

        # Core managers
        self.script_manager = MigrationScriptManager(...)
        self.state_manager = MigrationStateManager(...)
        self.history_manager = provider.history_manager

    def migrate(self, **options) -> MigrationResult:
        """Execute pending migrations"""

    def undo(self, **options) -> MigrationResult:
        """Rollback migrations"""

    def baseline(self, **options) -> BaselineResult:
        """Mark migrations as already applied"""
```

**Key Responsibilities**:
- Load migration scripts
- Compute migration state (pending/applied)
- Execute commands through database provider
- Record results in history table
- Manage schema snapshots

## Command Pattern

All operations are implemented as Command classes:

**Location**: `core/migration/commands/`

```python
class BaseCommand(ABC):
    def __init__(self, provider, config, log):
        self.provider = provider
        self.config = config
        self.log = log

    @abstractmethod
    def execute(self, **options):
        pass

# Concrete implementations
class MigrateCommand(BaseCommand): ...
class UndoCommand(BaseCommand): ...
class BaselineCommand(BaseCommand): ...
class CleanCommand(BaseCommand): ...
class RepairCommand(BaseCommand): ...
class InfoCommand(BaseCommand): ...
class ValidateCommand(BaseCommand): ...
```

**Benefits**:
- Each operation has isolated logic
- Easy to test independently
- Clear separation of concerns
- Consistent interface

## State Management

**MigrationStateManager** computes what migrations need to run.

**Location**: `core/migration/state/migration_state_manager.py`

```python
class MigrationStateManager:
    def compute_migration_state(
        self,
        scripts: List[MigrationScript],
        history: List[HistoryRecord],
        filters: MigrationFilters
    ) -> MigrationState:
        """
        Determines:
        - Pending migrations (not yet applied)
        - Applied migrations (already run)
        - Failed migrations (errors during execution)
        - Missing migrations (applied but script deleted)
        - Modified migrations (checksum changed)
        """
```

## Script Management

**MigrationScriptManager** discovers and loads migration files.

**Location**: `core/migration/scripts/migration_script_manager.py`

```python
class MigrationScriptManager:
    def discover_scripts(
        self,
        directories: List[str],
        recursive: bool = False
    ) -> List[MigrationScript]:
        """
        Scans directories for migration files:
        - V<version>__<description>.sql  (versioned)
        - R__<description>.sql           (repeatable)
        - U<version>__<description>.sql  (undo)
        """

    def parse_script(self, path: str) -> MigrationScript:
        """Extract metadata from filename and content"""
```

**Migration File Naming**:
```
V1_0_0__create_users_table.sql
│││││││  │
││││││└──┴─ Description (spaces replaced with _)
│││││└───── Double underscore separator
││││└────── Patch version
│││└─────── Minor version
││└──────── Major version
│└───────── Version indicator
└────────── V = Versioned, R = Repeatable, U = Undo
```

## Execution Flow

### Migrate Command Flow

```
1. Load scripts from configured directories
2. Query history table for applied migrations
3. Compute state (pending/applied/failed)
4. Filter migrations (tags, versions, etc.)
5. For each pending migration:
   a. Acquire lock
   b. Begin transaction
   c. Execute SQL statements
   d. Record in history table
   e. Commit transaction
   f. Release lock
6. Return results
```

### Undo Command Flow

```
1. Load scripts and history
2. Find migrations to undo (after target version)
3. Find matching undo migrations (U*.sql files)
4. For each migration (in reverse order):
   a. Acquire lock
   b. Begin transaction
   c. Execute undo SQL
   d. Remove from history table
   e. Commit transaction
   f. Release lock
5. Return results
```

## Error Handling

- **Transaction Rollback**: Failed migrations automatically roll back
- **Lock Timeout**: Prevents deadlocks with configurable timeout
- **Checksum Validation**: Detects modified migration files
- **State Validation**: Ensures migration history consistency

## Related Documentation

- **[Architecture Overview](overview.md)** - System architecture
- **[Database Providers](database-providers.md)** - How providers execute migrations
- **[Configuration](configuration.md)** - Configuration options
