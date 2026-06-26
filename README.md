# DBLift User Guide

<p align="center">
  <img src="logo/dblift_logo.png" width="280" alt="DBLift Logo">
</p>

**Manage your database changes with confidence**

DBLift helps you track and apply database changes systematically. Think of it as version control for your database schema - every change is tracked, can be rolled back, and works consistently across different environments.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/License-Apache--2.0-blue)

[![Unit Tests](https://github.com/cmodiano/dblift-oss/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/cmodiano/dblift-oss/actions/workflows/unit-tests.yml)
[![codecov](https://codecov.io/gh/cmodiano/dblift-oss/graph/badge.svg)](https://codecov.io/gh/cmodiano/dblift-oss)
[![Security Policy](https://img.shields.io/badge/Security-Policy-green)](SECURITY.md)

---

## Table of Contents

1. [Getting Started](#getting-started)
   - [Installation](#installation)
   - [Your First Migration](#your-first-migration)
2. [Integrations](#integrations)
   - [Django](#django)
   - [FastAPI](#fastapi)
   - [Flask](#flask)
   - [OpenTelemetry](#opentelemetry)
3. [Understanding the Basics](#understanding-the-basics)
   - [What are Migrations?](#what-are-migrations)
   - [How Migration Files Work](#how-migration-files-work)
4. [Common Tasks](#common-tasks)
   - [Applying Changes to Your Database](#applying-changes-to-your-database)
   - [Checking Migration Status](#checking-migration-status)
   - [Rolling Back Changes](#rolling-back-changes)
   - [Working with Existing Databases](#working-with-existing-databases)
5. [Everyday Commands](#everyday-commands)
6. [Organizing Your Migrations](#organizing-your-migrations)
7. [Configuration Guide](#configuration-guide)
8. [Best Practices](#best-practices)
9. [Troubleshooting](#troubleshooting)
10. [Advanced Commands](#advanced-commands)
11. [Running in CI/CD](#running-in-cicd)
12. [API Reference](#api-reference)
13. [Need More Help?](#need-more-help)

---

## Getting Started

### Installation

<!-- BEGIN: OSS README sync: python-install -->
#### Python / pip install

| Install | Dialects |
| --- | --- |
| `pip install dblift[postgresql]` | PostgreSQL (OSS) |
| `pip install dblift[oracle]` | Oracle (OSS) |

`pytest-dblift` quickstart:

```bash
pip install pytest-dblift
```

```python
# tests/test_foo.py
import pytest

def test_something(dblift_migrated_db, dblift_client):
    # dblift_migrated_db ensures migrations applied (function scope by default)
    result = dblift_client.info()
    assert result.pending_count == 0
```
<!-- END: OSS README sync: python-install -->

#### Using the Python SDK

**Synchronous client:**

```python
from sqlalchemy import create_engine
from api import DBLiftClient

engine = create_engine("postgresql+psycopg://user:pass@localhost/app")
with DBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations") as client:
    client.migrate()
```

**Asynchronous client** (for asyncio apps like FastAPI — runs the sync client
in a worker thread so it never blocks the event loop):

```python
from sqlalchemy import create_engine
from api.async_client import AsyncDBLiftClient

engine = create_engine("postgresql+psycopg://user:pass@localhost/app")
async with AsyncDBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations") as client:
    await client.migrate()
```

See [Async usage](docs/user-guide/async.md) for the full guide.

### Your First Migration

Let's create your first database change in 4 simple steps:

**Step 1: Create a Project Folder**

Create a folder for your database project and navigate to it:
```bash
mkdir my-database-project
cd my-database-project
```

**Step 2: Tell DBLift About Your Database**

Create a file called `dblift.yaml` with your database connection details:

```yaml
database:
  url: "postgresql+psycopg://localhost:5432/mydb"
  schema: "public"
  username: "myuser"
  password: "mypassword"

migrations:
  directory: "./migrations"
```

> **Tip**: Replace the values above with your actual database details. Install the matching driver extra, for example `dblift[postgresql]`, `dblift[mysql]`, `dblift[oracle]`, `dblift[sqlserver]`, or `dblift[db2]`.

**Step 3: Create Your First Migration File**

Create a folder called `migrations` and add your first migration file:

```bash
mkdir migrations
```

Create a file: `migrations/V1_0_0__create_users_table.sql`

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE
);
```

> **What's with the filename?** The `V1_0_0` is the version number, and everything after `__` (double underscore) is a description. This naming helps DBLift track which changes have been applied.

**Step 4: Apply Your Migration**

Run this command:
```bash
dblift migrate
```

That's it! DBLift will create the `users` table in your database and remember that this migration has been applied.

---

## Integrations

dblift works standalone via the CLI/SDK, and also plugs into common Python
frameworks:

| Integration | What it gives you | Guide |
|---|---|---|
| Django | Management commands + a pending-migrations system check, alongside Django's own ORM migrations | [Django](#django) |
| FastAPI | Lifespan helpers that block app startup on unapplied migrations | [FastAPI](#fastapi) |
| Flask | App-factory wiring + a `flask dblift-migrate` CLI command | [Flask](#flask) |
| OpenTelemetry | Spans for `migrate`/`undo`/etc., driven off the event bus | [OpenTelemetry](#opentelemetry) |

## Django

dblift provides Django management commands and a system check. It
**complements** Django's ORM migrations — use it for raw SQL, multiple or
heterogeneous databases, cross-dialect work, and rollback. See
[Django integration](docs/user-guide/django.md).

## FastAPI

```bash
pip install "dblift[fastapi]"
```

Use `integrations.fastapi` to block app startup on unapplied migrations:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import create_engine

from api import DBLiftClient
from integrations.fastapi import migration_guard

engine = create_engine("postgresql+psycopg://user:pass@localhost/app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    with DBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations") as client:
        migration_guard(client)  # raises if migrations are pending
    yield

app = FastAPI(lifespan=lifespan)
```

The helpers only inspect state via `client.info()` — they never call
`migrate()` themselves. See [FastAPI lifespan guide](docs/examples/fastapi-lifespan.md).

## Flask

```bash
pip install "dblift[flask]"
```

Use `integrations.flask` with your app factory to protect startup and register
a `flask dblift-migrate` command:

```python
from flask import Flask
from sqlalchemy import create_engine

from api import DBLiftClient
from integrations.flask import init_dblift, register_cli

def create_app() -> Flask:
    app = Flask(__name__)
    engine = create_engine("postgresql+psycopg://user:pass@localhost/app")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations")
    init_dblift(app, client)
    register_cli(app, client)
    return app
```

See [Flask integration guide](docs/examples/flask-integration.md).

## OpenTelemetry

```bash
pip install "dblift[otel]"
```

```python
from sqlalchemy import create_engine
from api import DBLiftClient
from integrations.opentelemetry import instrument

engine = create_engine("postgresql+psycopg://user:pass@localhost/app")
client = DBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations")
instrument(client)   # opt-in, per client — emits dblift.migrate + dblift.script spans
client.migrate()
```

Bring your own OTel SDK and exporter. See [OpenTelemetry tracing](docs/user-guide/opentelemetry.md).

---

## Understanding the Basics

### What are Migrations?

Migrations are versioned change scripts (typically `.sql`, or `.py` when you need logic beyond SQL). Each file represents one change (like creating a table, adding a column, or inserting data).

Think of migrations as a recipe book for your database:
- Each recipe (migration file) describes one change
- They're numbered in order
- DBLift keeps track of which recipes you've already followed
- You can always see what's been done and what's pending

> **Ordering default:** DBLift is out-of-order by default. If version `3` is
> already applied and version `2` appears later, DBLift treats version `2` as a
> pending migration and can apply it. This is the opposite of Flyway's default.
> Use `--strict` on `migrate` / `validate`, or set `strict_mode: true` in
> `dblift.yaml`, when you want to preserve strict version order.

### How Migration Files Work

Migration files follow a naming pattern that tells DBLift important information:

```
V1_0_0__create_users_table.sql
│││││││└─ Description (what this change does)
│││││││
││││││└─ Double underscore separator
│││││└─ Version number (1.0.0)
││││└─ Version type (V = versioned migration)
```

**Three Types of Migrations:**

1. **Versioned Migrations** (Start with `V`)
   - Run once, in order
   - Example: `V1_0_0__create_users_table.sql`
   - Use for: Creating tables, adding columns, schema changes

2. **Repeatable Migrations** (Start with `R`)
   - Re-run whenever the file changes
   - Example: `R__create_dashboard_view.sql` (same extensions as versioned scripts, for example `.py`, where supported)
   - Use for: Views, stored procedures, functions

3. **Undo Migrations** (Start with `U`)
   - Reverse a specific versioned migration
   - Example: `U1_0_0__drop_users_table.sql` (same extensions as versioned scripts where supported)
   - Use for: Rolling back changes when needed

**Migration Script Formats:**

- **SQL** (`.sql`) — standard format for most schema changes
- **Python** (`.py`) — for migrations requiring logic beyond SQL
  - The script must expose a `migrate(context)` function
  - DBLift creates a `MigrationContext` for the active migration run and passes it to that function
  - Import `MigrationContext` from `api` for type hints; do not instantiate it in the script
  - Example: `V2__seed_lookup_tables.py`

```python
# migrations/V2__seed_lookup_tables.py
from api import MigrationContext

def migrate(context: MigrationContext) -> None:
    """Seed initial lookup data using the injected DBLift context."""
    context.log.info("Seeding role lookup data")
    if context.dry_run:
        context.log.info("[DRY-RUN] would insert default roles")
        return

    schema_prefix = f"{context.schema}." if context.schema else ""
    rows = [("admin", "Administrator"), ("user", "Standard User")]
    for code, label in rows:
        context.execute(
            f"INSERT INTO {schema_prefix}roles (code, label) VALUES (?, ?)",
            [code, label],
        )

def undo(context: MigrationContext) -> None:
    """Optional rollback for `dblift undo`."""
    if context.dry_run:
        return
    context.execute(
        "DELETE FROM roles WHERE code IN (?, ?)",
        ["admin", "user"],
    )
```

---

## Common Tasks

### Applying Changes to Your Database

**See what needs to be applied:**
```bash
dblift info
```
This shows you which migrations are pending (not yet applied) and which are already done.

**Apply pending migrations:**
```bash
dblift migrate
```
This will run all migrations that haven't been applied yet. DBLift allows
out-of-order versioned migrations by default, so an older version that appears
after newer versions have already run is still considered pending.

To make ordering strict:

```bash
dblift migrate --strict
dblift validate --strict
```

**Preview changes before applying:**
```bash
dblift migrate --dry-run
```
This shows you which migrations would run without making changes. Add `--show-sql` to include the SQL statements in the output.

### Checking Migration Status

**View all migrations:**
```bash
dblift info
```

You'll see the current migration table. This extract was generated from the
current renderer with two applied SQLite migrations and one pending migration:
```
╭────────────┬─────────┬─────────────────────┬──────┬─────────────────────┬──────────────┬─────────┬───────────┬──────────╮
│ Category   │ Version │ Description         │ Type │ Installed On        │ Installed By │ State   │ Exec Time │ Undoable │
├────────────┼─────────┼─────────────────────┼──────┼─────────────────────┼──────────────┼─────────┼───────────┼──────────┤
│ Versioned  │ 1       │ create_users_table  │ SQL  │ 2026-06-17 22:01:23 │              │ Success │           │    No    │
│ Versioned  │ 2       │ add_email_column    │ SQL  │ 2026-06-17 22:01:23 │              │ Success │           │    No    │
│ Versioned  │ 3       │ create_orders_table │ SQL  │                     │              │ Pending │           │    No    │
╰────────────┴─────────┴─────────────────────┴──────┴─────────────────────┴──────────────┴─────────┴───────────┴──────────╯
Total migrations: 3
```
**Category** is the migration kind, **Type** is the script type, and **State**
is `Success`, `Pending`, or another migration status. **Undoable** tells you
whether a matching undo migration is available.

### Rolling Back Changes

If you need to undo a migration:

**Step 1: Create an undo migration**

For each versioned migration `V1_0_1__add_email_column.sql`, create a matching undo file `U1_0_1__remove_email_column.sql`:

```sql
-- U1_0_1__remove_email_column.sql
ALTER TABLE users DROP COLUMN email;
```

**Step 2: Run the rollback**
```bash
dblift undo --target-version=1.0.0
```

This will undo all migrations after version 1.0.0.

### Working with Existing Databases

Already have a database with tables? Use baseline to tell DBLift where to start:

**Step 1: Check what DBLift sees:**
```bash
dblift info
```

**Step 2: Set a baseline version:**
```bash
dblift baseline --baseline-version=1.0.0 --baseline-description="Existing production database"
```

This tells DBLift: "Everything up to version 1.0.0 is already in the database, skip those migrations."

**Step 3: Apply new migrations:**
```bash
dblift migrate
```

Now only migrations after version 1.0.0 will be applied.

## Everyday Commands

Here are the commands you'll use most often:

| Command | What it does | When to use it |
|---------|--------------|----------------|
| `dblift info` | Shows status of all migrations | Check what's applied and what's pending |
| `dblift migrate` | Applies pending migrations | Deploy database changes |
| `dblift migrate --dry-run` | Preview without applying | Check what will happen before doing it |
| `dblift migrate --dry-run --show-sql` | Preview migrations and SQL without applying | Review exact SQL before execution |
| `dblift undo --dry-run --show-sql` | Preview undo scripts and SQL without applying | Review rollback SQL before execution |
| `dblift undo --target-version=X` | Rolls back to a specific version | Reverse recent changes |
| `dblift validate` | Checks migrations for errors | Before applying changes |
| `dblift baseline --baseline-version=X` | Mark migrations as already applied | Working with existing databases |

**Quick Examples:**

```bash
# The usual workflow
dblift info                    # See what's pending
dblift validate               # Check for errors
dblift migrate                # Apply changes

# Rolling back
dblift undo --target-version=1.0.0

# Working with existing databases
dblift baseline --baseline-version=2.0.0

```

---

## Organizing Your Migrations

### Basic Structure

```
my-project/
├── dblift.yaml              # Configuration file
└── migrations/              # Your migration files
    ├── V1_0_0__create_users.sql
    ├── V1_0_1__add_orders.sql
    └── V1_0_2__add_products.sql
```

### Multi-Module Projects

For larger projects, you can organize migrations by feature or module:

```
my-project/
├── dblift.yaml
├── core/
│   └── migrations/
│       ├── V1_0_0__core_tables.sql
│       └── V1_0_1__core_functions.sql
├── auth/
│   └── migrations/
│       └── V2_0_0__auth_tables.sql
└── billing/
    └── migrations/
        └── V3_0_0__billing_tables.sql
```

Then in your `dblift.yaml`:
```yaml
migrations:
  directories:
    - ./core/migrations
    - ./auth/migrations
    - ./billing/migrations
```

**Per-Directory Recursive Settings:**

You can control whether each directory is searched recursively:

```yaml
migrations:
  directories:
    - path: ./core/migrations
      recursive: true    # Search subdirectories
    - path: ./auth/migrations
      recursive: false   # Only top-level files
    - path: ./billing/migrations
      recursive: true    # Search subdirectories
  recursive: true  # Global default (used if recursive not specified per directory)
```

This is useful when some directories have a flat structure (no subdirectories needed) while others are organized in subdirectories.

### Using Tags

Add tags to migration filenames to group related changes:

```
V1_0_0__create_users[core,init].sql
V1_0_1__create_auth[core,auth].sql
V2_0_0__add_billing[billing].sql
```

Deploy specific modules:
```bash
# Deploy only auth-related migrations
dblift migrate --tags=auth

# Deploy everything except billing
dblift migrate --exclude-tags=billing
```

---

## Configuration Guide

### Basic Configuration

Create a `dblift.yaml` file in your project root:

```yaml
database:
  url: "postgresql+psycopg://localhost:5432/mydb"
  schema: "public"
  username: "myuser"
  password: "mypassword"

migrations:
  directory: "./migrations"  # Single directory (legacy format)
  recursive: true  # Whether to search subdirectories (default: true)

```

**Multiple Directories:**

You can specify multiple migration directories. The first one is the primary directory:

```yaml
migrations:
  directories:
    - ./migrations/core      # Primary directory
    - ./migrations/features  # Additional directory
  recursive: true  # Global default for all directories
```

**Per-Directory Recursive Settings:**

Control recursive search per directory. Useful when some directories have subdirectories and others don't:

```yaml
migrations:
  directories:
    - path: ./migrations/core
      recursive: true    # Search subdirectories recursively
    - path: ./migrations/features
      recursive: false   # Only top-level files, no subdirectories
    - ./migrations/performance  # Uses global recursive setting (true)
  recursive: true  # Global default for directories without explicit recursive setting
```

**Mixed Format:**

You can mix string and dict formats in the same configuration:

```yaml
migrations:
  directories:
    - ./migrations/core                    # String format (uses global recursive)
    - path: ./migrations/features
      recursive: false                     # Dict format (per-directory setting)
```

### Supported Databases

DBLift works with these databases:

| Database | Connection URL Example | Driver extra |
|----------|------------------------|--------------|
| PostgreSQL | `postgresql+psycopg://localhost:5432/mydb` | `dblift[postgresql]` |
| SQL Server | `mssql+pymssql://localhost:1433/mydb` | `dblift[sqlserver]` |
| Oracle | `oracle+oracledb://localhost:1521?sid=SID` | `dblift[oracle]` |
| MySQL | `mysql+pymysql://localhost:3306/mydb` | `dblift[mysql]` |
| MariaDB | `mysql+pymysql://localhost:3306/mydb` | `dblift[mariadb]` |
| DB2 | `ibm_db_sa://localhost:50000/mydb` | `dblift[db2]` |
| SQLite | `/path/to/database.db` or `:memory:` (see [SQLite Configuration](#sqlite-configuration)) |
| Azure Cosmos DB | `https://account.documents.azure.com:443/` (see [CosmosDB Configuration](#cosmosdb-configuration)) |

### SQLite Configuration

SQLite uses a simpler configuration format since it's a file-based database:

```yaml
database:
  type: "sqlite"
  path: "/path/to/database.db"  # Or use ":memory:" for in-memory database
  schema: "main"                 # SQLite's default schema
```

**In-Memory Database (for testing):**
```yaml
database:
  type: "sqlite"
  path: ":memory:"
  schema: "main"
```

**Using Environment Variables:**
```bash
export DBLIFT_DB_TYPE="sqlite"
export DBLIFT_DB_PATH="/path/to/database.db"
```

**SQLite-Specific Notes:**
- SQLite uses Python's native `sqlite3` module
- No username/password needed (SQLite doesn't have authentication)
- Schema is always "main" (SQLite doesn't support multiple schemas)
- File path can be absolute or relative to the working directory
- Use `:memory:` for an in-memory database (useful for testing)

### CosmosDB Configuration

Azure Cosmos DB uses a different configuration format through the Azure SDK:

```yaml
database:
  type: "cosmosdb"
  account_endpoint: "https://your-account.documents.azure.com:443/"
  account_key: "your-account-key"  # Or use managed identity
  database_name: "your-database"
  # Optional: use managed identity instead of account_key
  # use_managed_identity: true
```

**For Local Development (CosmosDB Emulator):**
```yaml
database:
  type: "cosmosdb"
  account_endpoint: "https://localhost:8081/"
  account_key: "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
  database_name: "your-database"
```

**Using Environment Variables:**
```bash
export DBLIFT_DB_TYPE="cosmosdb"
export DBLIFT_DB_ACCOUNT_ENDPOINT="https://your-account.documents.azure.com:443/"
export DBLIFT_DB_ACCOUNT_KEY="your-account-key"
export DBLIFT_DB_DATABASE_NAME="your-database"
```

### Using Environment Variables

Instead of putting passwords in `dblift.yaml`, use environment variables:

```bash
export DBLIFT_DB_URL="postgresql+psycopg://localhost:5432/mydb"
export DBLIFT_DB_USERNAME="myuser"
export DBLIFT_DB_PASSWORD="mypassword"
```

---

## Best Practices

### 1. Always Preview Before Applying

Use `--dry-run` to see what will happen:
```bash
dblift migrate --dry-run
```

### 2. Version Numbers Matter

Use a consistent versioning scheme:
- **Major.Minor.Patch**: `V1_0_0`, `V1_0_1`, `V1_1_0`, `V2_0_0`
- Increment patch for small changes
- Increment minor for new features
- Increment major for breaking changes

### 3. Make Migrations Reversible

For every migration, consider creating an undo migration:
```
V1_0_1__add_email_column.sql
U1_0_1__remove_email_column.sql
```

### 4. Keep Migrations Small

One change per migration makes them easier to:
- Understand
- Review
- Roll back if needed
- Debug when something goes wrong

### 5. Test in Development First

Always test migrations on a development database before production:
```bash
# On dev database
dblift info
dblift migrate --dry-run
dblift migrate

# Verify everything works
# Then apply to production
```

### 6. Use Descriptive Names

Good migration names tell you what they do:
- ✅ `V1_0_1__add_user_email_column.sql`
- ✅ `V1_0_2__create_orders_table.sql`
- ❌ `V1_0_1__changes.sql`
- ❌ `V1_0_2__updates.sql`

### 7. Don't Modify Applied Migrations

Once a migration has been applied to any database (especially production), never change it. Instead:
- Create a new migration to fix issues
- Keep the history intact

---

## Troubleshooting

### "Migration already applied" Error

**Problem**: You see an error saying a migration was already applied.

**Solution**: Check which migrations are applied:
```bash
dblift info
```

If you see the migration listed as applied, it's already been run. If you need to make changes, create a new migration instead.

### Can't Connect to Database

**Problem**: DBLift can't connect to your database.

**Solution**: 
1. Check your `dblift.yaml` file has the correct connection details
2. Verify your database is running
3. Test the connection with your database client first
4. Make sure your username and password are correct

### Wrong Migrations Applied

**Problem**: You applied migrations to the wrong database or need to undo changes.

**Solution**: Use the undo command:
```bash
# Roll back to a specific version
dblift undo --target-version=1.0.0
```

Note: You need undo migrations (`U*.sql` files) for this to work.

### "File encoding" or Special Character Issues

**Problem**: Special characters (é, ñ, ö, etc.) in your SQL files aren't working.

**Solution**: Add encoding to your `dblift.yaml`:
```yaml
migrations:
  script_encoding: "utf-8"
```

DBLift decodes migration files strictly with `script_encoding` by default. To detect the script encoding before reading:

```yaml
migrations:
  script_encoding: "utf-8"
  detect_encoding: true
```

If detection or decoding fails, DBLift stops with an encoding error instead of silently replacing accented characters.

### Migration Out of Order

**Problem**: Someone created a migration with an older version number than what's already applied.

**Solution**: 
1. Rename the migration file with a newer version number
2. Or use `--mark-as-executed` if you need to skip it:
```bash
dblift migrate --mark-as-executed --versions=1.0.5
```

### Want to Start Fresh

**Problem**: You want to remove all migrations and start over.

**Solution**: Use the clean command (⚠️ **Warning: This deletes all managed objects!**):
```bash
dblift clean --dry-run  # Preview first
dblift clean            # Actually clean
```

---

## Advanced Commands

### Repairing Migration History

If your migration history table gets corrupted or out of sync:

**Check for issues:**
```bash
dblift validate
```

**Repair the history table:**
```bash
dblift repair
```

This will:
- Recalculate checksums for applied migrations
- Fix any inconsistencies in the history table
- Ensure history matches migration files

### Importing from Flyway

Migrating from Flyway to DBLift? Import your existing migration history:

```bash
dblift import-flyway
```

This imports records from Flyway's `flyway_schema_history` table into DBLift's history table.
The default Flyway source table name is `flyway_schema_history` for every database.
If Flyway uses a custom source table, pass `--flyway-table`:

```bash
dblift import-flyway --flyway-table custom_flyway_history
```

Use `--table` only to choose the target DBLift history table:

```bash
dblift import-flyway --flyway-table custom_flyway_history --table dblift_schema_history
```

### Database Utilities

**List available drivers:**
```bash
dblift db list-drivers
```

**Check database connection:**
```bash
dblift db check-connection
```

**Validate configuration:**
```bash
dblift db validate-config
```

**Diagnose connection issues:**
```bash
dblift db diagnose-connection
```

---

## Running in CI/CD

dblift is a pip package with no system dependencies — CI is `pip install` plus a
command. See [CI/CD recipes](docs/user-guide/ci-cd.md) for copy-paste GitHub
Actions, GitLab CI, and pre-commit configurations (OSS `validate` / `info`).

## API Reference

The Python SDK (`DBLiftClient`, `AsyncDBLiftClient`, `MigrationContext`), CLI,
core, and database layers are all documented from docstrings:

- [API reference](docs/api-reference/api.md) — `DBLiftClient` / `AsyncDBLiftClient`
- [CLI reference](docs/api-reference/cli.md)
- [Core reference](docs/api-reference/core.md)
- [Database providers reference](docs/api-reference/db.md)
- [Events reference](docs/api-reference/events.md)

## Need More Help?

### Documentation

For advanced features and technical details, see:

- **[Documentation index](docs/README.md)** - User guide, API reference, and architecture topics
- **[Cosmos DB configuration](docs/user-guide/configuration.md#cosmos-db)** - Account settings and emulator

### Configuration Templates

Use the [configuration guide](docs/user-guide/configuration.md) for database-specific
settings and copy-paste examples.

### Common Questions

**Q: Can I use DBLift with Docker?**
A: Yes. Install DBLift in your application image or CI job, then run the same `dblift validate`, `dblift info`, and `dblift migrate` commands you use locally. See [CI/CD recipes](docs/user-guide/ci-cd.md).

**Q: Is there a GUI?**
A: No, DBLift is a command-line tool. This keeps it simple and automation-friendly.

**Q: Can multiple developers use DBLift on the same database?**
A: Yes, DBLift tracks which migrations have been applied in the database itself. All developers can run `dblift migrate` and only pending migrations will be applied.

**Q: What happens if a migration fails?**
A: DBLift automatically rolls back the failed migration so your database stays in a consistent state.

**Q: Can I run migrations in CI/CD pipelines?**
A: Yes. Install DBLift with the database driver extra for your target database, provide the connection through environment variables or `dblift.yaml`, then run `dblift validate` and `dblift migrate`. See [CI/CD recipes](docs/user-guide/ci-cd.md).

---

## License

DBLift is licensed under the Apache License, Version 2.0. See the LICENSE file for details.

---

## Quick Reference Card

```bash
# Setup
dblift --version                                    # Check installation

# Daily workflow
dblift info                                         # Check status
dblift validate                                     # Validate migrations
dblift migrate                                      # Apply changes
dblift migrate --dry-run                           # Preview changes
dblift migrate --dry-run --show-sql                # Preview SQL without applying
dblift undo --dry-run --show-sql                   # Preview rollback SQL without applying

# Working with existing databases
dblift baseline --baseline-version=1.0.0           # Set starting point

# Rollback
dblift undo --target-version=1.0.0                 # Roll back to version

# Organization
dblift migrate --tags=core                         # Apply tagged migrations
dblift migrate --scripts=./migrations/core --scripts=./migrations/features  # Multiple directories
dblift info --scripts=./custom/migrations          # Use different directory
```

---

**Ready to get started?** Jump back to [Your First Migration](#your-first-migration)!
