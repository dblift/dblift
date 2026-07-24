# Getting Started with DBLift

DBLift is a Python-native migration toolkit. This guide takes you from install to your first migration in under five minutes, using only OSS commands.

## Prerequisites

- Python 3.11+
- A running PostgreSQL database (local Docker is fine)
- A connection URL for that database

## Step 1: Install

```bash
pip install "dblift[postgresql]"
dblift --version
```

Other supported extras: `dblift[oracle]`, `dblift[mysql]`, `dblift[sqlserver]`.

## Step 2: Configure

Set your connection URL as an environment variable:

```bash
export DBLIFT_DB_URL="postgresql+psycopg://user:password@localhost:5432/mydb"
```

The rest of this guide uses that variable — all commands below work as-is once it is set.

**Using a config file instead:** create `dblift.yaml` in your project root:

```yaml
database:
  url: "postgresql+psycopg://user:password@localhost:5432/mydb"
  schema: "public"

migrations:
  directory: "./migrations"
```

dblift does not auto-discover `dblift.yaml`. When using a config file, pass `--config dblift.yaml` with every command (e.g. `dblift --config dblift.yaml info`). The env var approach skips that flag.

**More than one environment?** One file can describe them all — declare
`environments:` blocks (dev, staging, prod, …) and select with `--env <name>`.
See [Configuration → Environments](configuration.md#environments).

## Step 3: Create your first migration

```bash
mkdir migrations
```

Create `migrations/V1_0_0__create_users_table.sql`:

```sql
CREATE TABLE users (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE
);
```

Migration filenames follow the pattern `V<version>__<description>.sql`. The version determines apply order.

## Step 4: Check state

```bash
dblift validate
```

`validate` checks that your migration files are internally consistent and match the recorded history. Run it before applying. No errors means you are ready.

```bash
dblift info
```

`info` shows the full migration table — which versions are applied, which are pending, and whether each has a matching undo file.

## Step 5: Preview SQL before applying

This is the step most migration tools skip.

```bash
dblift migrate --dry-run --show-sql
```

DBLift prints every SQL statement your pending migrations would execute — without touching the database. Check the output, confirm it matches your intent, then apply.

## Step 6: Apply

```bash
dblift migrate
```

DBLift applies all pending migrations in version order and records each one in its history table. Run `dblift info` again to confirm.

## Step 7: Roll back (optional)

If you need to undo, create a matching undo file alongside the original migration.

`migrations/U1_0_0__drop_users_table.sql`:

```sql
DROP TABLE users;
```

Then:

```bash
dblift undo --dry-run --show-sql    # preview rollback SQL first
dblift undo --target-version=0      # roll back to before V1_0_0
```

## Typical daily workflow

```bash
dblift info                          # what is the current state?
dblift validate                      # are migration files consistent?
dblift migrate --dry-run --show-sql  # what SQL will run?
dblift migrate                       # apply when ready
```

## Running in CI/CD

DBLift has no system dependencies beyond Python and the database driver — CI setup is `pip install` plus a command. Copy-paste GitHub Actions and GitLab CI examples are in [CI/CD recipes](ci-cd.md).

## Using the Python SDK

You can call DBLift directly from Python instead of the CLI:

```python
from sqlalchemy import create_engine
from api import DBLiftClient

engine = create_engine("postgresql+psycopg://user:password@localhost:5432/mydb")
with DBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations") as client:
    client.validate()
    client.migrate(dry_run=True, show_sql=True)
    client.migrate()
```

For FastAPI, Django, and Flask integration guides, see the [README integrations section](../../README.md#integrations).

## Working with an existing database

If your database already has tables and you are adopting DBLift mid-project, use baseline to tell DBLift where to start:

```bash
dblift baseline --baseline-version=1.0.0 --baseline-description="Existing schema"
```

This marks everything up to `1.0.0` as already applied. Only migrations after that version will run going forward.

## What Pro adds

The commands in this guide are all OSS (Apache 2.0). When your team needs stronger review controls:

| Feature | Command | What it does |
|---|---|---|
| Static SQL analysis | `dblift validate-sql` | Lints migration files with rule-based checks — catches issues before they reach the database. Built-in rule profiles (core, enterprise, strict). CI-friendly output formats (GitHub Actions, SARIF, GitLab). |
| Schema drift detection | `dblift diff` | Detects drift between the live database and what your migrations define. |
| Schema export | `dblift export-schema` | Exports the current schema to SQL migration files — useful for brownfield onboarding. |

[See Pro features and pricing →](https://dblift.com/pricing)

## Next steps

- [Commands reference](commands.md) — full CLI options and flags
- [Configuration guide](configuration.md) — all `dblift.yaml` options and environment variables
- [CI/CD recipes](ci-cd.md) — GitHub Actions, GitLab CI, and pre-commit hook examples
- [Best practices](best-practices.md) — naming conventions, rollback strategy, team workflows
