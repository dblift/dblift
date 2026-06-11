# API Reference

## DBLiftClient

The main client class for programmatic access to DBLift.

::: api.client.DBLiftClient
    options:
      show_root_heading: true
      show_source: true
      show_signature_annotations: true
      separate_signature: true

## Quick Start

```python
from api.client import DBLiftClient
from db.plugins.postgresql.provider import PostgreSqlJdbcProvider
from config import DbliftConfig

# Create provider
config = DbliftConfig.from_file("dblift.yaml")
provider = PostgreSqlJdbcProvider(config)

# Create client
client = DBLiftClient(
    provider=provider,
    migrations_dir="./migrations"
)

# Execute migrations
result = client.migrate()
if result.success:
    print(f"Applied {len(result.migrations_applied)} migrations")
```

## Factory Method

For convenience, use the factory method:

```python
from api.client import DBLiftClient
from config import DbliftConfig

# Load config and create client
config = DbliftConfig.from_file("dblift.yaml")
client = DBLiftClient.from_config_file("dblift.yaml")
```

## Main Methods

### migrate()

Apply pending migrations to the database.

```python
result = client.migrate(
    target_version="1.5.0",  # Optional: migrate to specific version
    dry_run=False,            # Preview without applying
    show_sql=False,           # Include migration SQL in outputs/reports
    tags="core,init",         # Filter by tags
    recursive=True            # Search subdirectories
)
```

### undo()

Rollback applied migrations.

```python
result = client.undo(
    target_version="1.0.0",  # Optional: roll back to specific version
    dry_run=True,             # Preview without applying
    show_sql=True             # Include matching undo SQL in outputs/reports
)
```

### info()

Get migration status information.

```python
result = client.info()
print(f"Current version: {result.current_schema_version}")
print(f"Applied migrations: {len(result.migrations_applied)}")
print(f"All migrations: {len(result.migrations)}")
```

!!! note "Stdout side effect"
    `client.info()` prints the migration table to stdout before returning. Redirect or suppress stdout if you need clean output in automation scripts.

### validate()

Validate migration scripts without executing them.

```python
result = client.validate()
if not result.success:
    print(f"Validation errors: {result.errors}")
```

### undo()

Rollback migrations to a specific version.

```python
result = client.undo(target_version="1.0.0")
```

### baseline()

Mark migrations as already applied (for existing databases).

```python
result = client.baseline(
    baseline_version="1.0.0",
    baseline_description="Existing production database"
)
```

## Event System

DBLiftClient supports events for IDE/tooling integration:

```python
from api.events import Event, EventType

def on_migration_started(event: Event) -> None:
    # event is a frozen Event dataclass — use attribute access
    print(f"Starting: {event.script} (dialect: {event.dialect})")

client.events.on(EventType.MIGRATION_STARTED, on_migration_started)
client.migrate()
```

!!! info "Events are typed dataclasses"
    As of 1.6.0, listener callbacks receive a frozen [`Event`][api.events.Event]
    dataclass instance — **not** a plain dict. Use attribute access
    (`event.script`, `event.dialect`, `event.result`); dict-style `event["key"]`
    raises `TypeError`. `event_type` and `timestamp` are always populated; every
    other field defaults to `None` and is set only when the emit site provides
    it. Unknown keyword arguments at emit time raise `TypeError` so emit sites
    cannot silently accumulate fields the dataclass does not declare. See the
    [Events reference](events.md) for the full field set and event-type enum.

Common event types — see [Events reference](events.md) for the complete enum:

- `MIGRATION_STARTED` / `MIGRATION_COMPLETED` / `MIGRATION_FAILED`
- `MIGRATION_SCRIPT_STARTED` / `MIGRATION_SCRIPT_COMPLETED` / `MIGRATION_SCRIPT_FAILED` / `MIGRATION_SCRIPT_SKIPPED`
- `INFO_STARTED` / `INFO_COMPLETED`
- `VALIDATION_STARTED` / `VALIDATION_COMPLETED` / `VALIDATION_FAILED`
- `SNAPSHOT_STARTED` / `SNAPSHOT_COMPLETED` / `SNAPSHOT_FAILED`

## Result Objects

All methods return result objects with a shared base structure plus
operation-specific fields:

- `success` - Boolean indicating success
- `migrations_applied` - List of applied version strings/script names on migration status results such as `MigrateResult` and `InfoResult`
- `migrations` - List of migration records on migration status results such as `MigrateResult`, `ValidateResult`, and `InfoResult`
- `errors` / `error_message` - Error details when present
- `execution_time_ms` - Execution time in milliseconds

## See Also

- [CLI Reference](cli.md) - Command-line interface
- [User Guide](../user-guide/getting-started.md) - Usage examples
- [Architecture](../architecture/overview.md) - System architecture
